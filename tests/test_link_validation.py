"""V1.6 Priority 4: datasheet URLs are validated before ingestion.

Reachability, content-type, and size are checked; each failure names the
specific problem and never falls back to a partial/empty extraction.
"""

import email.message
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import UrlValidationError, preflight_url


class _Resp:
    """Minimal stand-in for the urlopen context-manager response."""

    def __init__(self, ctype="application/pdf", clen=None, status=200):
        self.status = status
        self.headers = email.message.Message()
        if ctype is not None:
            self.headers["Content-Type"] = ctype
        if clen is not None:
            self.headers["Content-Length"] = str(clen)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, resp=None, exc=None):
    def fake_urlopen(req, timeout=0):
        if exc is not None:
            raise exc
        return resp
    monkeypatch.setattr("api.main.urllib.request.urlopen", fake_urlopen)


def test_ok_pdf_passes(monkeypatch):
    _patch(monkeypatch, _Resp("application/pdf", clen=1_000_000))
    preflight_url("https://vendor.com/datasheet.pdf")  # no raise


def test_octet_stream_with_pdf_extension_passes(monkeypatch):
    # servers often mislabel PDFs; a .pdf path is accepted
    _patch(monkeypatch, _Resp("application/octet-stream"))
    preflight_url("https://vendor.com/files/ds.pdf")


def test_unreachable_is_specific(monkeypatch):
    _patch(monkeypatch, exc=urllib.error.URLError("name resolution failed"))
    with pytest.raises(UrlValidationError) as e:
        preflight_url("https://nope.invalid/x.pdf")
    assert "unreachable" in str(e.value)


def test_http_error_is_specific(monkeypatch):
    _patch(monkeypatch, exc=urllib.error.HTTPError(
        "u", 404, "Not Found", hdrs=None, fp=None))
    with pytest.raises(UrlValidationError) as e:
        preflight_url("https://vendor.com/missing.pdf")
    assert "404" in str(e.value)


def test_wrong_content_type_is_rejected(monkeypatch):
    # an HTML page (no document extension) is not a datasheet
    _patch(monkeypatch, _Resp("text/html"))
    with pytest.raises(UrlValidationError) as e:
        preflight_url("https://vendor.com/product-page")
    assert "not a PDF/DOCX" in str(e.value)


def test_oversize_is_rejected(monkeypatch):
    _patch(monkeypatch, _Resp("application/pdf", clen=60 * 1024 * 1024))
    with pytest.raises(UrlValidationError) as e:
        preflight_url("https://vendor.com/huge.pdf")
    assert "50MB limit" in str(e.value)


def test_non_http_scheme_is_rejected(monkeypatch):
    with pytest.raises(UrlValidationError) as e:
        preflight_url("ftp://vendor.com/x.pdf")
    assert "http" in str(e.value)
