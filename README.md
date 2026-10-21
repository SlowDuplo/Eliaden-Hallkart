# Eliaden 2026 hall map

A static, searchable hall map for Eliaden 2026. The exhibitor directory is
compiled from `Eliaden-26-Hall-B-C-D_21.pdf`; the floor-plan image is cropped
from the same PDF. The PDF lists 254 distinct booth numbers. Some listed booths
do not have an individually identifiable label on the drawing, so they remain
searchable in the directory without a guessed map position.

## Run locally

From the repository root, run:

```sh
python3 -m http.server 8000
```

Then open <http://localhost:8000>.

## Publish with GitHub Pages

The site is static and all entry-point files are in the repository root. In
GitHub, open **Settings → Pages**, choose **Deploy from a branch**, select
`main` and `/(root)`, then save. GitHub Pages will publish the site at the
repository's Pages URL.
