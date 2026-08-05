"""Worker -> judge -> bounded retry -> graceful fallback (WS2 build order 5).

The validator runs as a SUBPROCESS (`python -m validator ...`) with no shared
state; its inputs are the files this pipeline wrote to disk plus the register
map JSON. Retries feed back only the validator's failure artifacts. After
max_retries failures the last attempt is returned clearly marked unvalidated,
with the failures and the register map attached (never presented as validated).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Callable

from generation.inputs import InputProvenanceError, assert_input_provenance
from generation.provider import LLMProvider, ProviderError
from generation.router import RouteDecision, route
from generation.worker import generate_driver

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_RETRIES = 3  # retries after the first attempt


def run_validator_subprocess(workdir: str, map_path: str, platform: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "validator", workdir, "--map", map_path,
         "--platform", platform],
        capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=600,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "status": "failed",
            "checks": {},
            "failures": [{"check": "validator", "file": "", "line": None,
                          "message": f"validator crashed: {proc.stderr[:500]}"}],
            "unverified_fields": [], "notes": [],
        }


def generate_validated_driver(
    register_map: dict,
    platform: str,
    provider: LLMProvider,
    conventions: str = "",
    workdir_root: str | None = None,
    max_retries: int = MAX_RETRIES,
    validate_fn: Callable[[str, str, str], dict] | None = None,
    on_event: Callable[[dict], None] | None = None,
) -> dict:
    """Full LLM-path pipeline. Returns a result payload with provenance:
    decision, per-attempt validation reports, and a status that is one of
    validated / validated-with-unverified-fields / unvalidated.

    `on_event`, if given, receives progress artifacts for UIs:
    {type: route|attempt_start|attempt_report, ...}. Events carry only
    router decisions and validator REPORTS (post-judgment artifacts) —
    never worker reasoning."""
    emit = on_event or (lambda e: None)
    # Priority 1: refuse to route or generate on missing/unconfirmed/invented
    # inputs. This runs before the router so a wrong interface never even frames
    # a route decision.
    assert_input_provenance(register_map, platform)
    decision: RouteDecision = route(register_map, platform)
    emit({"type": "route", "decision": decision.to_json()})
    if decision.path == "template":
        return {
            "status": "template-path",
            "decision": decision.to_json(),
            "message": "covered by the V1 deterministic template engine — run embeddpilot.py",
        }

    validate = validate_fn or run_validator_subprocess
    workdir_root = workdir_root or os.path.join(PROJECT_ROOT, "build", "llm_gen")
    chip = register_map.get("chip", "device").lower().replace(" ", "_")

    feedback: str | None = None
    reports: list[dict] = []
    files: dict[str, str] = {}
    for attempt in range(1, max_retries + 2):  # first attempt + max_retries
        emit({"type": "attempt_start", "attempt": attempt})
        try:
            result = generate_driver(
                provider, register_map, decision, platform, conventions, feedback
            )
        except ProviderError as e:
            report = {"status": "failed", "failures": [
                {"check": "worker", "file": "", "line": None, "message": str(e)}
            ], "checks": {}, "unverified_fields": [], "notes": []}
            reports.append(report)
            emit({"type": "attempt_report", "attempt": attempt, "report": report})
            feedback = f"your previous response was invalid: {e}"
            continue

        files = result.files
        workdir = os.path.join(workdir_root, chip, f"attempt_{attempt}")
        os.makedirs(workdir, exist_ok=True)
        for fname, content in files.items():
            with open(os.path.join(workdir, fname), "w", encoding="utf-8") as f:
                f.write(content if content.endswith("\n") else content + "\n")
        map_path = os.path.join(workdir, "register-map.json")
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(register_map, f, indent=1)

        report = validate(workdir, map_path, platform)
        reports.append(report)
        emit({"type": "attempt_report", "attempt": attempt, "report": report})

        if report.get("status") in ("validated", "validated-with-unverified-fields"):
            return {
                "status": report["status"],
                "decision": decision.to_json(),
                "files": files,
                "workdir": workdir,
                "attempts": attempt,
                "reports": reports,
                "unverified_fields": report.get("unverified_fields", []),
                "provider": provider.name,
            }
        feedback = format_failures(report)

    # graceful fallback: never present unvalidated code as validated
    return {
        "status": "unvalidated",
        "decision": decision.to_json(),
        "files": files,
        "attempts": max_retries + 1,
        "reports": reports,
        "validation_failures": reports[-1].get("failures", []) if reports else [],
        "register_map": register_map,
        "provider": provider.name,
        "message": (
            "all validation attempts failed — code is UNVALIDATED; the exact "
            "failures and the extracted register map are attached so you can "
            "proceed manually"
        ),
    }


def format_failures(report: dict) -> str:
    lines = []
    for f in report.get("failures", []):
        loc = f"{f['file']}:{f['line']}" if f.get("line") else f.get("file", "")
        lines.append(f"- [{f['check']}] {loc}: {f['message']}")
    return "\n".join(lines) or "validation failed with no recorded failures"
