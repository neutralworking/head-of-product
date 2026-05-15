# BOARD architecture

The board is the one-glance surface for portfolio state. Three panels: active projects, revenue snapshot, top opportunities. Mobile-first.

This doc records the architecture decisions for session 1. Each section gives the decision, the reasoning, and the alternatives considered.

---

## 1. Hosting — **`product.neutralworking.com`, Coolify on NW infra**

**Decision:** dedicated subdomain `product.neutralworking.com`, deployed via Coolify alongside `neutralworking.com`.

Why:
- `neutralworking.com` is the public-facing portfolio / lead-gen page. The board contains revenue figures and kill candidates — not for that audience.
- A subdomain lets us put auth in front of the whole thing without complicating the public site.
- Coolify is already set up on Luke's infra for `neutralworking.com`. One host, one deploy story, no extra bills.
- Easy to swap or front with Cloudflare later if needed.

Alternative considered: Cloudflare Pages + Access. Rejected — adds an extra surface; Coolify is already paid for.

Alternative considered: `neutralworking.com/product` path. Rejected — couples the deploy/auth surface to the public site and makes it harder to lock down.

---

## 2. Tech — **static HTML/CSS/JS, no build step, data from JSON**

**Recommendation:** single `index.html`, vanilla JS, no framework. `board/data.json` is the source. CSS in one file. Mobile-first layout.

Why:
- The board is 3 panels rendering tabular data. A framework is overkill.
- No build step means automation can edit `data.json` and push — the deploy is trivial.
- Zero runtime dependencies means zero supply-chain rot.
- A hand-rolled CSS grid renders well on mobile without a framework.

Alternative considered: Next.js / Astro. Rejected — adds a build step and Node dependency for a glorified read-only dashboard.

---

## 3. Auth — **HTTP Basic via Coolify reverse proxy** (interim)

**Decision:** Coolify's built-in basic-auth (Traefik middleware) in front of the static site. Single user, password in Coolify's secret store.

Why:
- Single user. HTTP Basic is the smallest thing that works.
- Coolify exposes this as config — no extra service to run.
- Move to magic links / OAuth only when there's a second consumer (none planned).

Alternative considered:
- Fully public. Rejected — revenue figures, kill recommendations, and personal project state are not for public consumption.
- Full OAuth. Rejected — over-engineered for a one-user dashboard.

---

## 4. Data source — **`board/data.json` in this repo**

**Recommendation:** the board reads a JSON file checked into this repo. Future automation regenerates the file from SQLite (`output/hop.db`) and commits it. Manual editing is fine in the interim.

Why:
- Single source of truth, version-controlled. Every state change is a git diff — free audit trail.
- No runtime DB call from the browser — keeps the page fast and the deploy stateless.
- Easy to roll back if HoP writes a bad file: revert the commit.

Alternative considered:
- API endpoint hitting SQLite directly. Rejected for now — adds a server, auth complexity, and a deploy target. Worth revisiting if data update frequency exceeds ~every 15 min.
- GitHub Issues / Notion as the data source. Rejected — adds a network hop and ties us to a third-party schema.

Schema sketch (`board/data.json`):

```json
{
  "generated_at": "2026-05-15T07:00:00Z",
  "projects": [
    {
      "name": "Chief Scout",
      "repo": "chief-scout",
      "tier": "now",
      "last_touched": "2026-05-14",
      "next_step": "...",
      "blocker": null,
      "revenue_status": "path"
    }
  ],
  "revenue": [
    { "project": "Chief Scout", "monthly_gbp": 0, "trajectory": "flat", "cost_gbp": 12 }
  ],
  "opportunities": [
    { "date": "2026-05-15", "opportunity": "...", "fit": "high", "next_step": "..." }
  ]
}
```

---

## 5. Update mechanism — **HoP → `data.json` → git push → Coolify rebuilds**

**Decision:** the HoP pipeline writes `board/data.json`, commits to a branch, and **auto-merges to `main`** for data updates. Coolify pulls and redeploys on push to `main`. Project additions / kills / scope changes still open as PRs for review.

Why:
- Same git audit trail as everything else.
- Auto-merge for routine data refreshes — they shouldn't need eyeballs.
- PRs reserved for state changes Luke should see (new project, kill recommendation, tier shift).
- No webhook plumbing — push triggers the rebuild.

Cadence: once daily for now (matches the digest). Bump to hourly only if something is actually moving fast.

---

## Open decisions

1. Branding — deliberately ugly operational tool, or styled to match NW? Defer until Luke sees the MVP.

Everything else is locked.
