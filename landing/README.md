# landing

Static marketing page for the bot. Plain HTML + CSS, zero JS, zero build step.
Server-rendered by definition, so crawlers get the full text.

## Files

| File | Purpose |
|---|---|
| `index.html` | EN page: markup, meta, OG tags, JSON-LD, icon sprite |
| `ru/index.html` | RU page, same structure, hreflang-paired with EN |
| `styles.css` | All styles |
| `og.png` | 1200x630 social preview |
| `favicon.svg`, `avatar.svg` | Tab icon and the bot avatar in the hero chat |
| `robots.txt`, `sitemap.xml` | Crawler hints |
| `src/og-card.html` | Source of `og.png`, screenshot it at 1200x630 to regenerate |

## Local preview

```bash
python3 -m http.server 3080 --bind 127.0.0.1 --directory landing
```

Spur sidecar `landing` runs the same command on a reserved port.

## Rules

- Copy changes land in EN and RU together.
- Hero chat mimics Telegram Desktop's Night theme (windowBg #17212b, msgIn #182533, msgOut #2b5278, ticks #6bbfff) and mirrors what the bot really sends: reply quote, draft entry, inline keyboard, save rewriting the same message, roast, memory update.
- Chat reveal runs once on load and only under `prefers-reduced-motion: no-preference`; the full transcript is in the HTML for crawlers.
- No JS. Motion is CSS only and stops under `prefers-reduced-motion`.

## Before hosting

Replace `https://pizdabol.app/` with the real domain in `index.html` and
`ru/index.html` (canonical, hreflang, og:url, JSON-LD `url`), `robots.txt`, and
`sitemap.xml`. Replace `t.me/pizdabol_ai_bot` with the real bot handle in both pages.

Deploy target: any static host — GitHub Pages, Cloudflare Pages, Netlify, nginx root.
Upload the directory, nothing to build.
