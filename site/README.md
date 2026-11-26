# Athena website

A static site (plain HTML and CSS, no build step, no dependencies). Open `index.html`, or serve the folder:

```bash
cd site && python3 -m http.server 8422
```

`.github/workflows/pages.yml` publishes it to GitHub Pages (https://promethean-works.github.io/athena/) on every push to `main` that touches `site/`, the guide or the build script; it rebuilds the docs pages first. It also works on any static host. The screenshots in `assets/` are copies of `docs/user-guide/images/`; keep them in step. Documentation links point at the guide on GitHub.

## Documentation pages

`site/docs/*.html` is generated from `docs/user-guide/*.md` (a shadcn-style docs layout: sidebar, "on this page", previous and next). After editing the guide, run `node scripts/build-site.mjs` from the repo root; it also copies the guide's screenshots into `site/assets/`. `node scripts/build-site.mjs --check` fails when the pages are out of date. A new guide page must be added to `NAV` in the script.
