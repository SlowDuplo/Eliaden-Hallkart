#!/usr/bin/env python3
"""Generate the static hall-map image and booth directory from an exhibition PDF."""

from __future__ import annotations

import argparse
import json
import math
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


def split_map_code_words(
    words: list[tuple], crop: pymupdf.Rect, page: pymupdf.Page
) -> list[tuple]:
    prefix_pattern = re.compile(r"^[A-Z]\d{1,2}-$")
    suffix_pattern = re.compile(r"^\d{1,2}$")
    map_words = []
    for word in words:
        center_x = (word[0] + word[2]) / 2
        center_y = (word[1] + word[3]) / 2
        if crop.x0 <= center_x <= crop.x1 and crop.y0 <= center_y <= crop.y1:
            map_words.append(word)

    combined_words = []
    used_suffixes = set()
    for prefix in map_words:
        if not prefix_pattern.fullmatch(prefix[4]):
            continue
        prefix_center_x = (prefix[0] + prefix[2]) / 2
        prefix_center_y = (prefix[1] + prefix[3]) / 2
        candidates = []
        for index, suffix in enumerate(map_words):
            if index in used_suffixes or not suffix_pattern.fullmatch(suffix[4]):
                continue
            suffix_center_x = (suffix[0] + suffix[2]) / 2
            suffix_center_y = (suffix[1] + suffix[3]) / 2
            max_line_height = max(prefix[3] - prefix[1], suffix[3] - suffix[1])
            if (
                suffix_center_y > prefix_center_y
                and suffix_center_y - prefix_center_y <= max_line_height * 1.5
                and abs(suffix_center_x - prefix_center_x) <= page.rect.width * 0.006
            ):
                candidates.append((suffix_center_y - prefix_center_y, index, suffix))

        if not candidates:
            continue
        _, suffix_index, suffix = min(candidates, key=lambda candidate: candidate[0])
        stand = f"{prefix[4]}{suffix[4]}"
        if not BOOTH_CODE.fullmatch(stand):
            continue
        used_suffixes.add(suffix_index)
        combined_words.append(
            (
                min(prefix[0], suffix[0]),
                min(prefix[1], suffix[1]),
                max(prefix[2], suffix[2]),
                max(prefix[3], suffix[3]),
                stand,
                *prefix[5:],
            )
        )
    return combined_words


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


def drawing_polygons(drawing: dict) -> list[list[tuple[float, float]]]:
    polygons = []
    path = []

    def finish_path() -> None:
        if len(path) >= 3:
            polygon = path.copy()
            if math.dist(polygon[0], polygon[-1]) <= 1e-4:
                polygon.pop()
            if len(polygon) >= 3:
                polygons.append(polygon)
        path.clear()

    def add_line(start: pymupdf.Point, end: pymupdf.Point) -> None:
        start_point = (start.x, start.y)
        end_point = (end.x, end.y)
        if path and math.dist(path[-1], start_point) > 1e-3:
            finish_path()
        if not path:
            path.append(start_point)
        path.append(end_point)

    for item in drawing["items"]:
        operation = item[0]
        if operation == "re":
            finish_path()
            rect = item[1]
            polygons.append([
                (rect.x0, rect.y0),
                (rect.x1, rect.y0),
                (rect.x1, rect.y1),
                (rect.x0, rect.y1),
            ])
        elif operation == "qu":
            finish_path()
            quad = item[1]
            polygons.append([
                (quad.ul.x, quad.ul.y),
                (quad.ur.x, quad.ur.y),
                (quad.lr.x, quad.lr.y),
                (quad.ll.x, quad.ll.y),
            ])
        elif operation == "l":
            add_line(item[1], item[2])
        elif operation == "c":
            start, control1, control2, end = item[1:]
            if path and math.dist(path[-1], (start.x, start.y)) > 1e-3:
                finish_path()
            if not path:
                path.append((start.x, start.y))
            for step in range(1, 9):
                t = step / 8
                inverse = 1 - t
                x = (
                    inverse**3 * start.x
                    + 3 * inverse**2 * t * control1.x
                    + 3 * inverse * t**2 * control2.x
                    + t**3 * end.x
                )
                y = (
                    inverse**3 * start.y
                    + 3 * inverse**2 * t * control1.y
                    + 3 * inverse * t**2 * control2.y
                    + t**3 * end.y
                )
                path.append((x, y))
        else:
            finish_path()

    finish_path()
    return polygons


def point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        cross = (x - previous_x) * (current_y - previous_y) - (y - previous_y) * (
            current_x - previous_x
        )
        if (
            abs(cross) <= 1e-5
            and min(previous_x, current_x) - 1e-5 <= x <= max(previous_x, current_x) + 1e-5
            and min(previous_y, current_y) - 1e-5 <= y <= max(previous_y, current_y) + 1e-5
        ):
            return True
        if (current_y > y) != (previous_y > y):
            crossing_x = previous_x + (y - previous_y) * (current_x - previous_x) / (
                current_y - previous_y
            )
            if x < crossing_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def polygon_area(polygon: list[tuple[float, float]]) -> float:
    return abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1])
    )) / 2


def extract_booths(page: pymupdf.Page, crop: pymupdf.Rect) -> list[dict]:
    words = page.get_text("words")
    booth_shapes = [
        (polygon, polygon_area(polygon))
        for drawing in page.get_drawings()
        if drawing.get("fill") is not None and drawing["rect"].intersects(crop)
        for polygon in drawing_polygons(drawing)
        if polygon_area(polygon) > 0
    ]
    code_words = [word for word in words if BOOTH_CODE.fullmatch(word[4])]

    def inside_crop(word: tuple) -> bool:
        center_x = (word[0] + word[2]) / 2
        center_y = (word[1] + word[3]) / 2
        return crop.x0 <= center_x <= crop.x1 and crop.y0 <= center_y <= crop.y1

    table_words = [word for word in code_words if not inside_crop(word)]
    map_words = [word for word in code_words if inside_crop(word)]
    map_words.extend(split_map_code_words(words, crop, page))
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
        matching_shapes = [
            (polygon, area)
            for polygon, area in booth_shapes
            if point_in_polygon(center_x, center_y, polygon)
        ]
        if not matching_shapes:
            raise ValueError(f"Could not find map geometry for booth {stand}.")
        polygon, _ = min(matching_shapes, key=lambda shape: shape[1])
        left = min(x for x, _ in polygon)
        top = min(y for _, y in polygon)
        right = max(x for x, _ in polygon)
        bottom = max(y for _, y in polygon)
        width = right - left
        height = bottom - top
        booth = booths.setdefault(
            stand,
            {"stand": stand, "hall": hall_for(stand), "exhibitors": [], "locations": []},
        )
        booth["locations"].append(
            {
                "x": round((center_x - crop.x0) / crop.width, 6),
                "y": round((center_y - crop.y0) / crop.height, 6),
                "geometry": {
                    "x": round((left - crop.x0) / crop.width, 6),
                    "y": round((top - crop.y0) / crop.height, 6),
                    "width": round(width / crop.width, 6),
                    "height": round(height / crop.height, 6),
                    "points": [
                        [round((x - left) / width, 6), round((y - top) / height, 6)]
                        for x, y in polygon
                    ],
                },
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

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=crop, alpha=False)
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
