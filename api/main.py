"""FastAPI service: upload/ingest, review, generate, results, downloads.

Run:  uvicorn api.main:app --port 8000
The Next.js dev server proxies /api/* here.
"""

from __future__ import annotations

import io
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from api.jobs import STORE, Job

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "build", "uploads")
MAX_UPLOAD = 50 * 1024 * 1024  # mirror the ingestion cap so the UI can say why

# content types we accept for a datasheet link. Servers often mislabel PDFs as
# octet-stream, so a matching file extension is also accepted; only a clearly
# non-document type (html/text/json) with no document extension is rejected.
DOC_CONTENT_TYPES = ("application/pdf", "application/vnd.openxmlformats-"
                     "officedocument.wordprocessingml.document",
                     "application/octet-stream", "binary/octet-stream")


class UrlValidationError(Exception):
    """A datasheet URL failed a preflight check; message names the problem."""


def preflight_url(url: str, timeout: int = 20) -> None:
    """Validate a datasheet URL BEFORE ingestion (Priority 4): reachable, is a
    PDF/DOCX, within the 50MB cap. Any failure raises UrlValidationError with a
    specific message — never a silent fallback to a partial/empty extraction."""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlValidationError(
            f"URL must be http(s), got '{scheme or 'no scheme'}'"
        )
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = resp.headers
            status = resp.status
    except urllib.error.HTTPError as e:
        # some servers reject HEAD; fall back to a ranged GET before giving up
        if e.code in (403, 405, 501):
            headers, status = _probe_get(url, timeout)
        else:
            raise UrlValidationError(f"URL unreachable: HTTP {e.code} {e.reason}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UrlValidationError(f"URL unreachable: {getattr(e, 'reason', e)}")

    if status and status >= 400:
        raise UrlValidationError(f"URL unreachable: HTTP {status}")

    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    path_lower = urllib.parse.urlparse(url).path.lower()
    looks_like_doc = path_lower.endswith((".pdf", ".docx"))
    if ctype and ctype not in DOC_CONTENT_TYPES and not looks_like_doc:
        raise UrlValidationError(
            f"URL is not a PDF/DOCX (server reports content-type '{ctype}')"
        )

    clen = headers.get("Content-Length")
    if clen and clen.isdigit() and int(clen) > MAX_UPLOAD:
        raise UrlValidationError(
            f"URL file is {int(clen) / 1024 / 1024:.1f}MB, over the 50MB limit"
        )


def _probe_get(url: str, timeout: int):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.headers, resp.status

app = FastAPI(title="EmbeddPilot API", version="1.5")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"],
)


# --- ingestion --------------------------------------------------------------------

@app.post("/api/ingest")
async def start_ingest(
    file: UploadFile | None = File(default=None),
    url: str = Form(default=""),
    chip: str = Form(default=""),
    peripheral: str = Form(default=""),
    pages: str = Form(default=""),
):
    if file is None and not url:
        raise HTTPException(422, "provide a datasheet file or a URL")
    # Priority 4: validate a URL before we start a job, so a broken/oversize/
    # non-document link fails fast with a specific reason instead of degrading
    # into a partial extraction. File uploads skip this (already local bytes).
    if file is None and url:
        try:
            preflight_url(url)
        except UrlValidationError as e:
            raise HTTPException(422, str(e))
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    job = STORE.create("ingest")
    if file is not None:
        data = await file.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "file exceeds the 50MB limit")
        path = os.path.join(UPLOAD_DIR, f"{job.id}_{os.path.basename(file.filename)}")
        with open(path, "wb") as f:
            f.write(data)
    else:
        path = os.path.join(UPLOAD_DIR, f"{job.id}_download.pdf")

    page_range = None
    if pages.strip():
        lo, _, hi = pages.partition("-")
        try:
            page_range = (int(lo), int(hi or lo))
        except ValueError:
            raise HTTPException(422, f"bad page range '{pages}' — use e.g. 401-429")

    threading.Thread(
        target=_run_ingest, args=(job, path, url, chip, peripheral, page_range),
        daemon=True,
    ).start()
    return {"job_id": job.id}


def _run_ingest(job: Job, path: str, url: str, chip: str, peripheral: str, page_range):
    from ingestion.loader import IngestionError
    from ingestion.pipeline import ingest_datasheet

    try:
        if url:
            job.emit({"type": "stage", "stage": "downloading"})
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise IngestionError("downloaded file exceeds the 50MB limit")
            with open(path, "wb") as f:
                f.write(data)
        job.emit({"type": "stage", "stage": "uploaded"})
        register_map = ingest_datasheet(
            path, peripheral=peripheral, chip=chip, page_range=page_range,
            progress=lambda stage: job.emit({"type": "stage", "stage": stage}),
        )
        job.finish(result={"register_map": register_map})
    except IngestionError as e:
        job.finish(error=str(e))
    except Exception as e:  # surfaced to the UI, never swallowed
        job.finish(error=f"ingestion crashed: {e}")


# --- generation -------------------------------------------------------------------

