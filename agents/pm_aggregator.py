"""PM aggregator agent — reads latest scans, produces cross-project digest via Claude, sends to Discord."""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from lib.memory import get_previous_digest, get_previous_scan, save_digest
from lib.model_router import route

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("hop.pm")

BASE_DIR = Path(__file__).resolve().parent.parent
REPOS_CONFIG = BASE_DIR / "config" / "repos.yaml"
PROMPT_TEMPLATE = BASE_DIR / "prompts" / "pm_digest.md"
DIGESTS_DIR = BASE_DIR / "output" / "digests"


def _load_repos() -> dict:
    with open(REPOS_CONFIG) as f:
        return (yaml.safe_load(f) or {}).get("repos", {})


def _load_prompt_template() -> str:
    with open(PROMPT_TEMPLATE) as f:
        return f.read()


def _gather_latest_scans(repos: dict) -> dict[str, dict]:
    """Get the most recent scan for each repo."""
    scans = {}
    for alias in repos:
        scan = get_previous_scan(alias)
        if scan is not None:
            scans[alias] = scan
        else:
            logger.warning("No scan data found for %s — skipping from digest", alias)
    return scans


def _build_projects_list(repos: dict) -> str:
    """Build the projects list section for the prompt."""
    lines = []
    for alias, config in repos.items():
        ptype = config.get("project_type", "unknown")
        weight = config.get("priority_weight", 1)
        lines.append(f"- {alias}: {ptype} (priority weight: {weight})")
    return "\n".join(lines)


def _build_projects_metadata(repos: dict) -> list[dict]:
    """Build metadata list for context."""
    meta = []
    for alias, config in repos.items():
        meta.append({
            "alias": alias,
            "github": config["github"],
            "project_type": config.get("project_type", "unknown"),
            "priority_weight": config.get("priority_weight", 1),
            "autofix_enabled": config.get("autofix", False),
        })
    return meta


