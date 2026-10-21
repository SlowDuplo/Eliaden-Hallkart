#!/usr/bin/env python3
"""Compare exhibitor-table booth numbers in a PDF with the public API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pymupdf

from process_hall_map import detect_map_crop, extract_booths, parse_crop


DEFAULT_API_URL = "https://api.venyou.no/v1/public/widgets/exhibitor-widget/553"


def pdf_table_stands(pdf_path: Path, page_number: int, map_crop: tuple | None) -> set[str]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Input PDF does not exist: {pdf_path}")

    with pymupdf.open(pdf_path) as document:
        if page_number < 1 or page_number > len(document):
            raise ValueError(f"Page must be between 1 and {len(document)}.")
        page = document[page_number - 1]
        crop = pymupdf.Rect(map_crop) if map_crop else detect_map_crop(page)
        if not page.rect.contains(crop):
            raise ValueError(f"Map crop {tuple(crop)} extends outside the selected PDF page.")
        booths = extract_booths(page, crop)

    return {
        booth["stand"].strip().upper()
        for booth in booths
        if booth["exhibitors"]
    }


def api_stand_counts(api_url: str) -> tuple[Counter[str], int]:
    request = Request(api_url, headers={"User-Agent": "EliadenHallMapStandCheck/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not download exhibitor data from {api_url}: {error}") from error

    records = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError("The exhibitor API response did not contain a non-empty result list.")

    stands: Counter[str] = Counter()
    missing_stand_count = 0
    for record in records:
        assignments = record.get("stands")
        valid_assignments = 0
        if isinstance(assignments, list):
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    continue
                standnumber = assignment.get("standnumber")
                if isinstance(standnumber, str) and standnumber.strip():
                    stands[standnumber.strip().upper()] += 1
                    valid_assignments += 1
        if not valid_assignments:
            missing_stand_count += 1

    return stands, missing_stand_count


def format_report(
    pdf_stands: set[str], api_stands: Counter[str], missing_stand_count: int
) -> tuple[str, bool]:
    pdf_only = sorted(pdf_stands - api_stands.keys())
    api_only = sorted(api_stands.keys() - pdf_stands)
    duplicates = sorted(
        (stand, count) for stand, count in api_stands.items() if count > 1
    )
    matches = len(pdf_stands & api_stands.keys())
    passed = not pdf_only and not api_only and not missing_stand_count
    status = "PASS" if passed else "FAIL"

    lines = [
        f"## PDF/API stand-number comparison: {status}",
        "",
        "| Source | Unique stand numbers |",
        "|---|---:|",
        f"| PDF exhibitor table | {len(pdf_stands)} |",
        f"| Eliaden API | {len(api_stands)} |",
        "",
        f"Matching stand numbers: **{matches}**",
        f"API stand assignments including repeats: **{sum(api_stands.values())}**",
        "",
        "### In the PDF table, missing from the API",
        "",
        ", ".join(pdf_only) if pdf_only else "None",
        "",
        "### In the API, missing from the PDF table",
        "",
        ", ".join(api_only) if api_only else "None",
        "",
        f"API exhibitors with no valid stand assignment: **{missing_stand_count}**",
        "",
        "### Stand numbers assigned to multiple API exhibitors",
        "",
        (
            ", ".join(f"{stand} ({count} records)" for stand, count in duplicates)
            if duplicates
            else "None"
        ),
        "",
        "Repeated API assignments are reported for review but do not fail the set comparison.",
    ]
    return "\n".join(lines), passed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare booth numbers in the PDF exhibitor table with the exhibitor API."
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Input hall-map PDF.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Public exhibitor API endpoint.")
    parser.add_argument("--page", type=int, default=1, help="One-based PDF page to inspect.")
    parser.add_argument(
        "--map-crop",
        type=parse_crop,
        help="Optional x0,y0,x1,y1 map crop in PDF points; auto-detected by default.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_stands = pdf_table_stands(args.pdf.expanduser().resolve(), args.page, args.map_crop)
    api_stands, missing_stand_count = api_stand_counts(args.api_url)
    report, passed = format_report(pdf_stands, api_stands, missing_stand_count)
    print(report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(report + "\n")

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
