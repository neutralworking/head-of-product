"""Discord webhook notifier — sends embeds to digests and alerts channels."""

import asyncio
import logging
import os
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("hop.discord")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "discord.yaml"
DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def _get_webhook_url(channel_key: str) -> str:
    config = _load_config()
    channel = config.get("channels", {}).get(channel_key, {})
    env_var = channel.get("webhook_url_env", "")
    url = os.environ.get(env_var, "")
    if not url:
        raise RuntimeError(f"Discord webhook URL not set: env var '{env_var}' is empty")
    return url


def _status_emoji(status: str) -> str:
    return {"green": "🟢", "yellow": "🟡", "red": "🔴", "healthy": "🟢", "stale": "🟡", "at-risk": "🔴"}.get(status, "⚪")


FIELD_MAX = 1024


def _truncate(text: str, limit: int = FIELD_MAX) -> str:
    """Truncate text to fit Discord's field value limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 4] + "\n…"


def _build_digest_embed(digest: dict) -> dict:
    """Build a Discord embed from a PM digest."""
    portfolio = digest.get("portfolio_status", "unknown")
    repo_statuses = digest.get("repo_statuses", {})
    ranking = digest.get("cross_project_ranking", [])
    decisions = digest.get("needs_decision", [])

    # Repo status lines
    status_lines = []
    for repo, status in repo_statuses.items():
        s = status if isinstance(status, str) else status.get("status", "unknown")
        status_lines.append(f"{_status_emoji(s)} **{repo}**: {s}")
    status_field = "\n".join(status_lines) if status_lines else "No repos scanned"

    # Top priorities
    priority_lines = []
    for item in ranking[:3]:
        rank = item.get("rank", "?")
        repo = item.get("repo", "?")
        action = item.get("action", "")
        priority_lines.append(f"**{rank}.** [{repo}] {action}")
    priority_field = "\n".join(priority_lines) if priority_lines else "None"

    # Next up
    next_up_field = "\n".join(
        f"**{i.get('rank', '?')}.** [{i.get('repo', '?')}] {i.get('action', '')}"
        for i in ranking[3:6]
    ) or "—"

    # Needs decision
    decision_lines = []
    for d in decisions[:3]:
        repo = d.get("repo", "?")
        question = d.get("question", "")
        decision_lines.append(f"• **{repo}**: {question}")
    decision_field = "\n".join(decision_lines) if decision_lines else "None — all clear"

    embed = {
        "title": "Head of Product — Daily Digest",
        "color": {"green": 0x2ECC71, "yellow": 0xF1C40F, "red": 0xE74C3C}.get(portfolio, 0x95A5A6),
        "fields": [
            {"name": f"{_status_emoji(portfolio)} Portfolio Status", "value": _truncate(status_field), "inline": False},
            {"name": "🎯 Top Priority", "value": _truncate(priority_field), "inline": False},
            {"name": "📋 Next Up", "value": _truncate(next_up_field), "inline": False},
            {"name": "🤔 Needs Your Call", "value": _truncate(decision_field), "inline": False},
        ],
        "footer": {"text": f"Full report: output/digests/ | {digest.get('timestamp', '')}"},
    }
    return embed


async def _send_webhook(url: str, payload: dict) -> None:
    """POST to Discord webhook with retry."""
    last_exc: Exception | None = None
    async with httpx.AsyncClient() as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 429:
                    retry_after = resp.json().get("retry_after", RETRY_BACKOFF * (2 ** attempt))
                    logger.warning("Discord rate limited, waiting %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                wait = RETRY_BACKOFF * (2 ** attempt)
                logger.warning("Discord webhook failed (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, MAX_RETRIES, wait, exc)
                await asyncio.sleep(wait)
    raise RuntimeError(f"Discord webhook failed after {MAX_RETRIES} retries: {last_exc}")


async def send_digest(digest: dict) -> None:
    """Format and send the PM digest embed to the digests channel."""
    url = _get_webhook_url("digests")
    embed = _build_digest_embed(digest)
    payload = {"embeds": [embed]}
    logger.info("Sending digest to Discord")
    await _send_webhook(url, payload)


async def send_alert(message: str) -> None:
    """Send a plain-text alert to the alerts channel."""
    url = _get_webhook_url("alerts")
    payload = {"content": message}
    logger.info("Sending alert to Discord: %s", message[:100])
    await _send_webhook(url, payload)
