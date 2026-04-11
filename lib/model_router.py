"""Routes prompts to Ollama or Claude based on task type in config."""

import asyncio
import logging
import os
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("hop.router")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"
DEFAULT_TIMEOUT = 3600.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def _resolve_backend(task: str, config: dict) -> str:
    """Return 'ollama', 'claude', or 'openai' for a given task."""
    for backend in ("ollama", "claude", "openai"):
        if task in config.get(backend, {}).get("tasks", []):
            return backend
    return config.get("routing", {}).get("default", "ollama")


async def _call_ollama(prompt: str, system: str, config: dict) -> str:
    base_url = config["ollama"].get("base_url", os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    model = config["ollama"]["model"]
    url = f"{base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": True,
        "options": {
            "num_ctx": config["ollama"].get("num_ctx", 4096),
        },
        "keep_alive": "30m",
    }

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", url, json=payload, timeout=DEFAULT_TIMEOUT) as resp:
                    resp.raise_for_status()
                    output = ""
                    async for line in resp.aiter_lines():
                        import json as _json
                        data = _json.loads(line)
                        output += data.get("response", "")
                        if data.get("done"):
                            break
                    return output
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF * (2 ** attempt)
            logger.warning("Ollama request failed (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, MAX_RETRIES, wait, exc)
            await asyncio.sleep(wait)
    raise RuntimeError(f"Ollama request failed after {MAX_RETRIES} retries: {last_exc}")


async def _call_claude(prompt: str, system: str, config: dict) -> str:
    """Call Claude via Anthropic API (requires ANTHROPIC_API_KEY)."""
    model = config["claude"]["model"]
    token = os.environ.get("ANTHROPIC_API_KEY", "")
    if not token:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system

    last_exc: Exception | None = None
    async with httpx.AsyncClient() as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "")
                return ""
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    logger.error("Claude API error %s: %s", exc.response.status_code, exc.response.text[:300])
                    raise
                wait = RETRY_BACKOFF * (2 ** attempt)
                logger.warning("Claude request failed (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, MAX_RETRIES, wait, exc)
                await asyncio.sleep(wait)
    raise RuntimeError(f"Claude request failed after {MAX_RETRIES} retries: {last_exc}")


async def _call_openai(prompt: str, system: str, config: dict) -> str:
    """Call OpenAI API (requires OPENAI_API_KEY)."""
    model = config["openai"]["model"]
    token = os.environ.get("OPENAI_API_KEY", "")
    if not token:
        raise RuntimeError("OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
    }

    last_exc: Exception | None = None
    async with httpx.AsyncClient() as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload, headers=headers, timeout=120.0)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    logger.error("OpenAI API error %s: %s", exc.response.status_code, exc.response.text[:300])
                    raise
                wait = RETRY_BACKOFF * (2 ** attempt)
                logger.warning("OpenAI request failed (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, MAX_RETRIES, wait, exc)
                await asyncio.sleep(wait)
    raise RuntimeError(f"OpenAI request failed after {MAX_RETRIES} retries: {last_exc}")


async def route(task: str, prompt: str, system: str = "") -> str:
    """Route a prompt to the appropriate model backend based on task type."""
    config = _load_config()
    backend = _resolve_backend(task, config)
    logger.info("Routing task '%s' to %s", task, backend)

    if backend == "claude":
        return await _call_claude(prompt, system, config)
    elif backend == "openai":
        return await _call_openai(prompt, system, config)
    else:
        return await _call_ollama(prompt, system, config)
