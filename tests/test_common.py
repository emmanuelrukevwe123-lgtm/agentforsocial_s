import pytest

import scriptmd
from common import llm


def test_claude_env_strips_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "ANTHROPIC_API_KEY" not in llm.claude_env()


def test_claude_command_refuses_bare(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda _: "claude")
    assert llm.claude_command("hi")[:4] == ["claude", "-p", "hi", "--output-format"]
    with pytest.raises(llm.LLMError):
        llm.claude_command("hi", extra=["--bare"])


def test_scriptmd_parse():
    text = """---
title: Test
target_seconds: 30
---
## Script
[1] First line here.
[2] Second.

## Visuals
[1] screen: terminal

## Alt hooks
[1] ignored
"""
    s = scriptmd.parse(text)
    assert s["meta"]["title"] == "Test"
    assert s["lines"] == {1: "First line here.", 2: "Second."}
    assert s["visuals"] == {1: "screen: terminal"}
    assert s["word_count"] == 4
