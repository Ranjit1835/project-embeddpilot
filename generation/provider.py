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


class ContextWindowError(ProviderError):
    """The assembled prompt + expected output does not fit the provider's
    context window. Raised BEFORE the request so the maps are never truncated
    and the system never silently degrades to a weaker strategy (V1.7.1)."""


def estimate_tokens(text: str) -> int:
    """Token estimate for gpt-oss on these JSON-heavy prompts. Measured live at
    ~chars/3.7; we divide by 3.5 to bias slightly toward OVER-estimation so the
    fit check errs on the safe side."""
    return int(len(text) / 3.5)


def assert_prompt_fits(
    name: str, context_window: int, system: str, user: str, expected_output: int
) -> None:
    """Fail loudly and specifically when a request will not fit, naming the
    provider, the required size, and the provider's limit (V1.7.1 Task 1). Never
    truncate; never fall back to a weaker retry strategy."""
    prompt_tokens = estimate_tokens(system) + estimate_tokens(user)
    need = prompt_tokens + expected_output
    if need > context_window:
        raise ContextWindowError(
            f"prompt does not fit provider '{name}': needs ~{need} tokens "
            f"(~{prompt_tokens} prompt + {expected_output} expected output) but "
            f"the provider context window is {context_window}. Configure a "
            "larger-window provider (e.g. NVIDIA) — EmbeddPilot never truncates "
            "the device/MCU maps to make a job fit."
        )


class LLMProvider(Protocol):
    name: str
    context_window: int

    def complete_json(self, system: str, user: str) -> dict: ...


class VisionCapableProvider(Protocol):
    """A provider that can transcribe an image to text.

    This is a SEPARATE, explicitly-named capability — it does NOT extend
    complete_json.  Vision transcription is a fundamentally different
    operation (binary image in, prose out) and must never silently replace
    or overload the JSON-generation contract that the rest of the pipeline
    depends on.
    """

    name: str

    def transcribe_image(self, image_bytes: bytes, mime_type: str) -> str:
        """Send `image_bytes` to a vision model and return a plain-text
        transcription.

        The transcription is LOSSY and UNCERTAIN.  Callers MUST label the
        result as a machine read that requires human review before it is
        used as a requirement.  Raises ProviderError on any failure —
        callers must NOT silently degrade to a blank or partial read
        presented as complete.
        """
        ...


class GroqProvider:
    """Groq chat completions with JSON-object response format."""

    # Vision transcription is not supported on this provider.  The flag is
    # checked by callers so they can refuse honestly rather than failing
    # with a cryptic AttributeError.
    has_vision: bool = False

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        self.name = f"groq/{self.model}"
        # Free-tier admission is a per-minute budget that behaves like a context
        # window: prompt + output must fit it. Override via GROQ_TPM_BUDGET for a
        # paid tier. A both-maps V1.7 job will not fit 8000 and now fails loudly.
        self.context_window = int(os.environ.get("GROQ_TPM_BUDGET", "8000"))
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


DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-120b"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NVIDIAProvider:
    """NVIDIA API (build.nvidia.com) via its OpenAI-compatible endpoint. Hosts
    the same openai/gpt-oss-120b model as Groq but with a large context/output
    window, so the both-maps V1.7 prompt (device map + MCU map + complete-driver
    output) fits where Groq's ~8000 TPM free tier 413s."""

    # Vision transcription is not supported on this provider.
    has_vision: bool = False

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("NVIDIA_MODEL", DEFAULT_NVIDIA_MODEL)
        self.name = f"nvidia/{self.model}"
        # gpt-oss-120b on NVIDIA exposes a 128K context; the both-maps job and
        # the targeted-edit echo fit comfortably. Override via NVIDIA_CONTEXT.
        self.context_window = int(os.environ.get("NVIDIA_CONTEXT", "128000"))
        key = os.environ.get("NVIDIA_API_KEY")
        if not key:
            raise ProviderError("NVIDIA_API_KEY is not set")
        from openai import OpenAI

        self._client = OpenAI(
            base_url=os.environ.get("NVIDIA_BASE_URL", NVIDIA_BASE_URL), api_key=key
        )

    def complete_json(self, system: str, user: str) -> dict:
        import openai

        max_tokens = int(os.environ.get("NVIDIA_MAX_TOKENS", "8000"))
        effort = os.environ.get("NVIDIA_REASONING_EFFORT", "low")
        base_kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        # gpt-oss takes reasoning_effort; if this deployment rejects the param,
        # retry once without it rather than failing the whole generation.
        attempt_kwargs = dict(base_kwargs, reasoning_effort=effort) if effort else dict(base_kwargs)
        delay = float(os.environ.get("NVIDIA_RETRY_DELAY", "10"))
        resp = None
        for attempt in range(4):
            try:
                resp = self._client.chat.completions.create(**attempt_kwargs)
                break
            except openai.BadRequestError as e:
                if "reasoning_effort" in attempt_kwargs and "reasoning" in str(e).lower():
                    attempt_kwargs = dict(base_kwargs)  # drop the unsupported param
                    continue
                raise ProviderError(f"nvidia API error 400: {e}") from e
            except openai.APIStatusError as e:
                if e.status_code in (429, 503) and attempt < 3:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise ProviderError(f"nvidia API error {e.status_code}: {e.message}") from e
            except openai.APIConnectionError as e:
                raise ProviderError(f"nvidia connection error: {e}") from e
        choice = resp.choices[0]
        text = choice.message.content or ""
        if getattr(choice, "finish_reason", None) == "length":
            raise ProviderError(
                f"response truncated at the {max_tokens}-token output ceiling "
                "(finish_reason=length) — raise NVIDIA_MAX_TOKENS."
            )
        return _parse_json(text)


# Google Gemini via its OpenAI-compatible endpoint. Default to a FREE-tier flash
# model so live generation costs nothing. The API retired the 2.0/2.5 flash
# models (confirmed live 2026-08-24: it recommends gemini-3.6-flash); flash-tier
# models have a large (~1M-token) context. Override with GEMINI_MODEL.
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Free flash-tier options (verify current availability; Google retires old ones):
FREE_GEMINI_MODELS = {
    "gemini-3.6-flash", "gemini-3.6-flash-lite", "gemini-3-flash",
    "gemini-2.5-flash", "gemini-2.5-flash-lite",
}


