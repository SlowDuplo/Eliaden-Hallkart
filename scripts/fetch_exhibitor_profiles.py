#!/usr/bin/env python3
"""Download and normalize exhibitor profiles for the static hall-map site."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://api.venyou.no/v1/public/widgets/exhibitor-widget/553"


def http_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return candidate


def description_for(stand: dict) -> str:
    english = stand.get("en")
    if isinstance(english, dict) and english.get("description"):
        return str(english["description"]).strip()
    return str(stand.get("description") or "").strip()


def normalize_exhibitor(record: dict) -> dict:
    name = str(record.get("company_name") or "").strip()
    if not name:
        raise ValueError(f"Exhibitor record {record.get('id', '(unknown)')} has no company name.")

    stands = []
    for stand in record.get("stands") or []:
        number = str(stand.get("standnumber") or "").strip()
        if not number:
            continue
        categories = []
        for category in stand.get("product_categories") or []:
            label = category.get("name_en") or category.get("name")
            if label and label not in categories:
                categories.append(str(label))
        stands.append(
            {
                "name": str(stand.get("standname") or name).strip(),
                "number": number,
                "description": description_for(stand),
                "categories": categories,
                "logo": http_url(stand.get("logo_screen_url")),
            }
        )

    logo = http_url(record.get("company_logo_url"))
    if not logo:
        logo = next((stand["logo"] for stand in stands if stand["logo"]), "")

    social_links = []
    for link in record.get("social_links") or []:
        url = http_url(link.get("url"))
        if url:
            social_links.append(
                {
                    "platform": str(link.get("platform") or "Social").strip().title(),
                    "url": url,
                }
            )

    return {
        "id": str(record.get("id") or name),
        "name": name,
        "website": http_url(record.get("company_url")),
        "logo": logo,
        "country_code": str(record.get("company_countrycode") or "").strip(),
        "social_links": social_links,
        "stands": stands,
    }


def merge_exhibitors(records: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for record in records:
        exhibitor = normalize_exhibitor(record)
        key = exhibitor["name"].casefold()
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = exhibitor
            continue

        existing_stands = {stand["number"] for stand in existing["stands"]}
        for stand in exhibitor["stands"]:
            if stand["number"] not in existing_stands:
                existing["stands"].append(stand)
                existing_stands.add(stand["number"])
        existing["stands"].sort(key=lambda stand: stand["number"])
        existing["logo"] = existing["logo"] or exhibitor["logo"]
        existing["website"] = existing["website"] or exhibitor["website"]
        existing["country_code"] = existing["country_code"] or exhibitor["country_code"]
        known_links = {link["url"] for link in existing["social_links"]}
        existing["social_links"].extend(
            link for link in exhibitor["social_links"] if link["url"] not in known_links
        )

    return sorted(grouped.values(), key=lambda exhibitor: exhibitor["name"].casefold())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download exhibitor details and logos from a public exhibitor API."
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Public exhibitor API endpoint.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/exhibitor-profiles.json"),
        help="Path for the normalized exhibitor data.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    request = Request(args.api_url, headers={"User-Agent": "EliadenHallMap/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not download exhibitor data from {args.api_url}: {error}") from error

    records = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError("The exhibitor API response did not contain a non-empty result list.")

    public_records = []
    hidden_stands = set()
    for record in records:
        if record.get("show_exhibitor_name") is False:
            hidden_stands.update(
                str(stand.get("standnumber") or "").strip()
                for stand in record.get("stands") or []
                if stand.get("standnumber")
            )
            continue
        public_records.append(record)

    if not public_records:
        raise ValueError("The exhibitor API has no publicly listed company profiles.")

    exhibitors = merge_exhibitors(public_records)
    data = {
        "source_url": args.api_url,
        "event": str(records[0].get("event_name") or "").strip(),
        "hidden_stands": sorted(hidden_stands),
        "exhibitors": exhibitors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logos = sum(bool(exhibitor["logo"]) for exhibitor in exhibitors)
    descriptions = sum(
        any(stand["description"] for stand in exhibitor["stands"])
        for exhibitor in exhibitors
    )
    print(
        f"Wrote {args.output} ({len(exhibitors)} exhibitors; "
        f"{logos} with logos; {descriptions} with descriptions)"
    )


if __name__ == "__main__":
    main()
