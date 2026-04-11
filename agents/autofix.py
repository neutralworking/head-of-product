"""Autofix executor — checks candidates against policy, branches, fixes, tests, opens PRs."""

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from lib.memory import get_previous_scan

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("hop.autofix")

BASE_DIR = Path(__file__).resolve().parent.parent
REPOS_CONFIG = BASE_DIR / "config" / "repos.yaml"
AUTOFIX_CONFIG = BASE_DIR / "config" / "autofix-policy.yaml"

# Fix commands per autofix type
FIX_COMMANDS: dict[str, list[str]] = {
    "lint_format": ["python", "-m", "black", "."],
    "import_sort": ["python", "-m", "isort", "."],
    "dead_link_docs": ["echo", "dead_link_docs: manual review required"],
    "type_stub_cleanup": ["echo", "type_stub_cleanup: manual review required"],
    "test_snapshot_refresh": ["echo", "test_snapshot_refresh: manual review required"],
}


def _load_repos() -> dict:
    with open(REPOS_CONFIG) as f:
        return (yaml.safe_load(f) or {}).get("repos", {})


def _load_autofix_policy() -> dict:
    with open(AUTOFIX_CONFIG) as f:
        return yaml.safe_load(f) or {}


def _is_allowed(fix_type: str, policy: dict) -> bool:
    allowed = policy.get("allowed", [])
    blocked = policy.get("blocked", [])
    if fix_type in blocked:
        return False
    return fix_type in allowed


def _run_command(cmd: list[str], cwd: str) -> tuple[int, str]:
    """Run a shell command and return (returncode, output)."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return 1, "Command timed out"
    except FileNotFoundError:
        return 1, f"Command not found: {cmd[0]}"


async def process_autofix_candidates(alias: str, repo_config: dict) -> list[dict]:
    """Process autofix candidates for a single repo."""
    policy = _load_autofix_policy()
    branch_prefix = policy.get("branch_prefix", "hop/autofix/")

    if not repo_config.get("autofix", False):
        logger.info("Autofix disabled for %s", alias)
        return []

    scan = get_previous_scan(alias)
    if scan is None:
        logger.warning("No scan data for %s — skipping autofix", alias)
        return []

    candidates = scan.get("autofix_candidates", [])
    if not candidates:
        logger.info("No autofix candidates for %s", alias)
        return []

    results = []
    owner_repo = repo_config["github"]
    token = os.environ.get("GITHUB_TOKEN", "")

    for candidate in candidates:
        fix_type = candidate.get("type", "")
        description = candidate.get("description", "")
        safe = candidate.get("safe", False)

        if not _is_allowed(fix_type, policy):
            logger.info("Autofix type '%s' blocked by policy for %s", fix_type, alias)
            results.append({"type": fix_type, "status": "blocked_by_policy", "description": description})
            continue

        if not safe:
            logger.info("Autofix candidate '%s' marked unsafe for %s — skipping", fix_type, alias)
            results.append({"type": fix_type, "status": "skipped_unsafe", "description": description})
            continue

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        branch_name = f"{branch_prefix}{fix_type}-{ts}"

        logger.info("Processing autofix: %s for %s (branch: %s)", fix_type, alias, branch_name)

        # TODO: Implement full git clone + branch + fix + test + PR flow
        # For now, log what would happen:
        #
        # 1. Clone repo to temp dir:
        #    git clone https://x-access-token:{token}@github.com/{owner_repo}.git {tmpdir}
        #
        # 2. Create branch:
        #    git checkout -b {branch_name}
        #
        # 3. Run fix command:
        #    FIX_COMMANDS.get(fix_type, ["echo", "no-op"])
        #
        # 4. Run tests:
        #    auto-detect test runner (pytest, npm test, etc.)
        #
        # 5. If tests pass:
        #    git add . && git commit -m "[HoP Auto-Fix] {description}"
        #    git push origin {branch_name}
        #    Open PR via GitHub API with title "[HoP Auto-Fix] {description}", label "autofix"
        #    Post to digests Discord
        #
        # 6. If tests fail:
        #    Abandon branch, log failure

        results.append({
            "type": fix_type,
            "status": "proposed",
            "description": description,
            "branch": branch_name,
            "repo": owner_repo,
        })
        logger.info(
            "Autofix proposed for %s: [%s] %s -> branch %s (PR creation stubbed — see TODO)",
            alias, fix_type, description, branch_name,
        )

    return results


async def run_all() -> dict[str, list[dict]]:
    """Process autofix candidates for all repos."""
    repos = _load_repos()
    all_results = {}
    for alias, config in repos.items():
        try:
            results = await process_autofix_candidates(alias, config)
            all_results[alias] = results
        except Exception as exc:
            logger.error("Autofix processing failed for %s: %s", alias, exc, exc_info=True)
            all_results[alias] = []
    return all_results


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Head of Product — Autofix Executor")
    parser.add_argument("repo", nargs="?", help="Repo alias (or omit for all)")
    parser.add_argument("--all", action="store_true", help="Process all repos")
    args = parser.parse_args()

    repos = _load_repos()

    if args.all or not args.repo:
        results = asyncio.run(run_all())
    else:
        if args.repo not in repos:
            logger.error("Repo '%s' not found", args.repo)
            return
        results = {args.repo: asyncio.run(process_autofix_candidates(args.repo, repos[args.repo]))}

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
