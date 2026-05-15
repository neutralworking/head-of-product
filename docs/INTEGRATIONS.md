# INTEGRATIONS

Current status of MCPs, APIs, and external services HoP relies on. Update as state changes.

| Integration | Purpose | Auth / endpoint | Status | Notes |
|---|---|---|---|---|
| GitHub MCP | Read repos, PRs, issues, commits | `mcp-github.neutralworking.com` (self-hosted) | **flaky in claude.ai web** | Token refresh sometimes needed; tools time out in browser sessions. Direct REST via `lib/github_client.py` is the reliable fallback. |
| GitHub REST API | Deterministic repo data (commits, issues, PRs, workflow runs, TODO search) | `https://api.github.com` + `GITHUB_TOKEN` | working | Used by `lib/github_client.py`. Code search has a per-token rate limit — TODO cache has an 8h TTL. |
| Linear MCP | Track tickets across `Chief Scout` and `Neutral Working` teams | claude.ai built-in | working | Not yet wired to HoP automation (session-1 don't list). Tags to use: `focus/{now,next,later}`, `someday`, `needs-triage`, `effort/quick`, `revenue/{active,path,none}`, plus existing `type/*`, `po/*`, `module/*`. |
| Todoist MCP | Daily actionables, digest delivery | claude.ai built-in | working | Daily digest target: `HoP morning brief — YYYY-MM-DD` at 06:30 Europe/Prague. Linear → Todoist bridge is an early priority. |
| Claude API | PM synthesis, judgment calls | `CLAUDE_CODE_OAUTH_TOKEN` env | working | Routed via `lib/model_router.py` for tasks like `pm_synthesis`. |
| Ollama (Mistral 7B) | Routine repo scans | `OLLAMA_HOST` env, local | requires local install | Default backend for `repo_scan`. Not available in remote/web sessions. |
| Discord webhooks | Output channel: digests + alerts | `DISCORD_WEBHOOK_DIGESTS`, `DISCORD_WEBHOOK_ALERTS` env | working | Configured per `config/discord.yaml`. May be superseded by Todoist for the daily digest. |
| Notion MCP | TBD | claude.ai built-in | available, unused | Could host long-form opportunity notes if Markdown becomes unwieldy. |
| Google Calendar MCP | Schedule awareness | claude.ai built-in | available, unused | Useful for weekly review / discovery scan timing. |
| Gmail MCP | Inbox signals | claude.ai built-in | available, unused | Possible source for opportunity scanning (newsletters, prospect replies). |
| Figma MCP | Design context | claude.ai built-in | available, unused | Only relevant when working in `chief-scout` / `neutralworking` UI. |
| Supabase MCP | DB-backed projects | claude.ai built-in | available, unused | Relevant if Chief Scout / Soft Power move off SQLite. |
| Telegram / Slack notifications | Push for digest + alerts | TBD | not chosen | **ASK** — which one for personal pushes? Discord is fine for archive but not for time-sensitive pings. |
| Board host | Public surface for `hop.neutralworking.com` | TBD | not provisioned | Recommended: Cloudflare Pages + Cloudflare Access (see `docs/BOARD.md`). |

## Known issues

- **GitHub MCP flakiness in claude.ai web sessions.** Tools may refuse, time out, or need a token refresh. Fall back to the REST client (`lib/github_client.py`) or shell `gh` (when available locally). In the managed remote execution environment there is no `gh`; use the GitHub MCP tools (`mcp__github__*`).
- **Repo MCP scope** is restricted to `neutralworking/head-of-product` in this remote environment. Other repos are read-only via GitHub MCP search/contents tools.
- **Ollama is not available** in remote/web sessions. Tasks routed to Ollama will fail until run on Luke's machine or the server.

## To wire (post session-1)

1. Linear → Todoist bridge (early priority)
2. HoP daily digest → Todoist at 06:30 Europe/Prague
3. HoP weekly review → Todoist Sunday 20:00
4. HoP monthly discovery scan → Todoist on the 1st (higher priority)
5. Board update pipeline: SQLite → `board/data.json` → push → host rebuild
