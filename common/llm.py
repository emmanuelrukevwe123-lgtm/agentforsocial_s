"""One function, three back ends, for batch jobs outside an interactive Claude Code session.

  claude  (default) `claude -p --output-format json`, billed to the logged-in Pro subscription.
  gemini  Gemini API free tier. Free-tier prompts are used to train Google's models,
          so never send ID numbers or private documents.
  paste   Prints the prompt and waits for you to paste the answer. Safety net if the
          `claude -p` billing rules change.

The interactive skills (/ideas, /script, /package) do not need this module. It exists for
headless batches and for the job agent that will reuse it.

Usage: python -m common.llm --backend paste "Write three hooks about Supabase RLS"
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from common.config import load_env, utf8_stdout

BACKENDS = ("claude", "gemini", "paste")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    pass


def claude_env() -> dict[str, str]:
    """Child env without ANTHROPIC_API_KEY, so `claude -p` uses the subscription login."""
    env = dict(os.environ)
    if env.pop("ANTHROPIC_API_KEY", None) is not None:
        print("WARNING: ANTHROPIC_API_KEY was set; removed it for this call to avoid API billing. "
              "Unset it in your shell.", file=sys.stderr)
    return env


def claude_command(prompt: str, model: str | None = None, extra: list[str] | None = None) -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise LLMError("`claude` CLI not found on PATH.")
    args = [exe, "-p", prompt, "--output-format", "json"]
    if model:
        args += ["--model", model]
    extra = extra or []
    if any(a == "--bare" for a in extra):
        raise LLMError("--bare skips the subscription login and needs an API key. Not allowed here.")
    return args + extra


def _claude(prompt: str, model: str | None, timeout: int) -> str:
    proc = subprocess.run(claude_command(prompt, model), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=claude_env(), timeout=timeout)
    if proc.returncode != 0:
        raise LLMError(f"claude -p failed: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(f"claude -p returned non-JSON output: {proc.stdout[:300]}") from exc
    if data.get("is_error"):
        raise LLMError(f"claude -p error: {data.get('result')}")
    return data.get("result", "")


def _gemini(prompt: str, model: str | None, timeout: int) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY is not set (add it to .env).")
    model = model or os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(GEMINI_URL.format(model=model), data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise LLMError(f"Gemini HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected Gemini response: {json.dumps(data)[:300]}") from exc


def _paste(prompt: str, model: str | None, timeout: int) -> str:
    print("=" * 20 + " PROMPT (paste into Claude Code) " + "=" * 20, file=sys.stderr)
    print(prompt, file=sys.stderr)
    print("=" * 20 + " Paste the answer, then a line with only END " + "=" * 7, file=sys.stderr)
    lines = []
    for line in sys.stdin:
        if line.strip() == "END":
            break
        lines.append(line)
    return "".join(lines).strip()


def complete(prompt: str, backend: str | None = None, model: str | None = None, timeout: int = 300) -> str:
    load_env()
    backend = backend or os.environ.get("LLM_BACKEND", "claude")
    if backend not in BACKENDS:
        raise LLMError(f"Unknown backend {backend!r}; choose from {BACKENDS}")
    return {"claude": _claude, "gemini": _gemini, "paste": _paste}[backend](prompt, model, timeout)


def main() -> None:
    utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt")
    parser.add_argument("--backend", choices=BACKENDS)
    parser.add_argument("--model")
    args = parser.parse_args()
    try:
        print(complete(args.prompt, args.backend, args.model))
    except LLMError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