class GeminiProvider:
    """Google Gemini through the OpenAI-compatible endpoint. Free-tier models have
    a large (~1M-token) context window, so the both-maps V1.7 job fits (like
    NVIDIA, unlike Groq's 8000-TPM free tier).

    GeminiProvider is the only provider that supports vision transcription
    (has_vision = True).  The OpenAI-compatible endpoint accepts image_url
    parts in the messages array, which Gemini's multimodal models handle
    natively.
    """

    has_vision: bool = True

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.name = f"gemini/{self.model}"
        if self.model not in FREE_GEMINI_MODELS:
            # not a hard error (Google may add free models), but say so plainly
            print(f"[provider] note: GEMINI_MODEL '{self.model}' is not in the "
                  "known free-tier list — verify it is free before heavy use")
        # gemini-2.0-flash exposes ~1M context; override via GEMINI_CONTEXT.
        self.context_window = int(os.environ.get("GEMINI_CONTEXT", "1000000"))
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError(
                "GEMINI_API_KEY is not set — set it in the environment (never "
                "commit it) to use the Gemini provider")
        from openai import OpenAI

        self._client = OpenAI(
            base_url=os.environ.get("GEMINI_BASE_URL", GEMINI_BASE_URL), api_key=key
        )

    def complete_json(self, system: str, user: str) -> dict:
        import openai

        max_tokens = int(os.environ.get("GEMINI_MAX_TOKENS", "8000"))
        base_kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        # ask for a JSON object; drop it and retry once if this model/endpoint
        # rejects the param rather than failing the whole generation.
        attempt_kwargs = dict(base_kwargs, response_format={"type": "json_object"})
        delay = float(os.environ.get("GEMINI_RETRY_DELAY", "10"))
        resp = None
        for attempt in range(4):
            try:
                resp = self._client.chat.completions.create(**attempt_kwargs)
                break
            except openai.BadRequestError as e:
                if "response_format" in attempt_kwargs:
                    attempt_kwargs = dict(base_kwargs)  # drop unsupported param
                    continue
                raise ProviderError(f"gemini API error 400: {e}") from e
            except openai.APIStatusError as e:
                # 429 = free-tier rate/quota; wait and retry (its window rolls)
                if e.status_code in (429, 503) and attempt < 3:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise ProviderError(f"gemini API error {e.status_code}: {e.message}") from e
            except openai.APIConnectionError as e:
                raise ProviderError(f"gemini connection error: {e}") from e
        choice = resp.choices[0]
        text = choice.message.content or ""
        if getattr(choice, "finish_reason", None) == "length":
            raise ProviderError(
                f"response truncated at the {max_tokens}-token output ceiling "
                "(finish_reason=length) — raise GEMINI_MAX_TOKENS (free-tier flash "
                "caps output at ~8192)."
            )
        return _parse_json(text)

    def transcribe_image(self, image_bytes: bytes, mime_type: str) -> str:
        """Transcribe `image_bytes` to plain text via Gemini's vision capability.

        The Gemini OpenAI-compatible endpoint accepts an `image_url` part
        carrying a base64 data URI in the messages array.  The model is asked
        to transcribe faithfully and to flag any uncertainty explicitly rather
        than smoothing it over — an uncertain transcription must surface as
        such, not vanish into a clean-looking but invented read.

        Raises ProviderError on any failure.  Callers MUST NOT catch this and
        substitute a blank or partial transcription — a refusal is the correct
        degradation; a fabricated read is not.
        """
        import base64
        import openai

        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_uri = f"data:{mime_type};base64,{b64}"

        # Thinking model (gemini-3.6-flash): reasoning tokens share the output
        # budget, so we need a generous max_tokens ceiling.  24000 was measured
        # sufficient for a one-page datasheet image; 8000 truncated output.
        max_tokens = int(os.environ.get("GEMINI_MAX_TOKENS", "24000"))

        system_msg = (
            "You are a technical transcription assistant for an embedded-systems "
            "tool. Your only job is to convert what is written in the supplied "
            "image into clean, plain text that can be pasted into a requirement "
            "document.\n\n"
            "TRANSCRIPTION RULES:\n"
            "1. Reproduce all text exactly as written, including numbers, units, "
            "pin names, part numbers, addresses, and register names.\n"
            "2. Preserve structure: headings, bullet points, tables (render each "
            "table row as a comma-separated line), and numbered lists.\n"
            "3. If any portion is illegible or ambiguous, write "
            "[ILLEGIBLE: <description>] or [UNCERTAIN: <what you think it says>] "
            "in-line. Do NOT silently omit or guess silently.\n"
            "4. If the image contains a diagram or schematic rather than text, "
            "write a brief structural description in square brackets, e.g. "
            "[DIAGRAM: block diagram showing MCU connected to sensor via I2C].\n"
            "5. Output ONLY the transcribed content. No preamble, no commentary, "
            "no summary. Start directly with the first word on the image."
        )
        user_content = [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": "Transcribe all text in this image."},
        ]

        delay = float(os.environ.get("GEMINI_RETRY_DELAY", "10"))
        resp = None
        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,   # low temperature: we want a faithful read
                    max_tokens=max_tokens,
                )
                break
            except openai.APIStatusError as e:
                if e.status_code in (429, 503) and attempt < 2:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise ProviderError(
                    f"gemini vision API error {e.status_code}: {e.message}"
                ) from e
            except openai.APIConnectionError as e:
                raise ProviderError(f"gemini vision connection error: {e}") from e

        if resp is None:
            raise ProviderError("gemini vision: no response received")

        choice = resp.choices[0]
        text = (choice.message.content or "").strip()

        if getattr(choice, "finish_reason", None) == "length":
            # Output hit the token ceiling.  A truncated transcription is worse
            # than a refusal — it looks complete when it is not.  Raise so the
            # caller can surface this as a refusal rather than a partial read.
            raise ProviderError(
                f"image transcription truncated at the {max_tokens}-token ceiling "
                "(finish_reason=length): the image may be too large or too dense. "
                "Raise GEMINI_MAX_TOKENS or split the image into smaller sections."
            )

        if not text:
            raise ProviderError(
                "gemini vision returned an empty transcription — the image may be "
                "blank, unreadable, or in a format the model cannot process. "
                "Upload the requirement as a PDF or text file instead."
            )

        return text


