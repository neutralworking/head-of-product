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
        return yaml.safe_load(f).get("repos", {})


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

    replacements = {
        "{{all_repo_scans_json}}": json.dumps(scans, indent=2),
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
    """Basic schema validation for PM digest."""
    required = {"portfolio_status", "cross_project_ranking"}
    return required.issubset(data.keys()) and data["portfolio_status"] in ("green", "yellow", "red")


def _save_digest_file(data: dict) -> Path:
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = DIGESTS_DIR / f"{ts}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


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

    # Send to Discord
    try:
        from lib.discord_notifier import send_digest as send_discord_digest
        await send_discord_digest(digest)
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
