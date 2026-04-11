"""Discord bot — listens for commands and free-form questions, triggers HoP actions."""

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import discord
from dotenv import load_dotenv

from lib.memory import get_previous_scan, get_previous_digest
from lib.model_router import route

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("hop.bot")

BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Commands that the bot responds to
HELP_TEXT = """**Head of Product Bot**

**Commands:**
`!scan <repo>` — scan a single repo
`!scan all` — scan all repos
`!digest` — generate and post a PM digest
`!status` — show latest scan status for all repos
`!status <repo>` — show latest scan for a specific repo
`!ask <question>` — ask Claude about your projects

Or just talk to me — I'll interpret what you need."""


def _load_repos() -> dict:
    import yaml
    with open(BASE_DIR / "config" / "repos.yaml") as f:
        return (yaml.safe_load(f) or {}).get("repos", {})


def _get_all_scan_statuses() -> dict[str, dict]:
    repos = _load_repos()
    statuses = {}
    for alias in repos:
        scan = get_previous_scan(alias)
        if scan:
            statuses[alias] = {
                "status": scan.get("status", "unknown"),
                "momentum": scan.get("momentum", {}).get("trend", "unknown"),
                "deploy": scan.get("deploy_health", {}).get("status", "unknown"),
            }
        else:
            statuses[alias] = {"status": "no scan data", "momentum": "—", "deploy": "—"}
    return statuses


def _status_emoji(status: str) -> str:
    return {"healthy": "🟢", "stale": "🟡", "at-risk": "🔴", "passing": "🟢", "failing": "🔴"}.get(status, "⚪")