def _build_prompt(scans: dict[str, dict], repos: dict) -> str:
    template = _load_prompt_template()
    previous_digest = get_previous_digest()
    metadata = _build_projects_metadata(repos)
    projects_list = _build_projects_list(repos)

    # Include full scan data — GPT-4o handles large context fine
    trimmed_scans = {}
    for alias, scan in scans.items():
        trimmed_scans[alias] = {
            "status": scan.get("status", "unknown"),
            "momentum": scan.get("momentum", {}),
            "deploy_health": scan.get("deploy_health", {}),
            "risks": scan.get("risks", [])[:5],
            "suggested_priorities": scan.get("suggested_priorities", [])[:5],
            "autofix_candidates": scan.get("autofix_candidates", []),
        }

    replacements = {
        "{{all_repo_scans_json}}": json.dumps(trimmed_scans, indent=2),
        "{{previous_digest_json}}": json.dumps(previous_digest, indent=2) if previous_digest else "null",
        "{{projects_metadata_json}}": json.dumps(metadata, indent=2),
        "{{current_date}}": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "{{projects_list}}": projects_list,
    }

    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def _parse_llm_json(raw: str) -> dict | None:
    """Try to extract valid JSON from LLM output."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    idx = raw.find("{")
    if idx == -1:
        return None
    depth = 0
    for i, ch in enumerate(raw[idx:], start=idx):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[idx:i + 1])
                except json.JSONDecodeError:
                    break
    return None


def _validate_digest(data: dict) -> bool:
    """Validate PM digest output against expected schema."""
    required = {"portfolio_status", "cross_project_ranking"}
    if not required.issubset(data.keys()):
        return False
    if data["portfolio_status"] not in ("green", "yellow", "red"):
        return False
    if not isinstance(data["cross_project_ranking"], list):
        return False
    if not isinstance(data.get("needs_decision", []), list):
        return False
    if not isinstance(data.get("repo_statuses", {}), dict):
        return False
    return True


def _save_digest_file(data: dict) -> Path:
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = DIGESTS_DIR / f"{ts}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def _push_digest_pr(digest_path: Path) -> str | None:
    """Commit the digest file, push to a branch, and open a PR via gh CLI."""
    import subprocess

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    branch = f"hop/digest-{ts}"
    # Determine the base branch from git
    try:
        base_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, check=True,
        )
        main_branch = base_result.stdout.strip()
    except subprocess.CalledProcessError:
        main_branch = "main"
    repo_url = "neutralworking/head-of-product"

    try:
        # Create branch from current HEAD
        subprocess.run(["git", "checkout", "-b", branch], cwd=BASE_DIR, check=True, capture_output=True)
        # Stage the digest file
        subprocess.run(["git", "add", str(digest_path)], cwd=BASE_DIR, check=True, capture_output=True)
        # Commit
        subprocess.run(
            ["git", "commit", "-m", f"[HoP] PM Digest {ts}"],
            cwd=BASE_DIR, check=True, capture_output=True,
        )
        # Push
        subprocess.run(
            ["git", "push", "origin", branch],
            cwd=BASE_DIR, check=True, capture_output=True,
        )
        # Open PR
        result = subprocess.run(
            ["gh", "pr", "create",
             "--repo", repo_url,
             "--base", main_branch,
             "--head", branch,
             "--title", f"[HoP] PM Digest {ts}",
             "--body", f"Auto-generated PM digest.\n\nFull report: `{digest_path.name}`"],
            cwd=BASE_DIR, check=True, capture_output=True, text=True,
        )
        pr_url = result.stdout.strip()
        # Switch back to main branch
        subprocess.run(["git", "checkout", main_branch], cwd=BASE_DIR, capture_output=True)
        return pr_url
    except subprocess.CalledProcessError as exc:
        logger.error("Git/PR operation failed: %s\n%s", exc, exc.stderr)
        # Try to get back to main branch
        subprocess.run(["git", "checkout", main_branch], cwd=BASE_DIR, capture_output=True)
        raise


async def produce_digest(dry_run: bool = False) -> dict | None:
    """Produce the PM digest from latest scans."""
    repos = _load_repos()
    scans = _gather_latest_scans(repos)

    if not scans:
        logger.error("No scan data available for any repo — cannot produce digest")
        return None

    logger.info("Producing digest from %d repo scans: %s", len(scans), ", ".join(scans.keys()))

    # Build prompt
    prompt = _build_prompt(scans, repos)

    # Call Claude for PM synthesis
    logger.info("Sending digest prompt to Claude")
    raw_response = await route("pm_synthesis", prompt)

    # Parse JSON
    digest = _parse_llm_json(raw_response)
    if digest is None:
        logger.error("Failed to parse digest JSON. Raw response:\n%s", raw_response[:1000])
        return None

    if not _validate_digest(digest):
        logger.error("Digest failed validation: %s", json.dumps(digest)[:500])
        return None

    # Add timestamp
    digest["timestamp"] = datetime.now(timezone.utc).isoformat()

    if dry_run:
        print(json.dumps(digest, indent=2))
        return digest

    # Save
    path = _save_digest_file(digest)
    save_digest(digest)
    logger.info("Saved digest: %s", path)

    # Push digest to GitHub and open PR
    pr_url = None
    try:
        pr_url = _push_digest_pr(path)
        logger.info("Opened digest PR: %s", pr_url)
    except Exception as exc:
        logger.error("Failed to push digest PR: %s", exc)

    # Send to Discord (include PR link)
    try:
        from lib.discord_notifier import send_digest as send_discord_digest
        await send_discord_digest(digest, pr_url=pr_url)
        logger.info("Digest sent to Discord")
    except Exception as exc:
        logger.error("Failed to send digest to Discord: %s", exc)

    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Head of Product — PM Aggregator")
    parser.add_argument("--dry-run", action="store_true", help="Produce digest but don't send to Discord")
    args = parser.parse_args()

    asyncio.run(produce_digest(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