@app.post("/api/generate")
async def start_generate(payload: dict):
    from generation.inputs import (
        InputProvenanceError,
        InterfaceMismatchError,
        UnsupportedInterfaceError,
        assert_input_provenance,
    )

    register_map = payload.get("register_map")
    platform = payload.get("platform", "")
    if not register_map:
        raise HTTPException(422, "register_map is required")
    # Priority 1 + V1.8 B1/B2: block missing/unconfirmed/invented inputs, an
    # unsupported bus (TMP107 UART/SMAART Wire), or an interface that contradicts
    # the document — each with a specific, field-naming error. Never let a silent
    # default or a wrong-interface driver reach generation.
    try:
        assert_input_provenance(register_map, platform)
    except (InputProvenanceError, UnsupportedInterfaceError,
            InterfaceMismatchError) as e:
        raise HTTPException(422, str(e))

    job = STORE.create("generate")
    conventions = payload.get("conventions") or (
        "snake_case, C99, no dynamic allocation"  # proven default from CLI runs
    )
    # V1.7 two-document flow: an optional MCU map turns this into a complete
    # driver (clock/GPIO/init/error) cross-checked against the MCU.
    mcu_map = payload.get("mcu_map")
    # V1.8 Part A: output target — "bare-metal" (register-level C driver, the
    # default) or "arduino" (importable C++ library compiled across cores).
    target = payload.get("target", "bare-metal")
    if target not in ("bare-metal", "arduino"):
        raise HTTPException(422, f"unknown target '{target}'")
    threading.Thread(
        target=_run_generate,
        args=(job, register_map, platform,
              conventions, int(payload.get("max_retries", 3)),
              payload.get("edits", []), mcu_map, target),
        daemon=True,
    ).start()
    return {"job_id": job.id}


def _run_generate(job: Job, register_map: dict, platform: str,
                  conventions: str, max_retries: int, edits: list,
                  mcu_map: dict | None = None, target: str = "bare-metal"):
    from generation.pipeline import generate_validated_driver
    from generation.provider import ProviderError, make_provider

    try:
        provider = make_provider()  # config-driven (EMBEDDPILOT_PROVIDER) — V1.7.1
    except ProviderError as e:
        job.finish(error=str(e))
        return
    try:
        result = generate_validated_driver(
            register_map, platform, provider, conventions=conventions,
            max_retries=max_retries, on_event=job.emit, mcu_map=mcu_map,
            target=target,
        )
        result["user_edits"] = edits  # provenance: review-screen corrections
        result["target"] = target
        job.finish(result=result)
    except Exception as e:
        job.finish(error=f"generation crashed: {e}")


# --- job introspection ---------------------------------------------------------------

@app.get("/api/jobs/{job_id}")
async def job_snapshot(job_id: str):
    job = STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    return {"id": job.id, "kind": job.kind, "status": job.status,
            "events": job.events, "result": job.result, "error": job.error}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    return StreamingResponse(job.subscribe(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs/{job_id}/download")
async def job_download(job_id: str):
    job = STORE.get(job_id)
    if job is None or job.result is None:
        raise HTTPException(404, "no result to download")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, content in (job.result.get("files") or {}).items():
            z.writestr(fname, content)
        if job.result.get("register_map"):  # fallback case: map for manual work
            z.writestr("register-map.json",
                       json.dumps(job.result["register_map"], indent=1))
        z.writestr("provenance.json", json.dumps(
            {k: job.result.get(k) for k in
             ("status", "decision", "attempts", "reports", "provider", "user_edits")},
            indent=1))
    chip = "driver"
    return Response(
        buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="embeddpilot_{chip}_{job_id}.zip"'},
    )


# --- demo samples (live-proven maps, so the UI can run without a PDF upload) -------

SAMPLES = {
    "bme280": ("artifacts/bme280-extracted-map.json", "esp32", "BME280 environmental sensor (I2C bus device)"),
    "w25q64": ("artifacts/w25q64-extracted-map.json", "esp32", "W25Q64JV SPI flash (command device)"),
    "esp32-i2c": ("artifacts/esp32-i2c-extracted-map.json", "esp32", "ESP32 I2C controller (memory-mapped, empty fields)"),
}


@app.get("/api/samples")
async def list_samples():
    return [{"id": k, "platform": p, "label": lbl} for k, (_, p, lbl) in SAMPLES.items()]


@app.get("/api/samples/{sample_id}")
async def get_sample(sample_id: str):
    entry = SAMPLES.get(sample_id)
    if entry is None:
        raise HTTPException(404, "no such sample")
    path, platform, label = entry
    with open(os.path.join(PROJECT_ROOT, path), encoding="utf-8") as f:
        return {"register_map": json.load(f), "platform": platform, "label": label}


# --- MCU maps (V1.7 two-document flow) --------------------------------------------
# The cached MCU maps are the supported-MCU library. The UI lists them as the
# optional second document; picking one turns generation into a complete driver.

MCU_CACHE_DIR = os.path.join(PROJECT_ROOT, "artifacts", "mcu_cache")


def _mcu_map_path(map_id: str) -> str:
    import re

    if not re.fullmatch(r"[A-Za-z0-9_]+", map_id or ""):  # no path traversal
        raise HTTPException(404, "no such MCU map")
    return os.path.join(MCU_CACHE_DIR, map_id + ".json")


@app.get("/api/mcu-maps")
async def list_mcu_maps():
    out = []
    if os.path.isdir(MCU_CACHE_DIR):
        for fn in sorted(os.listdir(MCU_CACHE_DIR)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(MCU_CACHE_DIR, fn), encoding="utf-8") as f:
                m = json.load(f)
            out.append({
                "id": fn[:-5],
                "mcu_family": m.get("mcu_family"),
                "variant": m.get("variant"),
                "peripheral": m.get("peripheral"),
                "rm_revision": m.get("rm_revision"),
                "label": f"{m.get('mcu_family')} {m.get('variant') or ''} "
                         f"{m.get('peripheral')}".strip(),
            })
    return out


@app.get("/api/mcu-maps/{map_id}")
async def get_mcu_map(map_id: str):
    path = _mcu_map_path(map_id)
    if not os.path.isfile(path):
        raise HTTPException(404, "no such MCU map")
    with open(path, encoding="utf-8") as f:
        return json.load(f)