async def _handle_scan(message: discord.Message, args: str) -> None:
    repos = _load_repos()
    if args == "all":
        await message.reply("Scanning all repos... this will take a few minutes.")
        proc = await asyncio.create_subprocess_exec(
            str(BASE_DIR / ".venv" / "bin" / "python"), "-m", "agents.repo_analyst", "--all",
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.wait()
        await message.reply(f"Scan complete for all {len(repos)} repos.")
    elif args in repos:
        await message.reply(f"Scanning **{args}**...")
        proc = await asyncio.create_subprocess_exec(
            str(BASE_DIR / ".venv" / "bin" / "python"), "-m", "agents.repo_analyst", args,
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.wait()
        if proc.returncode == 0:
            await message.reply(f"Scan complete for **{args}**.")
        else:
            await message.reply(f"Scan failed for **{args}** (exit code {proc.returncode}).")
    else:
        available = ", ".join(repos.keys())
        await message.reply(f"Unknown repo `{args}`. Available: {available}")


async def _handle_digest(message: discord.Message) -> None:
    await message.reply("Generating PM digest...")
    proc = await asyncio.create_subprocess_exec(
        str(BASE_DIR / ".venv" / "bin" / "python"), "-m", "agents.pm_aggregator",
        cwd=str(BASE_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.wait()
    if proc.returncode == 0:
        await message.reply("Digest generated and posted.")
    else:
        await message.reply(f"Digest generation failed (exit code {proc.returncode}).")


async def _handle_status(message: discord.Message, args: str) -> None:
    if args:
        scan = get_previous_scan(args)
        if scan is None:
            await message.reply(f"No scan data for `{args}`.")
            return
        lines = [
            f"**{args}** — {_status_emoji(scan.get('status', '?'))} {scan.get('status', '?')}",
            f"Momentum: {scan.get('momentum', {}).get('trend', '?')} ({scan.get('momentum', {}).get('summary', '')})",
            f"CI: {_status_emoji(scan.get('deploy_health', {}).get('status', '?'))} {scan.get('deploy_health', {}).get('status', '?')}",
        ]
        risks = scan.get("risks", [])
        if risks:
            lines.append("**Risks:**")
            for r in risks[:3]:
                lines.append(f"  • [{r.get('severity', '?')}] {r.get('description', '')}")
        priorities = scan.get("suggested_priorities", [])
        if priorities:
            lines.append("**Priorities:**")
            for p in priorities[:3]:
                lines.append(f"  {p.get('rank', '?')}. {p.get('action', '')}")
        await message.reply("\n".join(lines))
    else:
        statuses = _get_all_scan_statuses()
        lines = ["**Portfolio Status**"]
        for alias, s in statuses.items():
            lines.append(f"{_status_emoji(s['status'])} **{alias}**: {s['status']} | momentum: {s['momentum']} | CI: {s['deploy']}")
        await message.reply("\n".join(lines))


async def _handle_ask(message: discord.Message, question: str) -> None:
    # Gather context from latest scans
    statuses = _get_all_scan_statuses()
    digest = get_previous_digest()

    context = f"""You are Head of Product, a PM assistant for a portfolio of software projects.

Current scan statuses: {json.dumps(statuses)}
Latest digest: {json.dumps(digest) if digest else 'No digest yet'}

The user is asking about their projects. Answer concisely and actionably. Keep responses under 300 words."""

    try:
        response = await route("ambiguous_judgment", question, system=context)
        # Trim to Discord's 2000 char limit
        if len(response) > 1900:
            response = response[:1900] + "\n…"
        await message.reply(response)
    except Exception as exc:
        logger.error("Ask failed: %s", exc)
        await message.reply(f"Sorry, couldn't process that: {exc}")


async def _handle_freeform(message: discord.Message) -> None:
    """Interpret a free-form message and decide what action to take."""
    content = message.content.strip()
    repos = _load_repos()
    repo_list = ", ".join(repos.keys())

    prompt = f"""The user sent this message to the Head of Product Discord bot:
"{content}"

Available commands: scan <repo>, scan all, digest, status, status <repo>, ask <question>
Available repos: {repo_list}

What did the user want? Reply with EXACTLY one of:
- SCAN:<repo> or SCAN:all
- DIGEST
- STATUS:<repo> or STATUS:all
- ASK:<the question to answer>
- UNKNOWN

Reply with just the command, nothing else."""

    try:
        result = await route("ambiguous_judgment", prompt)
        result = result.strip()

        if result.startswith("SCAN:"):
            await _handle_scan(message, result[5:].strip())
        elif result == "DIGEST":
            await _handle_digest(message)
        elif result.startswith("STATUS:"):
            arg = result[7:].strip()
            await _handle_status(message, "" if arg == "all" else arg)
        elif result.startswith("ASK:"):
            await _handle_ask(message, result[4:].strip())
        else:
            await _handle_ask(message, content)
    except Exception as exc:
        logger.error("Freeform handling failed: %s", exc)
        await _handle_ask(message, content)


@client.event
async def on_ready():
    logger.info("Bot connected as %s", client.user)


@client.event
async def on_message(message: discord.Message):
    # Ignore own messages
    if message.author == client.user:
        return

    # Ignore messages not mentioning the bot and not starting with !
    content = message.content.strip()
    is_mention = client.user in message.mentions if client.user else False
    is_command = content.startswith("!")

    if not is_mention and not is_command:
        return

    # Strip mention from content
    if is_mention and client.user:
        content = content.replace(f"<@{client.user.id}>", "").strip()

    # Strip ! prefix
    if content.startswith("!"):
        content = content[1:].strip()

    # Route to handler
    cmd = content.split()[0].lower() if content else ""
    args = content[len(cmd):].strip() if cmd else ""

    if cmd == "help":
        await message.reply(HELP_TEXT)
    elif cmd == "scan":
        if not args:
            await message.reply("Usage: `!scan <repo>` or `!scan all`")
        else:
            await _handle_scan(message, args)
    elif cmd == "digest":
        await _handle_digest(message)
    elif cmd == "status":
        await _handle_status(message, args)
    elif cmd == "ask":
        if not args:
            await message.reply("Usage: `!ask <question>`")
        else:
            await _handle_ask(message, args)
    else:
        # Free-form message — interpret with Claude
        await _handle_freeform(message)


def main() -> None:
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN not set")
        return
    client.run(TOKEN)


if __name__ == "__main__":
    main()
