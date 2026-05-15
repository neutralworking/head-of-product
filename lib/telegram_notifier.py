"""Telegram bot notifier — primary push channel for HoP digest + alerts."""

import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("hop.telegram")

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
MAX_MESSAGE_LEN = 4096


def _creds() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
    return token, chat_id


def _status_emoji(status: str) -> str:
    return {
        "green": "🟢", "yellow": "🟡", "red": "🔴",
        "healthy": "🟢", "stale": "🟡", "at-risk": "🔴",
    }.get(status, "⚪")


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _build_digest_message(digest: dict, pr_url: str | None = None) -> str:
    portfolio = digest.get("portfolio_status", "unknown")
    ranking = digest.get("cross_project_ranking", []) or []
    decisions = digest.get("needs_decision", []) or []
    repo_statuses = digest.get("repo_statuses", {}) or {}

    at_risk = sum(
        1 for v in repo_statuses.values()
        if (v if isinstance(v, str) else v.get("status", "")) == "at-risk"
    )

    header = f"<b>{_status_emoji(portfolio)} Portfolio: {portfolio}</b>"
    if at_risk:
        header += f" — {at_risk} at-risk"

    lines = [header, ""]

    if ranking:
        lines.append("<b>Top priorities</b>")
        for item in ranking[:3]:
            rank = item.get("rank", "?")
            repo = _html_escape(str(item.get("repo", "?")))
            action = _html_escape(str(item.get("action", "")))
            lines.append(f"{rank}. [{repo}] {action}")
        lines.append("")

    if decisions:
        lines.append("<b>Needs your call</b>")
        for d in decisions[:3]:
            repo = _html_escape(str(d.get("repo", "?")))
            question = _html_escape(str(d.get("question", "")))
            lines.append(f"• {repo}: {question}")
        lines.append("")

    if pr_url:
        lines.append(f'<a href="{_html_escape(pr_url)}">Full digest →</a>')

    msg = "\n".join(lines).rstrip()
    if len(msg) > MAX_MESSAGE_LEN:
        msg = msg[: MAX_MESSAGE_LEN - 4] + "\n…"
    return msg


async def _post(method: str, payload: dict) -> dict:
    token, _ = _creds()
    url = f"{API_BASE}/bot{token}/{method}"
    last_exc: Exception | None = None
    async with httpx.AsyncClient() as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", RETRY_BACKOFF * (2 ** attempt))
                    logger.warning("Telegram rate limited, waiting %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                wait = RETRY_BACKOFF * (2 ** attempt)
                logger.warning(
                    "Telegram %s failed (attempt %d/%d), retrying in %.1fs: %s",
                    method, attempt + 1, MAX_RETRIES, wait, exc,
                )
                await asyncio.sleep(wait)
    raise RuntimeError(f"Telegram {method} failed after {MAX_RETRIES} retries: {last_exc}")


async def send_message(text: str, *, parse_mode: str = "HTML", disable_preview: bool = True) -> None:
    _, chat_id = _creds()
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    await _post("sendMessage", payload)


async def send_digest(digest: dict, pr_url: str | None = None) -> None:
    msg = _build_digest_message(digest, pr_url=pr_url)
    logger.info("Sending digest to Telegram")
    await send_message(msg)


async def send_alert(message: str) -> None:
    logger.info("Sending alert to Telegram: %s", message[:100])
    await send_message(_html_escape(message), disable_preview=True)
