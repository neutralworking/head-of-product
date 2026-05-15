# INTEGRATIONS

Current status of MCPs, APIs, and external services HoP relies on. Update as state changes.

| Integration | Purpose | Auth / endpoint | Status | Notes |
|---|---|---|---|---|
| GitHub MCP (self-hosted) | — | `mcp-github.neutralworking.com` | **dropped** | Luke's call (session 1). Self-hosted MCP retired; not worth standing up for one user. Use REST client + claude.ai built-in MCP instead. |
| GitHub MCP (claude.ai built-in) | Repo browsing, PR/issue read+write from chat | claude.ai integration | working | Repo-scoped to `neutralworking/head-of-product` in this remote environment. For cross-repo reads HoP automation uses the REST client. |
| GitHub REST API | Deterministic repo data (commits, issues, PRs, workflow runs, TODO search) | `https://api.github.com` + `GITHUB_TOKEN` | working | Used by `lib/github_client.py`. Code search has a per-token rate limit — TODO cache has an 8h TTL. |
| Linear MCP | Track tickets across `Chief Scout` and `Neutral Working` teams | claude.ai built-in | working | Not yet wired to HoP automation (session-1 don't list). Tags to use: `focus/{now,next,later}`, `someday`, `needs-triage`, `effort/quick`, `revenue/{active,path,none}`, plus existing `type/*`, `po/*`, `module/*`. |
| Todoist REST API | Daily morning-brief task | `TODOIST_API_TOKEN` env | wired, untested | `lib/todoist_client.py` creates `HoP morning brief — YYYY-MM-DD` due today 06:30. Linear → Todoist bridge is an early priority. |
| Todoist MCP | Chat-driven actionables | claude.ai built-in | working | Used in claude.ai sessions for ad-hoc tasking outside the pipeline. |
| Claude API | PM synthesis, judgment calls | `CLAUDE_CODE_OAUTH_TOKEN` env | working | Routed via `lib/model_router.py` for tasks like `pm_synthesis`. |
| Ollama (Mistral 7B) | Routine repo scans | `OLLAMA_HOST` env, local | requires local install | Default backend for `repo_scan`. Not available in remote/web sessions. |
| Notion MCP | TBD | claude.ai built-in | available, unused | Could host long-form opportunity notes if Markdown becomes unwieldy. |
| Google Calendar MCP | Schedule awareness | claude.ai built-in | available, unused | Useful for weekly review / discovery scan timing. |
| Gmail MCP | Inbox signals | claude.ai built-in | available, unused | Possible source for opportunity scanning (newsletters, prospect replies). |
| Figma MCP | Design context | claude.ai built-in | available, unused | Only relevant when working in `chief-scout` / `neutralworking` UI. |
| Supabase MCP | DB-backed projects | claude.ai built-in | available, unused | Relevant if Chief Scout / Soft Power move off SQLite. |
| Telegram | Time-sensitive pings: digest delivery, alerts | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` env | wired, untested | `lib/telegram_notifier.py` sends HTML-formatted digest + alerts. Bot: `@nw_hop_bot`. Daily digest also creates a Todoist task. |
| Discord webhooks | Archive channel: digests + alerts log | `DISCORD_WEBHOOK_DIGESTS`, `DISCORD_WEBHOOK_ALERTS` env | working | Stays as searchable archive; primary notifications move to Telegram. |
| Board host | `product.neutralworking.com` via Coolify on NW infra | Coolify on same host as `neutralworking.com` | not provisioned | Auth: Coolify reverse-proxy basic-auth. Deploy: git push → Coolify pulls. See `docs/BOARD.md`. |

## Known issues

- **Repo MCP scope** is restricted to `neutralworking/head-of-product` in this remote execution environment. Cross-repo reads use the REST client.
- **Ollama is not available** in remote/web sessions. Tasks routed to Ollama will fail until run on Luke's machine or the server.

## To wire

1. ~~HoP daily digest → Todoist at 06:30 Europe/Prague~~ ✓ session 2 (untested on host)
2. ~~HoP daily digest → Telegram~~ ✓ session 2 (untested on host)
3. Linear → Todoist bridge (early priority)
4. HoP weekly review → Todoist Sunday 20:00
5. HoP monthly discovery scan → Todoist on the 1st (higher priority)
6. Board update pipeline: SQLite → `board/data.json` → push → host rebuild
