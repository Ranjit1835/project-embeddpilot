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
import time
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
        # free-tier TPM counts prompt + max_tokens against one per-minute
        # budget, so size the output reservation from the actual prompt.
        # chars/4 tracks real tokenization for this JSON-heavy prompt; a
        # too-safe estimate (chars/3) starves the reservation and truncates
        # the JSON payload — reasoning tokens spend from max_tokens too.
        # If chars/4 ever underestimates, the 413 handler below trims.
        configured = int(os.environ.get("GROQ_MAX_TOKENS", "5000"))
        tpm_budget = int(os.environ.get("GROQ_TPM_BUDGET", "8000"))
        prompt_est = (len(system) + len(user)) // 4
        max_tokens = max(2500, min(configured, tpm_budget - prompt_est - 300))
        delay = float(os.environ.get("GROQ_RETRY_DELAY", "15"))
        for attempt in range(5):
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
            except groq.APIStatusError as e:
                # free-tier TPM counts prompt + max_tokens against a
                # per-minute budget. Prefer WAITING for the window to roll
                # over shrinking max_tokens — a shrunken reservation
                # truncates the JSON payload, which is a worse failure
                # than a slow response.
                if e.status_code in (413, 429) and attempt < 4:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    if e.status_code == 413 and attempt >= 1 and max_tokens > 2000:
                        # window rolled and it's STILL too large: trim gently
                        max_tokens = max(2000, int(max_tokens * 0.8))
                    continue
                raise ProviderError(f"groq API error {e.status_code}: {e.message}") from e
            except groq.APIConnectionError as e:
                raise ProviderError(f"groq connection error: {e}") from e
        choice = resp.choices[0]
        text = choice.message.content or ""
        if getattr(choice, "finish_reason", None) == "length":
            # Output hit the token ceiling before the JSON object closed. On the
            # free tier prompt + max_tokens share one ~8000 TPM budget, and
            # gpt-oss reasoning tokens spend from max_tokens too, so a large
            # three-file driver can truncate mid-string. Report that plainly with
            # the actual levers instead of letting _parse_json surface a
            # confusing "Unterminated string" further down.
            raise ProviderError(
                f"response truncated at the {max_tokens}-token output ceiling "
                "(finish_reason=length): the JSON was cut off before it closed. "
                "Reduce the prompt (fewer/slimmer registers) or, if your Groq tier "
                "allows a larger per-minute budget, raise GROQ_MAX_TOKENS / "
                "GROQ_TPM_BUDGET."
            )
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
