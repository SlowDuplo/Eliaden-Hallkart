#!/usr/bin/env python3
"""Generate the static hall-map image and booth directory from an exhibition PDF."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

import pymupdf


BOOTH_CODE = re.compile(r"^(?:[A-Z]\d{2}-\d{2}|UR-\d{2}|[A-Z]\d-\d)$")


def parse_crop(value: str) -> tuple[float, float, float, float]:
    try:
        coordinates = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Crop must be four comma-separated PDF coordinates.") from error
    if len(coordinates) != 4 or coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
        raise argparse.ArgumentTypeError("Crop must be x0,y0,x1,y1 with positive width and height.")
    return coordinates  # type: ignore[return-value]


def detect_map_crop(page: pymupdf.Page) -> pymupdf.Rect:
    hall_shapes = []
    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        rect = drawing["rect"]
        if (
            fill
            and min(fill) >= 0.95
            and rect.width >= page.rect.width * 0.08
            and rect.height >= page.rect.height * 0.25
        ):
            hall_shapes.append(rect)

    if not hall_shapes:
        raise ValueError(
            "Could not auto-detect the hall artwork. Pass --map-crop x0,y0,x1,y1 "
            "using coordinates in PDF points."
        )

    crop = pymupdf.Rect(
        min(rect.x0 for rect in hall_shapes) - page.rect.width * 0.015,
        min(rect.y0 for rect in hall_shapes) - page.rect.height * 0.08,
        max(rect.x1 for rect in hall_shapes) + page.rect.width * 0.01,
        max(rect.y1 for rect in hall_shapes) + page.rect.height * 0.01,
    )
    return crop & page.rect


def hall_for(stand: str) -> str:
    return "U" if stand.startswith("UR-") else stand[0]


def text_words_on_row(
    words: list[tuple], code_word: tuple, column_left: float, tolerance: float
) -> str:
    x0, y0, x1, y1, *_ = code_word
    center_y = (y0 + y1) / 2
    row = [
        word
        for word in words
        if abs((word[1] + word[3]) / 2 - center_y) <= tolerance
        and column_left <= (word[0] + word[2]) / 2 < x0
        and not BOOTH_CODE.fullmatch(word[4])
    ]
    return " ".join(word[4] for word in sorted(row, key=lambda word: word[0])).strip()


def extract_booths(page: pymupdf.Page, crop: pymupdf.Rect) -> list[dict]:
    words = page.get_text("words")
    code_words = [word for word in words if BOOTH_CODE.fullmatch(word[4])]

    def inside_crop(word: tuple) -> bool:
        center_x = (word[0] + word[2]) / 2
        center_y = (word[1] + word[3]) / 2
        return crop.x0 <= center_x <= crop.x1 and crop.y0 <= center_y <= crop.y1

    table_words = [word for word in code_words if not inside_crop(word)]
    map_words = [word for word in code_words if inside_crop(word)]
    if not table_words:
        raise ValueError("No exhibitor-table booth numbers were found outside the map crop.")
    if not map_words:
        raise ValueError("No booth labels were found inside the map crop; check --map-crop.")

    column_centers: list[float] = []
    cluster_distance = page.rect.width * 0.004
    for word in sorted(table_words, key=lambda word: (word[0] + word[2]) / 2):
        center = (word[0] + word[2]) / 2
        if not column_centers or center - column_centers[-1] > cluster_distance:
            column_centers.append(center)
        else:
            column_centers[-1] = (column_centers[-1] + center) / 2

    gaps = [right - left for left, right in zip(column_centers, column_centers[1:])]
    column_width = statistics.median(gaps) * 0.95 if gaps else page.rect.width * 0.09
    code_heights = [word[3] - word[1] for word in table_words]
    row_tolerance = max(1.5, statistics.median(code_heights) * 0.75)

    booths: dict[str, dict] = {}
    for word in table_words:
        center_x = (word[0] + word[2]) / 2
        column_center = min(column_centers, key=lambda center: abs(center - center_x))
        stand = word[4]
        name = text_words_on_row(words, word, column_center - column_width, row_tolerance)
        if not name:
            raise ValueError(
                f"Could not read the exhibitor name for {stand}. Check the PDF table "
                "layout and the selected page."
            )
        booth = booths.setdefault(
            stand,
            {"stand": stand, "hall": hall_for(stand), "exhibitors": [], "locations": []},
        )
        if name not in booth["exhibitors"]:
            booth["exhibitors"].append(name)

    for word in map_words:
        stand = word[4]
        center_x = (word[0] + word[2]) / 2
        center_y = (word[1] + word[3]) / 2
        booth = booths.setdefault(
            stand,
            {"stand": stand, "hall": hall_for(stand), "exhibitors": [], "locations": []},
        )
        booth["locations"].append(
            {
                "x": round((center_x - crop.x0) / crop.width, 6),
                "y": round((center_y - crop.y0) / crop.height, 6),
            }
        )

    for booth in booths.values():
        booth["exhibitors"].sort(key=str.casefold)
        booth["locations"].sort(key=lambda point: (point["y"], point["x"]))

    return sorted(booths.values(), key=lambda booth: booth["stand"])


def infer_year(pdf_path: Path) -> str:
    parts = re.split(r"[-_]+", pdf_path.stem)
    full_year = next((part for part in parts if re.fullmatch(r"20\d{2}", part)), "")
    if full_year:
        return full_year
    if len(parts) > 1 and re.fullmatch(r"\d{2}", parts[1]):
        return f"20{parts[1]}"
    return ""


def infer_event_name(pdf_path: Path) -> str:
    parts = re.split(r"[-_]+", pdf_path.stem)
    name = next((part for part in parts if not re.fullmatch(r"\d{2}|20\d{2}", part)), "")
    return name.replace("_", " ").strip().title() or "Event"


def write_outputs(
    pdf_path: Path,
    output_dir: Path,
    page_number: int,
    crop: pymupdf.Rect,
    page: pymupdf.Page,
    booths: list[dict],
    event: dict[str, str],
) -> None:
    image_path = output_dir / "assets" / "hall-map.png"
    data_path = output_dir / "data" / "exhibitors.json"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.parent.mkdir(parents=True, exist_ok=True)

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=crop, alpha=False)
    pixmap.save(image_path)

    halls = sorted({booth["hall"] for booth in booths})
    data = {
        "event": event,
        "source_pdf": pdf_path.name,
        "halls": [{"id": hall, "label": f"Hall {hall}"} for hall in halls],
        "map": {
            "image": "./assets/hall-map.png",
            "page": page_number,
            "crop": [round(value, 2) for value in (crop.x0, crop.y0, crop.x1, crop.y1)],
            "image_size": [pixmap.width, pixmap.height],
        },
        "booths": booths,
    }
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    located = sum(bool(booth["locations"]) for booth in booths)
    print(f"Wrote {image_path} ({pixmap.width}×{pixmap.height})")
    print(f"Wrote {data_path} ({len(booths)} booths; {located} with map positions)")
    print(f"Map crop (PDF points): {crop.x0:.2f},{crop.y0:.2f},{crop.x1:.2f},{crop.y1:.2f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create hall-map artwork and exhibitors.json from an exhibition PDF."
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Input PDF with the hall plan and exhibitor table.")
    parser.add_argument("--output-dir", type=Path, default=Path("."), help="Site root for assets/ and data/.")
    parser.add_argument("--page", type=int, default=1, help="One-based PDF page containing the plan and table.")
    parser.add_argument(
        "--map-crop",
        type=parse_crop,
        help="Optional x0,y0,x1,y1 crop in PDF points; auto-detected by default.",
    )
    parser.add_argument("--event-name", help="Event name (inferred from the PDF filename if omitted).")
    parser.add_argument("--year", help="Event year (inferred from the PDF filename if omitted).")
    parser.add_argument("--dates", default="", help="Event dates to display in the page header.")
    parser.add_argument("--venue", default="", help="Event venue to display in the page header.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Input PDF does not exist: {pdf_path}")

    document = pymupdf.open(pdf_path)
    if args.page < 1 or args.page > len(document):
        raise ValueError(f"Page must be between 1 and {len(document)}.")

    page = document[args.page - 1]
    crop = pymupdf.Rect(args.map_crop) if args.map_crop else detect_map_crop(page)
    if not page.rect.contains(crop):
        raise ValueError(f"Map crop {tuple(crop)} extends outside the selected PDF page.")

    booths = extract_booths(page, crop)
    event_name = args.event_name or infer_event_name(pdf_path)
    event_year = args.year or infer_year(pdf_path)
    event = {
        "name": event_name,
        "year": event_year,
        "dates": args.dates,
        "venue": args.venue,
    }
    write_outputs(pdf_path, args.output_dir, args.page, crop, page, booths, event)


if __name__ == "__main__":
    main()
