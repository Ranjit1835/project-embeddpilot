"""Tests for the image-to-text transcription path.

Requirements under test:
  1. Successful transcription: image bytes reach a vision provider, the
     transcription is returned with review_required=True and a clear warning.
  2. No-vision-provider refusal: when make_vision_provider raises (missing key
     or no vision-capable provider), the API returns 415 with an honest message.
  3. Failed-call refusal: when transcribe_image raises (network error, model
     error, truncated output), the API returns 422 with the specific reason.
  4. Transcribed text cannot reach spec analysis unconfirmed: the endpoint only
     returns the text for user review; it never calls analyze_requirement.

These tests must not reach the real network or a real key.  Every vision
provider call is monkeypatched.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import api.main as apimain  # noqa: E402
from generation.provider import MockProvider, ProviderError  # noqa: E402


# ---------------------------------------------------------------------------
# shared fixture: the standard mock for the text-path provider (unchanged)
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """Standard client fixture: make_provider returns a MockProvider so the
    rest of the API can operate without a real key."""
    def _mock():
        return MockProvider([])

    monkeypatch.setattr("generation.provider.make_provider", _mock)
    return TestClient(apimain.app)


# ---------------------------------------------------------------------------
# test 1: successful transcription
# ---------------------------------------------------------------------------

def test_image_transcription_returns_text_for_review(client, monkeypatch):
    """A vision-capable provider returns a transcription.

    The response must carry:
      - the transcribed text verbatim
      - review_required = True
      - a transcription_warning that includes the word LOSSY (or equivalent)
      - filename and chars
    The text must NOT have been fed into spec analysis (the spec pipeline is
    not invoked from this endpoint — the user reviews first).
    """
    expected_transcription = (
        "Read the BMP180 over I2C at address 0x77 on a Nucleo-F411RE board.\n"
        "Print temperature over UART at 9600 baud."
    )
    mock_vision = MockProvider([], vision_response=expected_transcription)

    monkeypatch.setattr(
        "generation.provider.make_vision_provider", lambda: mock_vision
    )

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # minimal PNG-like bytes
    r = client.post(
        "/api/v2/requirement-from-file",
        files={"file": ("requirement.png", fake_png, "image/png")},
    )

    assert r.status_code == 200, r.text
    body = r.json()

    # the transcribed text is returned verbatim
    assert body["text"] == expected_transcription

    # the user must review it before it goes anywhere
    assert body["review_required"] is True

    # the warning must be present and must label it as a machine/lossy read
    warning = body.get("transcription_warning", "")
    assert warning, "transcription_warning must be present in the response"
    warning_lower = warning.lower()
    assert "machine" in warning_lower or "lossy" in warning_lower, (
        f"warning must call out the lossy/machine nature: {warning!r}"
    )

    # chars count must match the text length
    assert body["chars"] == len(expected_transcription)

    # filename is echoed back
    assert body["filename"] == "requirement.png"

    # the vision provider was called exactly once with the image bytes
    assert len(mock_vision.vision_calls) == 1
    received_bytes, received_mime = mock_vision.vision_calls[0]
    assert received_bytes == fake_png
    assert "image" in received_mime


def test_transcription_works_for_all_supported_image_extensions(client,
                                                                  monkeypatch):
    """Every extension in REQUIREMENT_IMAGE_EXT must reach the vision path."""
    extensions = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]
    for ext in extensions:
        mock_vision = MockProvider([], vision_response="some text")
        monkeypatch.setattr(
            "generation.provider.make_vision_provider", lambda m=mock_vision: m
        )
        r = client.post(
            "/api/v2/requirement-from-file",
            files={"file": (f"req{ext}", b"\x00" * 8, "image/png")},
        )
        assert r.status_code == 200, (ext, r.text)
        assert r.json()["review_required"] is True, ext


# ---------------------------------------------------------------------------
# test 2: no-vision-provider refusal
# ---------------------------------------------------------------------------

def test_no_vision_provider_returns_415_with_honest_message(client, monkeypatch):
    """When make_vision_provider raises (missing key, no provider), the API
    must return 415 and name the gap and the alternative.

    It must NEVER return 200 with blank text, a guessed transcription, or any
    content the user could mistake for a real read.
    """
    def _no_vision():
        raise ProviderError(
            "GEMINI_API_KEY is not set — set it to enable image transcription"
        )

    monkeypatch.setattr("generation.provider.make_vision_provider", _no_vision)

    r = client.post(
        "/api/v2/requirement-from-file",
        files={"file": ("spec.png", b"\x89PNG\r\n", "image/png")},
    )

    assert r.status_code == 415, r.text
    body_text = r.text
    # must name that a vision-capable model is needed
    assert "vision-capable" in body_text or "vision" in body_text.lower(), body_text
    # must offer the text/PDF alternative so the user knows what to do
    assert "PDF" in body_text or "text" in body_text.lower(), body_text
    # must NOT contain any transcribed content — this is a refusal, not a result
    assert "review_required" not in body_text


def test_no_vision_provider_never_returns_blank_transcription(client, monkeypatch):
    """A 415 refusal is the correct outcome.  A 200 with empty text is not."""
    monkeypatch.setattr(
        "generation.provider.make_vision_provider",
        lambda: (_ for _ in ()).throw(
            ProviderError("no vision provider")
        ),
    )
    r = client.post(
        "/api/v2/requirement-from-file",
        files={"file": ("spec.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    # must not be a 200 success
    assert r.status_code != 200, (
        "a missing vision provider must produce a refusal, not a 200 with empty text"
    )


# ---------------------------------------------------------------------------
# test 3: failed-call refusal
# ---------------------------------------------------------------------------

def test_transcription_call_failure_returns_422_with_reason(client, monkeypatch):
    """When transcribe_image raises (network error, model error, truncated
    output), the API must return 422 with the specific reason.

    It must NEVER return 200 with empty or partial text presented as a
    complete transcription.
    """
    class _FailingVisionProvider:
        name = "failing-mock"
        has_vision = True

        def transcribe_image(self, image_bytes: bytes, mime_type: str) -> str:
            raise ProviderError(
                "image transcription truncated at the 24000-token ceiling "
                "(finish_reason=length): the image may be too large or too dense"
            )

    monkeypatch.setattr(
        "generation.provider.make_vision_provider", _FailingVisionProvider
    )

    r = client.post(
        "/api/v2/requirement-from-file",
        files={"file": ("spec.png", b"\x89PNG\r\n", "image/png")},
    )

    assert r.status_code == 422, r.text
    body_text = r.text
    # the response must contain something from the original error message, not
    # just a generic "something went wrong"
    assert "truncat" in body_text.lower() or "too large" in body_text.lower() or \
           "could not" in body_text.lower(), body_text
    # must offer the PDF/text alternative
    assert "PDF" in body_text or "text" in body_text.lower(), body_text


def test_transcription_network_error_returns_422(client, monkeypatch):
    """Connection errors also produce a 422 refusal, not a blank 200."""
    class _NetworkFailVisionProvider:
        name = "netfail-mock"
        has_vision = True

        def transcribe_image(self, image_bytes: bytes, mime_type: str) -> str:
            raise ProviderError("gemini vision connection error: [Errno 111] refused")

    monkeypatch.setattr(
        "generation.provider.make_vision_provider", _NetworkFailVisionProvider
    )

    r = client.post(
        "/api/v2/requirement-from-file",
        files={"file": ("spec.png", b"\x89PNG\r\n", "image/png")},
    )

    assert r.status_code == 422, r.text
    assert r.status_code != 200, (
        "a network failure must produce a 422 refusal, not a 200 with empty text"
    )


# ---------------------------------------------------------------------------
# test 4: transcribed text cannot reach spec analysis unconfirmed
# ---------------------------------------------------------------------------

def test_image_endpoint_never_calls_analyze_requirement(client, monkeypatch):
    """The /requirement-from-file endpoint must only return text for review.
    It must never call analyze_requirement or spec.extract directly.

    This is the architectural guarantee: user-confirmed text flows into the
    normal pipeline through a separate /analyze call.  The image endpoint is
    a transcription step only.
    """
    analyze_called = {"count": 0}

    def _spy_analyze(*args, **kwargs):
        analyze_called["count"] += 1
        raise AssertionError("analyze_requirement must not be called from the "
                             "image transcription endpoint")

    # patch at both possible import paths
    monkeypatch.setattr("generation.spec.analyze_requirement", _spy_analyze,
                        raising=False)
    monkeypatch.setattr("generation.spec.extract", _spy_analyze, raising=False)

    mock_vision = MockProvider([], vision_response="BMP180 on I2C at 0x77")
    monkeypatch.setattr(
        "generation.provider.make_vision_provider", lambda: mock_vision
    )

    r = client.post(
        "/api/v2/requirement-from-file",
        files={"file": ("req.png", b"\x89PNG\r\n" + b"\x00" * 32, "image/png")},
    )

    assert r.status_code == 200, r.text
    assert analyze_called["count"] == 0, (
        "analyze_requirement was called from the image endpoint — the "
        "transcription must be returned for user review first"
    )


def test_transcribed_text_not_in_any_spec_pipeline_call(client, monkeypatch):
    """The text returned by the transcription endpoint is for user review.
    A follow-up /analyze call is where it enters the pipeline — and only
    after the user has seen and confirmed it.

    Verify that the image endpoint response shape is identical to the PDF
    path shape (same keys), so the UI can treat both identically without
    any special-casing that might bypass the review step.
    """
    transcription = "Read BMP180 via I2C"
    mock_vision = MockProvider([], vision_response=transcription)
    monkeypatch.setattr(
        "generation.provider.make_vision_provider", lambda: mock_vision
    )

    r = client.post(
        "/api/v2/requirement-from-file",
        files={"file": ("req.png", b"\x89PNG\r\n" + b"\x00" * 32, "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # must carry all the same keys the PDF path returns (plus transcription_warning)
    for key in ("filename", "text", "pages", "chars", "review_required"):
        assert key in body, f"key {key!r} missing from image transcription response"

    # image path adds the warning key; PDF path does not — this is fine, the
    # UI can display it when present
    assert "transcription_warning" in body

    # the text in the body is the transcription — nothing else
    assert body["text"] == transcription


# ---------------------------------------------------------------------------
# test 5: provider capability flag consistency
# ---------------------------------------------------------------------------

def test_gemini_provider_has_vision_flag(monkeypatch):
    """GeminiProvider.has_vision must be True."""
    from generation.provider import GeminiProvider

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    p = GeminiProvider.__new__(GeminiProvider)  # bypass __init__ network setup
    # has_vision is a class attribute, so we can check it without instantiation
    assert GeminiProvider.has_vision is True


def test_groq_provider_has_no_vision_flag():
    """GroqProvider.has_vision must be False."""
    from generation.provider import GroqProvider

    assert GroqProvider.has_vision is False


def test_nvidia_provider_has_no_vision_flag():
    """NVIDIAProvider.has_vision must be False."""
    from generation.provider import NVIDIAProvider

    assert NVIDIAProvider.has_vision is False


def test_mock_provider_with_vision_response_reports_has_vision():
    """MockProvider with vision_response set must report has_vision=True."""
    mock = MockProvider([], vision_response="some text")
    assert mock.has_vision is True
    assert mock.transcribe_image(b"\x00", "image/png") == "some text"


def test_mock_provider_without_vision_response_raises():
    """MockProvider with no vision_response must raise ProviderError on
    transcribe_image — matching the behaviour of non-vision real providers."""
    mock = MockProvider([])
    assert mock.has_vision is False
    with pytest.raises(ProviderError):
        mock.transcribe_image(b"\x00", "image/png")


# ---------------------------------------------------------------------------
# test 6: make_vision_provider refuses when no key is set
# ---------------------------------------------------------------------------

def test_make_vision_provider_raises_without_key(monkeypatch):
    """make_vision_provider must raise ProviderError when GEMINI_API_KEY and
    GOOGLE_API_KEY are both absent — never return a provider that will silently
    fail later."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    from generation.provider import make_vision_provider

    with pytest.raises(ProviderError) as exc_info:
        make_vision_provider()

    msg = str(exc_info.value)
    assert "GEMINI_API_KEY" in msg or "vision" in msg.lower(), (
        f"error message should explain the gap: {msg!r}"
    )
