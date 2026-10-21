# Reusable hall map

This static web app reads event details, halls, booth numbers and map positions
from `data/exhibitors.json`. Exhibitor names, profiles, categories, website
links and logos are read from `data/exhibitor-profiles.json`. It loads the
floor-plan image from the path in the booth data (normally
`assets/hall-map.png`) and sizes the map from the image itself.

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
the PDF again whenever booth positions change. Map labels split across two
lines, such as `D01-` followed by `23`, are joined automatically.

Fetch the matching exhibitor profiles separately so the directory can show
company information and logos:

```sh
python scripts/fetch_exhibitor_profiles.py \
  --api-url "https://api.venyou.no/v1/public/widgets/exhibitor-widget/553"
```

This writes `data/exhibitor-profiles.json`. Update the API URL for a new event;
the GitHub Actions workflow performs both processing steps automatically.

## Generate from GitHub Actions

The **Process hall map PDF** workflow runs on pushes to `main` that add or
change a PDF directly in `pdf/`. Keep exactly one `.pdf` file in that folder;
replace the previous file when preparing a new year. For example:

```sh
mkdir -p pdf
cp "/path/to/new-hall-plan.pdf" "pdf/Eliaden-27-Hall-Plan.pdf"
# For a new event, update EXHIBITOR_API_URL and the HALL_MAP_* values first.
git add -A
git status --short
git commit -m "Update hall map source PDF"
git push origin main
```

Review `git status --short` before committing to make sure all intended PDF,
workflow, code, and documentation changes are included.

After the push, open the repository's **Actions** tab and select
**Process hall map PDF** to follow the run. The workflow installs requirements,
fetches exhibitor profiles and logos from the configured public API, processes
the PDF, then commits changed `assets/hall-map.png`, `data/exhibitors.json`
and `data/exhibitor-profiles.json` back to `main` using the `turbolego` Git
identity. It does not create a second commit when generated files are unchanged.

To run it again without changing the PDF, go to **Actions → Process hall map
PDF → Run workflow**, choose the `main` branch, and start the run. The same
single-PDF requirement applies. If processing fails, check that the PDF is
directly inside `pdf/`, that there is only one PDF there, and that the map crop
can be detected; use the manual script command above for page or crop overrides.
For a new event, change `EXHIBITOR_API_URL` in
`.github/workflows/process-hall-map.yml` to the new widget endpoint and update
`HALL_MAP_EVENT_NAME`, `HALL_MAP_YEAR`, `HALL_MAP_DATES` and `HALL_MAP_VENUE`
before pushing the PDF. The workflow passes these values to the processor so
event dates and venue are retained in the generated booth data.

## Verify PDF and API booth numbers

Run the comparison locally from the repository root:

```sh
python scripts/verify_exhibitor_stands.py \
  --pdf "pdf/Eliaden-26-Hall-B-C-D_21.pdf" \
  --api-url "https://api.venyou.no/v1/public/widgets/exhibitor-widget/553"
```

The checker compares unique stand numbers in the PDF's exhibitor tables with
the API's `stands[].standnumber` values. It reports stands found only in either
source, API records without a valid stand, and repeated API assignments.
Repeated assignments are informational because several exhibitors can share a
stand; set differences and exhibitors without a stand make the check fail.

The separate **Verify PDF and API booth data** workflow runs when the PDF or
checker code changes on `main`. To run it on demand, open **Actions → Verify
PDF and API booth data → Run workflow**, select `main`, and start the run. Keep
exactly one PDF directly in `pdf/`. The action summary shows the comparison
results, and the workflow fails when the sources differ. For a new event,
update `EXHIBITOR_API_URL` in both
`.github/workflows/process-hall-map.yml` and
`.github/workflows/verify-exhibitor-stands.yml`.

## Edit the data by hand

You can edit `data/exhibitors.json` directly when only exhibitor names, booth
numbers or event details change. Keep the existing JSON structure:

- `event` contains `name`, `year`, `dates` and `venue`, which the page displays.
- `halls` contains the hall `id` and display `label` used by the filters.
- `map.image` is the artwork path. `map.crop`, `map.page` and `map.image_size`
  document how it was generated.
- Each item in `booths` has a `stand`, `hall`, an `exhibitors` array and a
  `locations` array.
- `data/exhibitor-profiles.json` is generated from the public exhibitor API
  and provides logos, descriptions, categories and website/social links.

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
