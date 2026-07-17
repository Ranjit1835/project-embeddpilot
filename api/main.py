"""FastAPI service: upload/ingest, review, generate, results, downloads.

Run:  uvicorn api.main:app --port 8000
The Next.js dev server proxies /api/* here.
"""

from __future__ import annotations

import io
import json
import os
import threading
import urllib.request
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from api.jobs import STORE, Job

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "build", "uploads")
MAX_UPLOAD = 50 * 1024 * 1024  # mirror the ingestion cap so the UI can say why

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
    register_map = payload.get("register_map")
    platform = payload.get("platform", "")
    if not register_map or not platform:
        raise HTTPException(422, "register_map and platform are required")

    job = STORE.create("generate")
    conventions = payload.get("conventions") or (
        "snake_case, C99, no dynamic allocation"  # proven default from CLI runs
    )
    threading.Thread(
        target=_run_generate,
        args=(job, register_map, platform,
              conventions, int(payload.get("max_retries", 3)),
              payload.get("edits", [])),
        daemon=True,
    ).start()
    return {"job_id": job.id}


def _run_generate(job: Job, register_map: dict, platform: str,
                  conventions: str, max_retries: int, edits: list):
    from generation.pipeline import generate_validated_driver
    from generation.provider import GroqProvider, ProviderError

    try:
        provider = GroqProvider()
    except ProviderError as e:
        job.finish(error=str(e))
        return
    try:
        result = generate_validated_driver(
            register_map, platform, provider, conventions=conventions,
            max_retries=max_retries, on_event=job.emit,
        )
        result["user_edits"] = edits  # provenance: review-screen corrections
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
