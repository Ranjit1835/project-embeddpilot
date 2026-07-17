"""Package the real captured pipeline runs into ui/lib/demo-data.json.

The Vercel deployment has no Python backend (the validator needs a real
cross-compiler), so the hosted case study replays these recorded runs —
actual maps, actual generated files, actual validation reports. Nothing is
fabricated: reports are produced by re-running the validator on the artifacts.
"""

import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from generation.router import route  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_CLUSTER_WINDOW = 30 * 60  # attempt dirs within 30min of newest = one run

SHAPES = [
    ("bme280", "artifacts/bme280-extracted-map.json", "build/llm_gen/bme280",
     "esp32", "BME280 environmental sensor (I2C bus device)"),
    ("w25q64", "artifacts/w25q64-extracted-map.json", "build/llm_gen/w25q64jv",
     "esp32", "W25Q64JV SPI flash (command device)"),
    ("esp32-i2c", "artifacts/esp32-i2c-extracted-map.json", "build/llm_gen/esp32",
     "esp32", "ESP32 I2C controller (memory-mapped, empty fields)"),
]


def validate(workdir: str, map_path: str) -> dict:
    p = subprocess.run(
        [sys.executable, "-m", "validator", workdir, "--map", map_path,
         "--platform", "esp32"],
        capture_output=True, text=True, cwd=ROOT, timeout=600,
    )
    return json.loads(p.stdout)


def build_run(map_rel: str, gen_dir: str, platform: str) -> dict:
    with open(os.path.join(ROOT, map_rel), encoding="utf-8") as f:
        register_map = json.load(f)

    dirs = sorted(
        glob.glob(os.path.join(ROOT, gen_dir, "attempt_*")),
        key=lambda d: int(d.rsplit("_", 1)[1]),
    )
    # each run overwrites attempt_1..N in order, so the dir with the newest
    # GENERATED SOURCE files is the last attempt of the most recent run;
    # higher-numbered dirs are stale leftovers from older (failed) runs.
    # (directory mtimes are unusable: the validator's compile step creates and
    # deletes .o files, touching the dir)
    def source_mtime(d: str) -> float:
        sources = glob.glob(os.path.join(d, "*.c")) + glob.glob(os.path.join(d, "*.h"))
        return max(os.path.getmtime(p) for p in sources)

    last = max(dirs, key=source_mtime)
    n = int(last.rsplit("_", 1)[1])
    dirs = dirs[:n]

    reports = []
    files = {}
    for d in dirs:
        report = validate(d, os.path.join(d, "register-map.json"))
        reports.append(report)
        if report["status"] != "failed":
            files = {
                os.path.basename(p): open(p, encoding="utf-8").read()
                for p in sorted(glob.glob(os.path.join(d, "*.c"))
                                + glob.glob(os.path.join(d, "*.h")))
            }
    final = reports[-1]
    decision = route(register_map, platform, log=False)
    return {
        "register_map": register_map,
        "result": {
            "status": final["status"] if final["status"] != "failed" else "unvalidated",
            "decision": decision.to_json(),
            "files": files,
            "attempts": len(dirs),
            "reports": reports,
            "unverified_fields": final.get("unverified_fields", []),
            "provider": "groq/openai/gpt-oss-120b (recorded 2026-07-17)",
        },
    }


def main() -> None:
    out = {"samples": [], "runs": {}}
    for sid, map_rel, gen_dir, platform, label in SHAPES:
        print(f"packaging {sid} ...")
        out["samples"].append({"id": sid, "platform": platform, "label": label})
        out["runs"][sid] = {"platform": platform, **build_run(map_rel, gen_dir, platform)}
        r = out["runs"][sid]["result"]
        print(f"  {r['status']} in {r['attempts']} attempt(s), "
              f"{len(r['files'])} files")
    dest = os.path.join(ROOT, "ui", "lib", "demo-data.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"wrote {dest} ({os.path.getsize(dest) // 1024} KB) at {time.strftime('%H:%M')}")


if __name__ == "__main__":
    main()
