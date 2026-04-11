# Head of Product

A Python orchestrator that monitors GitHub repos, produces product-owner-style analysis per repo, synthesizes cross-project PM digests, and delivers updates via Discord webhooks.

Uses **Ollama (Mistral 7B)** for routine repo scans and **Claude** for PM-level synthesis and judgment calls.

## Architecture

```
GitHub REST API  →  Repo Analyst (Ollama)  →  PM Aggregator (Claude)  →  Discord
                         ↓                          ↓
                    per-repo JSON              cross-project digest
                         ↓                          ↓
                    SQLite memory              Discord embeds
```

Three layers:

1. **Data collection** (`lib/github_client.py`) — deterministic GitHub REST API calls, no LLM
2. **Repo analyst** (`agents/repo_analyst.py`) — feeds raw data + prompt to Ollama, outputs structured JSON per repo
3. **PM aggregator** (`agents/pm_aggregator.py`) — feeds all repo JSONs to Claude, outputs a ranked cross-project digest

Plus: autofix executor, model router, Discord notifier, SQLite memory store.

## Setup

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/) with Mistral 7B pulled: `ollama pull mistral:7b`
- GitHub personal access token
- Claude API key
- Discord webhook URLs (digests + alerts channels)

### Install

```bash
cd /opt/head-of-product
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

1. Copy and fill environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your tokens
   ```

2. Edit `config/repos.yaml` to add your repos.

3. Review `config/models.yaml` for model settings.

4. Review `config/autofix-policy.yaml` for autofix rules.

5. Set up Discord webhooks and edit `config/discord.yaml` if needed.

## Usage

### Scan a single repo

```bash
python -m agents.repo_analyst roguelike
```

### Scan all repos

```bash
python -m agents.repo_analyst --all
```

### Dry run (collect data, no LLM)

```bash
python -m agents.repo_analyst --all --dry-run
```

### Produce PM digest

```bash
python -m agents.pm_aggregator
```

### Dry run digest (no Discord)

```bash
python -m agents.pm_aggregator --dry-run
```

### Run autofix

```bash
python -m agents.autofix --all
```

## Systemd (Production)

Copy unit files and enable timers:

```bash
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hop-scan-all.timer hop-digest.timer
```

**Schedule:**
- Repo scans: every 4 hours (02:00, 06:00, 10:00, 14:00, 18:00, 22:00)
- PM digest: twice daily (09:00, 17:00)

Check status:

```bash
systemctl list-timers hop-*
journalctl -u hop-scan-all -f
journalctl -u hop-digest -f
```

## File Structure

```
config/         YAML configuration (repos, models, autofix policy, discord)
agents/         Agent modules (repo analyst, PM aggregator, autofix)
lib/            Shared libraries (GitHub client, model router, Discord, SQLite memory)
prompts/        Prompt templates with {{placeholder}} syntax
output/         Generated reports, digests, and SQLite database
systemd/        Systemd service and timer units
```

## Adding a Repo

Add a block to `config/repos.yaml`:

```yaml
  my-new-repo:
    github: "owner/repo-name"
    default_branch: main
    project_type: "web-app"
    priority_weight: 2
    scan:
      commits: true
      issues: true
      prs: true
      tests: true
      todos: true
      deploy_health: true
    autofix: true
```

The next scan cycle will pick it up automatically.
