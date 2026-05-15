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

Target: `product.neutralworking.com` via Coolify on NW infra.

- Host: Coolify (same instance as `neutralworking.com`)
- Subdomain: `product.neutralworking.com`
- Auth: HTTP Basic via Coolify reverse-proxy middleware
- Update flow: push to `main` → Coolify pulls and redeploys

Not yet deployed — pending Luke creating the Coolify app + DNS record (see `docs/BOARD.md`).

## Updating data

For now: hand-edit `data.json` and commit.

Later: HoP automation will write `data.json` from `output/hop.db` and push.
