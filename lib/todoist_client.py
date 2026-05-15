"""Todoist REST API v2 client — minimal, used by HoP for the morning digest task."""

import asyncio
import logging
import os
from datetime import date

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("hop.todoist")

API_BASE = "https://api.todoist.com/rest/v2"
DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def _token() -> str:
    token = os.environ.get("TODOIST_API_TOKEN", "")
    if not token:
        raise RuntimeError("TODOIST_API_TOKEN not set")
    return token


async def _post(path: str, payload: dict) -> dict:
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
    last_exc: Exception | None = None
    async with httpx.AsyncClient() as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 429:
                    wait = RETRY_BACKOFF * (2 ** attempt)
                    logger.warning("Todoist rate limited, waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                wait = RETRY_BACKOFF * (2 ** attempt)
                logger.warning(
                    "Todoist POST %s failed (attempt %d/%d), retrying in %.1fs: %s",
                    path, attempt + 1, MAX_RETRIES, wait, exc,
                )
                await asyncio.sleep(wait)
    raise RuntimeError(f"Todoist POST {path} failed after {MAX_RETRIES} retries: {last_exc}")


async def create_task(
    content: str,
    *,
    description: str = "",
    due_string: str | None = None,
    priority: int = 3,
) -> dict:
    """Create a Todoist task. priority: 1=p4 (lowest) … 4=p1 (highest)."""
    payload: dict = {"content": content, "description": description, "priority": priority}
    if due_string:
        payload["due_string"] = due_string
    return await _post("/tasks", payload)


async def send_digest_task(digest: dict, pr_url: str | None = None) -> dict:
    """Create the daily HoP morning brief task in Todoist."""
    today = date.today().isoformat()
    title = f"HoP morning brief — {today}"
    description = _format_description(digest, pr_url=pr_url)
    logger.info("Creating Todoist task: %s", title)
    return await create_task(title, description=description, due_string="today at 06:30", priority=3)


def _format_description(digest: dict, pr_url: str | None = None) -> str:
    portfolio = digest.get("portfolio_status", "unknown")
    ranking = digest.get("cross_project_ranking", []) or []
    decisions = digest.get("needs_decision", []) or []

    lines = [f"Portfolio: **{portfolio}**", ""]

    if ranking:
        lines.append("**Top priorities**")
        for item in ranking[:3]:
            rank = item.get("rank", "?")
            repo = item.get("repo", "?")
            action = item.get("action", "")
            lines.append(f"{rank}. [{repo}] {action}")
        lines.append("")

    if decisions:
        lines.append("**Needs your call**")
        for d in decisions[:3]:
            repo = d.get("repo", "?")
            question = d.get("question", "")
            lines.append(f"- {repo}: {question}")
        lines.append("")

    if pr_url:
        lines.append(f"[Full digest]({pr_url})")

    return "\n".join(lines).rstrip()
