"""
title: Phone system prompt
author: arc-llm-lab
description: Adds the gateway's byte-stable system prompt to chats that have no system message, so Qwen knows how to use search_tools, call_tool, skills, share_file and approvals.
version: 0.1.0
"""
from pydantic import BaseModel, Field

PROMPT_FILE = r"C:\AI\gateway\prompts\phone-system.md"


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=5)
        enabled: bool = Field(default=True)

    def __init__(self):
        self.valves = self.Valves()
        self._prompt = None

    def _text(self):
        if self._prompt is None:
            try:
                self._prompt = open(PROMPT_FILE, encoding="utf-8").read().strip()
            except Exception:
                self._prompt = ""
        return self._prompt

    def inlet(self, body: dict) -> dict:
        msgs = body.get("messages") or []
        if self.valves.enabled and self._text() and not any(m.get("role") == "system" for m in msgs):
            body["messages"] = [{"role": "system", "content": self._text()}] + msgs
        return body
