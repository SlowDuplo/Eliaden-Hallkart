# Reusable hall map

This static web app reads its event details, halls, exhibitors, booth numbers
and map positions from `data/exhibitors.json`. It loads the floor-plan image
from the path in that file (normally `assets/hall-map.png`) and sizes the map
from the image itself. Updating an event does not require editing the app code.

## Process a new PDF

The PDF processor reads the exhibitor table and booth labels, then creates both
`assets/hall-map.png` and `data/exhibitors.json`.

Install its dependency once:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Run it from the repository root, using the new PDF as input:

```sh
python scripts/process_hall_map.py \
  --pdf "path/to/new-hall-plan.pdf" \
  --output-dir . \
  --event-name "Eliaden" \
  --year 2027 \
  --dates "DD–DD Month YYYY" \
  --venue "Venue name"
```

The event name and year are inferred from the PDF filename when omitted. Dates
and venue are optional. The script auto-detects large hall shapes in the PDF;
check the generated image before publishing. If the crop is not right, pass the
map bounds explicitly as `x0,y0,x1,y1` in PDF points (not image pixels), and
select the page if needed:

```sh
python scripts/process_hall_map.py \
  --pdf "path/to/new-hall-plan.pdf" \
  --page 1 \
  --map-crop 250,62,1090,445
```

The crop must include every hall and booth label to be shown. The script writes
map positions as normalized `x`/`y` values for the generated image, so process
the PDF again whenever booth positions change.

## Edit the data by hand

You can edit `data/exhibitors.json` directly when only exhibitor names, booth
numbers or event details change. Keep the existing JSON structure:

- `event` contains `name`, `year`, `dates` and `venue`, which the page displays.
- `halls` contains the hall `id` and display `label` used by the filters.
- `map.image` is the artwork path. `map.crop`, `map.page` and `map.image_size`
  document how it was generated.
- Each item in `booths` has a `stand`, `hall`, an `exhibitors` array and a
  `locations` array.

For example:

```json
{
  "stand": "B01-01",
  "hall": "B",
  "exhibitors": ["Example Exhibitor"],
  "locations": [{ "x": 0.25, "y": 0.96 }]
}
```

`locations` use proportions from the top-left corner of the image (`0` to `1`),
not PDF coordinates or pixels. A booth can have multiple locations. Use an
empty array when its position is not known; the booth remains searchable but
the map marker is not shown. Add a hall to `halls` when adding booths in a hall
that is not already listed. The app discovers hall filters and event branding
from the JSON.

## Replace the map artwork

Replace `assets/hall-map.png` with the new image, keeping the same filename and
path in `map.image`. The app reads the image dimensions automatically, so no
CSS or JavaScript changes are needed for a different image size or aspect
ratio.

If booths have moved, update their `locations` in `data/exhibitors.json` too;
otherwise the existing markers will stay at their old positions. Prefer
processing the new PDF to regenerate the image and positions together. If you
replace the image manually, update the normalized coordinates to match the new
image and review the result locally.

## Preview and publish

Run the site from the repository root:

```sh
python3 -m http.server 8000
```

Open <http://localhost:8000>, check the map, filters, search results and a few
booth locations, then commit the generated image and JSON together. GitHub
Pages uses the repository root: in **Settings → Pages**, choose **Deploy from a
branch**, select `main` and `/(root)`, then save.
