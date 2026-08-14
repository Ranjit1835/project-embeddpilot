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

from generation.inputs import (
    InputProvenanceError,
    assert_chip_consistency,
    assert_input_provenance,
)
from generation.provider import ContextWindowError, LLMProvider, ProviderError
from generation.router import RouteDecision, route
from generation.worker import generate_driver

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_RETRIES = 3  # retries after the first attempt


def run_validator_subprocess(
    workdir: str, map_path: str, platform: str, target: str = "bare-metal"
) -> dict:
    cmd = [sys.executable, "-m", "validator", workdir, "--map", map_path,
           "--platform", platform]
    if target == "arduino":
        # V1.8: the Arduino target is compiled with arduino-cli against multiple
        # cores; the MCU map is never used on this target.
        cmd += ["--target", "arduino"]
    else:
        # V1.7: if an MCU map was written alongside the sources, cross-check the
        # generated RCC/GPIO/peripheral bring-up against it too.
        mcu_map_path = os.path.join(workdir, "mcu-map.json")
        if os.path.exists(mcu_map_path):
            cmd += ["--mcu-map", mcu_map_path]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=600,
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
    mcu_map: dict | None = None,
    target: str = "bare-metal",
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

    # Default validator threads the output target through; a custom validate_fn
    # (tests) keeps the simple (workdir, map, platform) signature.
    validate = validate_fn or (
        lambda wd, mp, pl: run_validator_subprocess(wd, mp, pl, target)
    )
    workdir_root = workdir_root or os.path.join(PROJECT_ROOT, "build", "llm_gen")
    chip = register_map.get("chip", "device").lower().replace(" ", "_")

    feedback: str | None = None
    reports: list[dict] = []
    files: dict[str, str] = {}
    prior_files: dict[str, str] | None = None
    for attempt in range(1, max_retries + 2):  # first attempt + max_retries
        emit({"type": "attempt_start", "attempt": attempt})
        try:
            result = generate_driver(
                provider, register_map, decision, platform, conventions, feedback,
                mcu_map, prior_files, target,
            )
        except ContextWindowError as e:
            # The job does not fit this provider's window. Retrying cannot help
            # (the size is fixed), so fail immediately and loudly — never truncate
            # the maps or silently degrade (V1.7.1 Task 1).
            report = {"status": "failed", "failures": [
                {"check": "context_window", "file": "", "line": None, "message": str(e)}
            ], "checks": {}, "unverified_fields": [], "notes": []}
            emit({"type": "attempt_report", "attempt": attempt, "report": report})
            return {
                "status": "provider-window-exceeded",
                "decision": decision.to_json(),
                "reports": [report],
                "provider": provider.name,
                "message": str(e),
            }
        except ProviderError as e:
            report = {"status": "failed", "failures": [
                {"check": "worker", "file": "", "line": None, "message": str(e)}
            ], "checks": {}, "unverified_fields": [], "notes": []}
            reports.append(report)
            emit({"type": "attempt_report", "attempt": attempt, "report": report})
            feedback = f"your previous response was invalid: {e}"
            continue

        files = result.files
        prior_files = files  # feed this attempt's code into the next retry
        # V1.8 B1: the shipped artifact identity must agree with the map. Compare
        # against detection only when the chip was NOT user-confirmed (a user
        # override legitimately supersedes stale detection).
        _chip_prov = (register_map.get("provenance") or {}).get("chip")
        _detected_chip = None if _chip_prov == "user" else (
            (register_map.get("detected") or {}).get("chip") or {}
        ).get("value")
        assert_chip_consistency(
            register_map.get("chip", ""), _detected_chip, list(files.keys())
        )
        workdir = os.path.join(workdir_root, chip, f"attempt_{attempt}")
        os.makedirs(workdir, exist_ok=True)
        for fname, content in files.items():
            fpath = os.path.join(workdir, fname)
            # the Arduino target writes a nested library folder (src/, examples/)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content if content.endswith("\n") else content + "\n")
        map_path = os.path.join(workdir, "register-map.json")
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(register_map, f, indent=1)
        if mcu_map and target != "arduino":  # V1.7 MCU cross-check (bare-metal only)
            with open(os.path.join(workdir, "mcu-map.json"), "w", encoding="utf-8") as f:
                json.dump(mcu_map, f, indent=1)

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
