"""Repo analyst agent — feeds raw GitHub data + prompt to Ollama, outputs structured JSON per repo."""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from lib.github_client import RepoData, collect_repo_data
from lib.memory import get_previous_scan, save_scan
from lib.model_router import route

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("hop.analyst")

BASE_DIR = Path(__file__).resolve().parent.parent
REPOS_CONFIG = BASE_DIR / "config" / "repos.yaml"
AUTOFIX_CONFIG = BASE_DIR / "config" / "autofix-policy.yaml"
PROMPT_TEMPLATE = BASE_DIR / "prompts" / "repo_analyst.md"
REPORTS_DIR = BASE_DIR / "output" / "reports"


def _load_repos() -> dict:
    with open(REPOS_CONFIG) as f:
        return (yaml.safe_load(f) or {}).get("repos", {})


def _load_autofix_allowed() -> list[str]:
    with open(AUTOFIX_CONFIG) as f:
        return (yaml.safe_load(f) or {}).get("allowed", [])


def _load_prompt_template() -> str:
    with open(PROMPT_TEMPLATE) as f:
        return f.read()


def _build_deploy_status(workflow_runs: list[dict]) -> dict:
    """Extract deploy health summary from workflow runs."""
    if not workflow_runs:
        return {
            "status": "unknown",
            "last_green": None,
            "last_run": None,
            "failing_workflows": [],
            "failure_summary": None,
        }

    last_run = workflow_runs[0] if workflow_runs else None
    last_run_at = last_run.get("updated_at") if last_run else None

    failing = []
    last_green = None
    for run in workflow_runs:
        conclusion = run.get("conclusion", "")
        if conclusion == "failure":
            failing.append(run.get("name", "unknown"))
        if conclusion == "success" and last_green is None:
            last_green = run.get("updated_at")

    status = "passing"
    if failing:
        status = "failing"
    elif not workflow_runs:
        status = "unknown"

    failure_summary = None
    if failing:
        failure_summary = f"{len(failing)} workflow(s) failing: {', '.join(failing[:5])}"

    return {
        "status": status,
        "last_green": last_green,
        "last_run": last_run_at,
        "failing_workflows": failing,
        "failure_summary": failure_summary,
    }


def _build_prompt(repo_data: RepoData, repo_config: dict, previous_scan: dict | None) -> str:
    template = _load_prompt_template()
    autofix_allowed = _load_autofix_allowed()
    deploy_status = _build_deploy_status(repo_data.workflow_runs)

    # Trim large payloads to avoid blowing context limits
    commits_trimmed = [
        {"sha": c.get("sha", "")[:8], "message": c.get("commit", {}).get("message", "")[:200], "date": c.get("commit", {}).get("author", {}).get("date", "")}
        for c in repo_data.commits[:50]
    ]
    commits_7d_count = len(repo_data.commits)
    commits_30d_count = len(repo_data.commits_30d)
    issues_trimmed = [
        {"number": i.get("number"), "title": i.get("title", "")[:150], "labels": [l.get("name", "") for l in i.get("labels", [])], "created_at": i.get("created_at", "")}
        for i in repo_data.issues[:30]
    ]
    prs_trimmed = [
        {"number": p.get("number"), "title": p.get("title", "")[:150], "user": p.get("user", {}).get("login", ""), "created_at": p.get("created_at", ""), "updated_at": p.get("updated_at", ""), "draft": p.get("draft", False)}
        for p in repo_data.prs[:30]
    ]
    todos_trimmed = [
        {"file": t.get("path", ""), "text": t.get("name", "")[:200]}
        for t in repo_data.todos[:50]
    ]

    replacements = {
        "{{repo_alias}}": repo_data.alias,
        "{{repo_url}}": repo_config["github"],
        "{{project_type}}": repo_config.get("project_type", "unknown"),
        "{{commits_json}}": json.dumps(commits_trimmed, indent=2),
        "{{commits_7d_count}}": str(commits_7d_count),
        "{{commits_30d_count}}": str(commits_30d_count),
        "{{issues_json}}": json.dumps(issues_trimmed, indent=2),
        "{{prs_json}}": json.dumps(prs_trimmed, indent=2),
        "{{test_output}}": "Not available",
        "{{todos_json}}": json.dumps(todos_trimmed, indent=2),
        "{{deploy_status}}": json.dumps(deploy_status, indent=2),
        "{{previous_scan_json}}": json.dumps(previous_scan, indent=2) if previous_scan else "null",
        "{{autofix_allowed}}": json.dumps(autofix_allowed),
    }

    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def _parse_llm_json(raw: str) -> dict | None:
    """Try to extract valid JSON from LLM output."""
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in the response
    for start_marker in ("{",):
        idx = raw.find(start_marker)
        if idx == -1:
            continue
        # Find matching closing brace
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