PROVIDERS = {"nvidia": NVIDIAProvider, "groq": GroqProvider, "gemini": GeminiProvider}


def make_vision_provider() -> "GeminiProvider":
    """Return a vision-capable provider, or raise ProviderError if none is configured.

    Currently only GeminiProvider supports image transcription.  GEMINI_API_KEY
    must be set.  This function raises ProviderError rather than returning None
    so every call site gets an honest, specific refusal — never a silent fallback
    to a blank transcription or a fabricated read.
    """
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        raise ProviderError(
            "image transcription requires a vision-capable model (Gemini), but "
            "GEMINI_API_KEY is not set. Set it in the environment to enable image "
            "uploads, or paste the requirement text directly."
        )
    return GeminiProvider()


def make_provider() -> "LLMProvider":
    """Configuration-driven provider selection (V1.7.1 — no vendor hard-coded).

    EMBEDDPILOT_PROVIDER=nvidia|groq picks explicitly, so a deployment can use a
    different (licensed) provider than local development with NO code change — see
    the licensing note in the README. With no explicit setting, default to NVIDIA
    when its key is present (its window fits the both-maps job), else Groq."""
    choice = os.environ.get("EMBEDDPILOT_PROVIDER", "").strip().lower()
    if choice:
        if choice not in PROVIDERS:
            raise ProviderError(
                f"EMBEDDPILOT_PROVIDER='{choice}' is not a known provider "
                f"({', '.join(sorted(PROVIDERS))})"
            )
        return PROVIDERS[choice]()
    if os.environ.get("NVIDIA_API_KEY"):
        return NVIDIAProvider()
    return GroqProvider()


class MockProvider:
    """Deterministic provider for tests: pops canned responses in order.

    Pass `vision_response` to make this provider simulate vision capability.
    Leave it as None (the default) to simulate a provider that does not
    support vision — `transcribe_image` will then raise ProviderError, just
    as a real non-vision provider would.
    """

    def __init__(self, responses: list[dict],
                 vision_response: str | None = None):
        self.name = "mock"
        self.context_window = 1_000_000  # tests never hit the fit check
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []  # (system, user) per call
        self._vision_response = vision_response
        # has_vision mirrors GeminiProvider's attribute so tests can inspect it
        self.has_vision: bool = vision_response is not None
        self.vision_calls: list[tuple[bytes, str]] = []  # (image_bytes, mime)

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if not self._responses:
            raise ProviderError("mock provider exhausted")
        return self._responses.pop(0)

    def transcribe_image(self, image_bytes: bytes, mime_type: str) -> str:
        self.vision_calls.append((image_bytes, mime_type))
        if self._vision_response is None:
            raise ProviderError(
                "this mock provider was not configured with a vision_response — "
                "vision transcription is not available"
            )
        return self._vision_response


def _parse_json(text: str) -> dict:
    """Models occasionally wrap JSON in code fences despite json mode, and emit
    literal newlines/tabs inside string values (raw code in a "source_c" field).
    strict=False tolerates those unescaped control characters — standard
    json.loads rejects them and would fail every large-driver response."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError as e:
        raise ProviderError(f"provider returned non-JSON output: {e}") from e
