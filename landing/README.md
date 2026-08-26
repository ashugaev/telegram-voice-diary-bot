# landing

Static marketing page for the bot. Plain HTML + CSS, zero JS, zero build step.
Server-rendered by definition, so crawlers get the full text.

## Files

| File | Purpose |
|---|---|
| `index.html` | Whole page: markup, meta, OG tags, JSON-LD |
| `styles.css` | All styles |
| `og.png` | 1200x630 social preview |
| `favicon.svg` | Tab icon |
| `robots.txt`, `sitemap.xml` | Crawler hints |
| `src/og-card.html` | Source of `og.png`, screenshot it at 1200x630 to regenerate |

## Local preview

```bash
python3 -m http.server 3080 --bind 127.0.0.1 --directory landing
```

Spur sidecar `landing` runs the same command on a reserved port.

## Before hosting

Replace `https://pizdabol.app/` with the real domain in `index.html` (canonical, OG,
JSON-LD), `robots.txt`, and `sitemap.xml`. Replace `t.me/pizdabol_ai_bot` with the real
bot handle.

Deploy target: any static host — GitHub Pages, Cloudflare Pages, Netlify, nginx root.
Upload the directory, nothing to build.