def _validate_scan(data: dict) -> bool:
    """Validate repo scan output against expected schema."""
    required_top = {"repo", "timestamp", "status"}
    if not required_top.issubset(data.keys()):
        return False
    if data["status"] not in ("healthy", "stale", "at-risk"):
        return False
    # Validate nested structures exist and have correct types
    momentum = data.get("momentum")
    if momentum is not None and not isinstance(momentum, dict):
        return False
    deploy = data.get("deploy_health")
    if deploy is not None and not isinstance(deploy, dict):
        return False
    if not isinstance(data.get("risks", []), list):
        return False
    if not isinstance(data.get("todos", []), list):
        return False
    if not isinstance(data.get("autofix_candidates", []), list):
        return False
    if not isinstance(data.get("suggested_priorities", []), list):
        return False
    return True


def _save_report(alias: str, data: dict) -> Path:
    report_dir = REPORTS_DIR / alias
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / f"{ts}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


async def scan_repo(alias: str, repo_config: dict, dry_run: bool = False) -> dict | None:
    """Scan a single repo: collect data -> prompt LLM -> parse -> save."""
    logger.info("Scanning repo: %s (%s)", alias, repo_config["github"])

    # Collect data
    repo_data = await collect_repo_data(repo_config, alias)
    logger.info(
        "Collected for %s: %d commits, %d issues, %d PRs, %d workflow runs, %d TODOs",
        alias,
        len(repo_data.commits),
        len(repo_data.issues),
        len(repo_data.prs),
        len(repo_data.workflow_runs),
        len(repo_data.todos),
    )

    if dry_run:
        print(json.dumps({
            "alias": alias,
            "commits": len(repo_data.commits),
            "issues": len(repo_data.issues),
            "prs": len(repo_data.prs),
            "workflow_runs": len(repo_data.workflow_runs),
            "todos": len(repo_data.todos),
            "collected_at": repo_data.collected_at,
        }, indent=2))
        return None

    # Build prompt
    previous_scan = get_previous_scan(alias)
    prompt = _build_prompt(repo_data, repo_config, previous_scan)

    # Call LLM
    logger.info("Sending prompt to model for %s", alias)
    raw_response = await route("repo_scan", prompt)

    # Parse JSON
    scan_result = _parse_llm_json(raw_response)
    if scan_result is None:
        logger.error("Failed to parse LLM JSON for %s. Raw response:\n%s", alias, raw_response[:1000])
        return None

    if not _validate_scan(scan_result):
        logger.error("Scan output failed validation for %s: %s", alias, json.dumps(scan_result)[:500])
        return None

    # Save
    report_path = _save_report(alias, scan_result)
    save_scan(alias, scan_result)
    logger.info("Saved report for %s: %s", alias, report_path)

    # Alert on CI failure
    deploy_health = scan_result.get("deploy_health", {})
    if deploy_health.get("status") == "failing":
        try:
            from lib.discord_notifier import send_alert
            failing = deploy_health.get("failing_workflows", [])
            msg = f"🔴 **{alias}** — CI failing: {', '.join(failing[:5])}"
            await send_alert(msg)
        except Exception as exc:
            logger.warning("Failed to send CI alert for %s: %s", alias, exc)

    return scan_result


async def scan_all(repos: dict, dry_run: bool = False) -> dict[str, dict | None]:
    """Scan all repos sequentially."""
    results = {}
    for alias, config in repos.items():
        try:
            results[alias] = await scan_repo(alias, config, dry_run=dry_run)
        except Exception as exc:
            logger.error("Scan failed for %s: %s", alias, exc, exc_info=True)
            results[alias] = None
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Head of Product — Repo Analyst")
    parser.add_argument("repo", nargs="?", help="Repo alias to scan (from repos.yaml)")
    parser.add_argument("--all", action="store_true", help="Scan all repos in repos.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Collect data only, don't call LLM or save")
    args = parser.parse_args()

    if not args.all and not args.repo:
        parser.error("Specify a repo alias or use --all")

    repos = _load_repos()

    if args.all:
        asyncio.run(scan_all(repos, dry_run=args.dry_run))
    else:
        if args.repo not in repos:
            logger.error("Repo '%s' not found in repos.yaml. Available: %s", args.repo, ", ".join(repos.keys()))
            sys.exit(1)
        asyncio.run(scan_repo(args.repo, repos[args.repo], dry_run=args.dry_run))


if __name__ == "__main__":
    main()
