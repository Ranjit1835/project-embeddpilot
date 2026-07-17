"""LLM provider abstraction for the worker.

GroqProvider is the live backend (user decision 2026-07-15: Groq for now).
MockProvider drives tests and the retry-loop machinery without network access.
The worker only sees `complete_json(system, user) -> dict`, so swapping
providers later (e.g. to the Anthropic API) touches this file only.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

# proven live 2026-07-17: gpt-oss-120b converged in 2 attempts on the W25Q64
# command driver; llama-3.3-70b works too but has a tighter free-tier budget
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class ProviderError(Exception):
    pass


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict: ...


class GroqProvider:
    """Groq chat completions with JSON-object response format."""

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        self.name = f"groq/{self.model}"
        if not os.environ.get("GROQ_API_KEY"):
            raise ProviderError(
                "GROQ_API_KEY is not set — set it in the environment to enable "
                "the LLM generation path (tests use the mock provider instead)"
            )
        import groq

        self._client = groq.Groq()

    def complete_json(self, system: str, user: str) -> dict:
        import groq

        is_reasoning = "gpt-oss" in self.model
        kwargs = {}
        # gpt-oss models reject strict json mode and spend the output budget
        # on reasoning; the fence-tolerant parser + a low effort cap cover them
        json_default = "off" if is_reasoning else "on"
        if os.environ.get("GROQ_JSON_MODE", json_default) != "off":
            kwargs["response_format"] = {"type": "json_object"}
        effort = os.environ.get("GROQ_REASONING_EFFORT", "low" if is_reasoning else "")
        if effort:
            kwargs["reasoning_effort"] = effort
        max_tokens = int(os.environ.get("GROQ_MAX_TOKENS", "5000"))
        while True:
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                break
            except groq.APIStatusError as e:  # incl. 413/429 rate limits
                # free-tier TPM counts prompt + max_tokens against one budget;
                # a 413 usually means the output reservation is too greedy —
                # shrink it and retry before giving up
                if e.status_code == 413 and max_tokens > 2500:
                    max_tokens = max(2500, max_tokens // 2)
                    continue
                raise ProviderError(f"groq API error {e.status_code}: {e.message}") from e
            except groq.APIConnectionError as e:
                raise ProviderError(f"groq connection error: {e}") from e
        text = resp.choices[0].message.content or ""
        return _parse_json(text)


class MockProvider:
    """Deterministic provider for tests: pops canned responses in order."""

    def __init__(self, responses: list[dict]):
        self.name = "mock"
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []  # (system, user) per call

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if not self._responses:
            raise ProviderError("mock provider exhausted")
        return self._responses.pop(0)


def _parse_json(text: str) -> dict:
    """Models occasionally wrap JSON in code fences despite json mode."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ProviderError(f"provider returned non-JSON output: {e}") from e
