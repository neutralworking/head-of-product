# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Head of Product (HoP) is a Python orchestrator that monitors multiple GitHub repos, produces per-repo product-owner analysis, synthesizes cross-project PM digests, and delivers updates via Discord webhooks. It uses a two-tier LLM strategy: **Ollama (Mistral 7B)** for routine repo scans, **Claude** for PM-level synthesis and judgment.

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Scan a single repo
python -m agents.repo_analyst roguelike

# Scan all repos
python -m agents.repo_analyst --all

# Dry run (collect GitHub data, skip LLM + save)
python -m agents.repo_analyst --all --dry-run

# Produce PM digest (reads latest scans from SQLite, calls Claude, posts to Discord)
python -m agents.pm_aggregator

# Dry run digest (no Discord post)
python -m agents.pm_aggregator --dry-run

# Run autofix candidates
python -m agents.autofix --all
```

No test suite exists yet. There is no linter configuration.

## Architecture

The pipeline flows in three stages:

1. **Data collection** (`lib/github_client.py`) — Deterministic GitHub REST API calls using httpx. Returns a `RepoData` dataclass. No LLM involved. Fetches commits (7d + 30d), open issues (excluding PRs), open PRs, workflow runs, and TODO/FIXME markers via code search.

2. **Repo analyst** (`agents/repo_analyst.py`) — Builds a prompt from `prompts/repo_analyst.md` using `{{placeholder}}` substitution, sends to Ollama via the model router, parses structured JSON output. Validates against expected schema (status must be `healthy`/`stale`/`at-risk`). Saves report JSON to `output/reports/{alias}/` and to SQLite.

3. **PM aggregator** (`agents/pm_aggregator.py`) — Gathers latest scans from SQLite, builds prompt from `prompts/pm_digest.md`, routes to Claude. Validates digest (portfolio_status must be `green`/`yellow`/`red`). Saves to `output/digests/` and SQLite, then posts Discord embed.

### Key shared modules

- **Model router** (`lib/model_router.py`) — Routes tasks to Ollama or Claude based on `config/models.yaml`. The `route(task, prompt)` function is the single entry point. Tasks like `repo_scan` go to Ollama; `pm_synthesis` goes to Claude.
- **Memory** (`lib/memory.py`) — SQLite store at `output/hop.db` with tables: `scans`, `digests`, `todo_cache`. Thread-local connections with WAL mode. TODO cache has 8-hour TTL to respect GitHub search rate limits.
- **Discord notifier** (`lib/discord_notifier.py`) — Sends embeds to digests channel, plain text to alerts channel. Webhook URLs come from env vars referenced in `config/discord.yaml`.

### Autofix

`agents/autofix.py` checks scan results for autofix candidates, filters against `config/autofix-policy.yaml` (allowed vs blocked categories). The actual git clone/branch/fix/PR flow is **stubbed** (see the TODO in that file) — it currently only logs proposed fixes.

## Configuration

- `config/repos.yaml` — Repo definitions with `github`, `default_branch`, `project_type`, `priority_weight`, and per-repo scan/autofix toggles.
- `config/models.yaml` — Maps task names to backends (`ollama` or `claude`). Default backend is Ollama.
- `config/autofix-policy.yaml` — Allowed/blocked autofix categories, branch prefix.
- `config/discord.yaml` — Maps channel keys to env var names for webhook URLs; routing rules for which events go to which channel.

## Environment Variables

Defined in `.env` (see `.env.example`): `GITHUB_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `DISCORD_WEBHOOK_DIGESTS`, `DISCORD_WEBHOOK_ALERTS`, `OLLAMA_HOST`.

## Prompt Templates

Templates in `prompts/` use `{{placeholder}}` syntax — replaced via simple string substitution in the agent modules (not Jinja). When editing prompts, keep placeholders exactly as-is. Both prompts require the LLM to output **valid JSON only** with no markdown wrapping.
