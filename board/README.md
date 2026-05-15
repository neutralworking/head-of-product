# board/

Static HoP board. See `docs/BOARD.md` for the architecture decision record.

Files:
- `index.html` — three panels (projects, revenue, opportunities)
- `styles.css` — mobile-first, dark
- `board.js` — fetches `data.json`, renders panels
- `data.json` — single source of truth for what the board shows

## Local preview

```bash
cd board
python3 -m http.server 8000
# open http://localhost:8000
```

## Deploy

Not yet deployed. See `docs/BOARD.md` open decisions:
- Host (Cloudflare Pages recommended)
- Subdomain (`hop.neutralworking.com` recommended)
- Auth (Cloudflare Access / HTTP Basic recommended)

## Updating data

For now: hand-edit `data.json` and commit.

Later: HoP automation will write `data.json` from `output/hop.db` and push.
