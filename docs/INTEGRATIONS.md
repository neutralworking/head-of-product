# INTEGRATIONS

Current status of MCPs, APIs, and external services HoP relies on. Update as state changes.

| Integration | Purpose | Auth / endpoint | Status | Notes |
|---|---|---|---|---|
| GitHub MCP | Read repos, PRs, issues, commits | `mcp-github.neutralworking.com` (self-hosted) | **misconfigured — fix planned** | Luke flagged the server wasn't configured correctly. Action: confirm host, auth (PAT scopes: repo, read:org, workflow), verify against all 17 NW repos. Until fixed, fall back to GitHub MCP via claude.ai (currently scoped to `head-of-product` only in this environment) or direct REST via `lib/github_client.py`. |
| GitHub REST API | Deterministic repo data (commits, issues, PRs, workflow runs, TODO search) | `https://api.github.com` + `GITHUB_TOKEN` | working | Used by `lib/github_client.py`. Code search has a per-token rate limit — TODO cache has an 8h TTL. |
| Linear MCP | Track tickets across `Chief Scout` and `Neutral Working` teams | claude.ai built-in | working | Not yet wired to HoP automation (session-1 don't list). Tags to use: `focus/{now,next,later}`, `someday`, `needs-triage`, `effort/quick`, `revenue/{active,path,none}`, plus existing `type/*`, `po/*`, `module/*`. |
| Todoist MCP | Daily actionables, digest delivery | claude.ai built-in | working | Daily digest target: `HoP morning brief — YYYY-MM-DD` at 06:30 Europe/Prague. Linear → Todoist bridge is an early priority. |
| Claude API | PM synthesis, judgment calls | `CLAUDE_CODE_OAUTH_TOKEN` env | working | Routed via `lib/model_router.py` for tasks like `pm_synthesis`. |
| Ollama (Mistral 7B) | Routine repo scans | `OLLAMA_HOST` env, local | requires local install | Default backend for `repo_scan`. Not available in remote/web sessions. |
| Notion MCP | TBD | claude.ai built-in | available, unused | Could host long-form opportunity notes if Markdown becomes unwieldy. |
| Google Calendar MCP | Schedule awareness | claude.ai built-in | available, unused | Useful for weekly review / discovery scan timing. |
| Gmail MCP | Inbox signals | claude.ai built-in | available, unused | Possible source for opportunity scanning (newsletters, prospect replies). |
| Figma MCP | Design context | claude.ai built-in | available, unused | Only relevant when working in `chief-scout` / `neutralworking` UI. |
| Supabase MCP | DB-backed projects | claude.ai built-in | available, unused | Relevant if Chief Scout / Soft Power move off SQLite. |
| Telegram | Time-sensitive pings: digest delivery, alerts | bot token + chat ID, TBD | not provisioned | Chosen over Slack for personal pushes. Need: new bot via `@BotFather`, chat ID, store as `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`. Daily digest also goes to Todoist as `HoP morning brief — YYYY-MM-DD`. |
| Discord webhooks | Archive channel: digests + alerts log | `DISCORD_WEBHOOK_DIGESTS`, `DISCORD_WEBHOOK_ALERTS` env | working | Stays as searchable archive; primary notifications move to Telegram. |
| Board host | `product.neutralworking.com` via Coolify on NW infra | Coolify on same host as `neutralworking.com` | not provisioned | Auth: Coolify reverse-proxy basic-auth. Deploy: git push → Coolify pulls. See `docs/BOARD.md`. |

## Known issues

- **GitHub MCP at `mcp-github.neutralworking.com` is not configured correctly.** Luke flagged this; fix planned. Need: confirm host is reachable, PAT scopes (repo, read:org, workflow), test against each NW repo. Until fixed, fall back to the REST client (`lib/github_client.py`) or the built-in GitHub MCP via claude.ai (currently repo-scoped to `head-of-product` only in this environment).
- **Repo MCP scope** is restricted to `neutralworking/head-of-product` in this remote execution environment. Other repos are read-only via GitHub MCP search/contents tools.
- **Ollama is not available** in remote/web sessions. Tasks routed to Ollama will fail until run on Luke's machine or the server.

## To wire (post session-1)

1. Linear → Todoist bridge (early priority)
2. HoP daily digest → Todoist at 06:30 Europe/Prague
3. HoP weekly review → Todoist Sunday 20:00
4. HoP monthly discovery scan → Todoist on the 1st (higher priority)
5. Board update pipeline: SQLite → `board/data.json` → push → host rebuild
