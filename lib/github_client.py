"""Deterministic GitHub REST API client — no LLM. Returns raw RepoData per repo."""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

from lib.memory import cache_todos, get_cached_todos

load_dotenv()

logger = logging.getLogger("hop.github")

GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


@dataclass
class RepoData:
    alias: str
    commits: list[dict] = field(default_factory=list)
    commits_30d: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    prs: list[dict] = field(default_factory=list)
    workflow_runs: list[dict] = field(default_factory=list)
    todos: list[dict] = field(default_factory=list)
    collected_at: str = ""


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> list | dict:
    """GET with retry + backoff. Handles 403 rate limits via Retry-After header."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                # Rate limit — retry after the header-specified delay
                if status in (403, 429):
                    retry_after = exc.response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else RETRY_BACKOFF * (2 ** attempt)
                    logger.warning("GitHub rate limit (%d) on %s, waiting %.1fs (attempt %d/%d)", status, url, wait, attempt + 1, MAX_RETRIES)
                    await asyncio.sleep(wait)
                    continue
                # Other 4xx — not retryable
                if status < 500:
                    logger.warning("GitHub API %s returned %s: %s", url, status, exc.response.text[:200])
                    raise
            wait = RETRY_BACKOFF * (2 ** attempt)
            logger.warning("GitHub API request failed (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, MAX_RETRIES, wait, exc)
            await asyncio.sleep(wait)
    raise RuntimeError(f"GitHub API request failed after {MAX_RETRIES} retries: {last_exc}")


async def _fetch_commits(client: httpx.AsyncClient, owner_repo: str, since_days: int = 7) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    url = f"{GITHUB_API}/repos/{owner_repo}/commits"
    return await _get(client, url, params={"since": since, "per_page": 100})


async def _fetch_issues(client: httpx.AsyncClient, owner_repo: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner_repo}/issues"
    all_issues = await _get(client, url, params={"state": "open", "per_page": 100})
    # Exclude pull requests (GitHub includes PRs in the issues endpoint)
    return [i for i in all_issues if "pull_request" not in i]


async def _fetch_prs(client: httpx.AsyncClient, owner_repo: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner_repo}/pulls"
    return await _get(client, url, params={"state": "open", "per_page": 100})


async def _fetch_workflow_runs(client: httpx.AsyncClient, owner_repo: str, branch: str = "main") -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner_repo}/actions/runs"
    data = await _get(client, url, params={"branch": branch, "per_page": 5})
    return data.get("workflow_runs", []) if isinstance(data, dict) else []


async def _fetch_todos(client: httpx.AsyncClient, owner_repo: str, alias: str) -> list[dict]:
    """Fetch TODO/FIXME markers. Uses cache to respect the 30 req/min search rate limit."""
    cached = get_cached_todos(alias)
    if cached is not None:
        logger.info("Using cached TODOs for %s", alias)
        return cached.get("items", [])

    url = f"{GITHUB_API}/search/code"
    try:
        data = await _get(client, url, params={"q": f"TODO OR FIXME repo:{owner_repo}"})
        items = data.get("items", []) if isinstance(data, dict) else []
        cache_todos(alias, {"items": items})
        return items
    except Exception as exc:
        logger.warning("TODO search failed for %s: %s — returning empty", alias, exc)
        return []


async def collect_repo_data(repo_config: dict, alias: str) -> RepoData:
    """Collect all data for a single repo based on its scan config."""
    owner_repo = repo_config["github"]
    scan = repo_config.get("scan", {})
    default_branch = repo_config.get("default_branch", "main")

    async with httpx.AsyncClient(headers=_headers()) as client:
        tasks = {}
        if scan.get("commits", True):
            tasks["commits"] = _fetch_commits(client, owner_repo, since_days=7)
            tasks["commits_30d"] = _fetch_commits(client, owner_repo, since_days=30)
        if scan.get("issues", True):
            tasks["issues"] = _fetch_issues(client, owner_repo)
        if scan.get("prs", True):
            tasks["prs"] = _fetch_prs(client, owner_repo)
        if scan.get("deploy_health", True):
            tasks["workflow_runs"] = _fetch_workflow_runs(client, owner_repo, default_branch)
        if scan.get("todos", True):
            tasks["todos"] = _fetch_todos(client, owner_repo, alias)

        results = {}
        if tasks:
            keys = list(tasks.keys())
            values = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for k, v in zip(keys, values):
                if isinstance(v, Exception):
                    logger.error("Failed to fetch %s for %s: %s", k, alias, v)
                    results[k] = []
                else:
                    results[k] = v

    return RepoData(
        alias=alias,
        commits=results.get("commits", []),
        commits_30d=results.get("commits_30d", []),
        issues=results.get("issues", []),
        prs=results.get("prs", []),
        workflow_runs=results.get("workflow_runs", []),
        todos=results.get("todos", []),
        collected_at=datetime.now(timezone.utc).isoformat(),
    )
