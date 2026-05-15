# BOARD architecture

The board is the one-glance surface for portfolio state. Three panels: active projects, revenue snapshot, top opportunities. Mobile-first.

This doc records the architecture decisions for session 1. Each section gives a recommendation, the reasoning, and the alternatives considered. Items marked **ASK** need Luke's sign-off before going to production.

---

## 1. Hosting — **`hop.neutralworking.com` subdomain**

**Recommendation:** dedicated subdomain.

Why:
- `neutralworking.com` is (or will be) the public-facing portfolio / lead-gen page. The board contains revenue figures and kill candidates — not for that audience.
- A subdomain lets us put auth in front of the whole thing at the edge without complicating the public site.
- Easier to swap hosts later (Cloudflare Pages, Netlify, Vercel) without breaking the public site's deploy.

Alternative considered: `neutralworking.com/hop` path. Rejected — couples the deploy/auth surface to the public site and makes it harder to lock down.

**ASK:** confirm Luke is happy with `hop.neutralworking.com` and that DNS is his to change.

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

## 3. Auth — **HTTP Basic at the edge** (interim) → signed link (later)

**Recommendation:** start with HTTP Basic auth via Cloudflare Access or a Worker (single user, single password in an env var). Move to signed magic links once there's a second consumer.

Why:
- Single user. HTTP Basic is the smallest thing that works.
- Edge auth keeps the static deploy dumb.
- Magic links are nicer UX but unnecessary for one person.

Alternative considered:
- Fully public. Rejected — revenue figures, kill recommendations, and personal project state are not for public consumption.
- Full OAuth. Rejected — over-engineered for a one-user dashboard.

**ASK:** Cloudflare vs. another host? If not Cloudflare, the auth mechanism may need to change.

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

## 5. Update mechanism — **HoP → `data.json` → git push → host rebuilds**

**Recommendation:** the HoP Python pipeline writes `board/data.json`, commits it on a generated branch, and either auto-merges to `main` (cheap) or opens a PR (auditable). The host (Cloudflare Pages / Netlify) rebuilds on push to `main`.

Why:
- Same git audit trail as everything else.
- Failure modes are visible (a bad PR is a bad PR, not a silently broken dashboard).
- No webhook plumbing — push triggers the rebuild.

Cadence: tied to scan cadence (currently every 4h per systemd timer; will be slower for the board — once daily is probably enough until something is moving fast).

**ASK:** auto-merge or PR-per-update? Auto-merge is simpler; PRs give Luke a daily diff to glance at. Default recommendation: auto-merge for the board update, separate PRs for project additions/kills.

---

## Open decisions (none blocking the MVP)

1. Host choice — Cloudflare Pages vs. Netlify vs. Vercel. Recommendation: **Cloudflare Pages** (Luke already uses Cloudflare for DNS, Access for auth is one click).
2. Auto-merge vs. PR for `data.json` updates.
3. Branding — the board can be deliberately ugly (operational tool) or styled to match NW.

Defer until after Luke sees the MVP.
