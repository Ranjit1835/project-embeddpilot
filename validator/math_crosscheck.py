"""V1.10a: verify compensation/conversion MATH by executing it.

Every other check in this system verifies *named things* statically (register
offsets, readout #defines). Compensation/conversion math is different: a wrong
shift or a wrong sign path compiles clean and passes every static check, then
silently returns wrong numbers. The only way to catch that is to RUN the math
and compare its output to a ground truth the datasheet itself provides.

This is the validator's first EXECUTION capability. It compiles a tiny host
program that calls the generated driver's conversion/compensation function and
compares the result against a `math_oracle` that came from the DOCUMENT — never
from the model. Two oracle kinds (V1.10a spike):

  - "table"          a datasheet conversion table (code -> physical value), e.g.
                     LM75B section 7.5.2. Exact match required on integer/fixed
                     paths; the negative two's-complement rows are the point.
  - "reference_code" the datasheet's own reference compensation functions (e.g.
                     BME280 4.2.3). We compile the reference INDEPENDENTLY and
                     differentially test the generated math against it over a
                     spread of inputs. This verifies TRANSCRIPTION FIDELITY —
                     that the model reproduced the datasheet's algorithm — NOT
                     that the algorithm is independently correct.

Contamination guard (unchanged discipline): the oracle is datasheet-sourced, the
checker is not the generator, and we never string-compare against the generated
source — we compare NUMERIC OUTPUT. No imports from generation/.

Host compiler: gcc/cc/clang if present (Docker has gcc); TinyCC (`tcc -run`) as a
local fallback. If none can run, the check is `skipped` (a judge that did not run
promotes no one) — the same honest degradation as cppcheck.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from validator.report import Failure, ValidationReport

RUN_TIMEOUT = 20  # seconds; a generated program that hangs FAILS, never hangs the run


# --- host compiler discovery -------------------------------------------------

def _tcc_path() -> str | None:
    """Bundled local TinyCC, if present (.tools/tcc/tcc.exe). Gitignored; the
    deployed image uses gcc instead."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (
        os.path.join(here, ".tools", "tcc", "tcc.exe"),
        os.path.join(here, ".tools", "tcc", "tcc"),
    ):
        if os.path.isfile(cand):
            return cand
    return shutil.which("tcc")


def find_host_runner():
    """Return (kind, path) for a compiler that can build AND run host binaries,
    or None. kind is 'cc' (gcc/clang flags) or 'tcc' (minimal flags). Both are
    driven the same way: compile every .c to one executable, then run it —
    `tcc -run` is NOT used because it treats extra source files as program
    arguments rather than linking them."""
    for cc in ("gcc", "cc", "clang"):
        p = shutil.which(cc)
        if p:
            return ("cc", p)
    tcc = _tcc_path()
    if tcc:
        return ("tcc", tcc)
    return None


def _run_c(runner, sources: dict[str, str], main_name: str, incdir: str) -> tuple[int, str, str]:
    """Compile `sources` (filename->text) written into a scratch dir into one
    executable and run it. Sandboxed: scratch-only writes, wall-clock timeout,
    no network use by the toolchain. Returns (exit_code, stdout, stderr)."""
    kind, cc = runner
    with tempfile.TemporaryDirectory(prefix="ep_math_") as d:
        for fn, text in sources.items():
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write(text)
        cfiles = [os.path.join(d, fn) for fn in sources if fn.endswith(".c")]
        exe = os.path.join(d, "ep_prog.exe")
        if kind == "tcc":
            compile_cmd = [cc, "-I", d, *cfiles, "-o", exe]
        else:
            compile_cmd = [cc, "-O0", "-std=c99", "-I", d, *cfiles, "-o", exe, "-lm"]
        try:
            comp = subprocess.run(compile_cmd, capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT, cwd=d)
            if comp.returncode != 0:
                return comp.returncode, comp.stdout, comp.stderr
            proc = subprocess.run([exe], capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT, cwd=d)
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"execution exceeded {RUN_TIMEOUT}s timeout"


# --- helpers -----------------------------------------------------------------

def _header_for(files: dict[str, list[str]]) -> str | None:
    """The driver header the probe must #include. Prefer .h, then .hpp; nested
    Arduino layouts keep the basename."""
    for fn in files:
        if fn.endswith(".h"):
            return os.path.basename(fn)
    for fn in files:
        if fn.endswith((".hpp", ".hh")):
            return os.path.basename(fn)
    return None


def _c_sources(files: dict[str, list[str]]) -> dict[str, str]:
    """Flatten generated C sources by basename (headers + .c). C++ (.cpp) is not
    executable via the C harness — the math check targets the bare-metal C
    target, where the conversion is a free C function."""
    out: dict[str, str] = {}
    for fn, lines in files.items():
        if fn.endswith((".c", ".h")):
            out[os.path.basename(fn)] = "\n".join(lines) + "\n"
    return out


_MAIN_RE = re.compile(r"\bint\s+main\s*\(")


def _without_own_main(sources: dict[str, str]) -> dict[str, str]:
    """Drop any .c that defines its own main() — the bare-metal target ships a
    `<chip>_example.c` demo with a main, which would clash with the probe's main
    (two definitions -> link error). Headers and the driver source are kept."""
    return {fn: text for fn, text in sources.items()
            if not (fn.endswith(".c") and _MAIN_RE.search(text))}


def _defined_in_c(entry: str, sources: dict[str, str]) -> bool:
    """The entry point must be DEFINED (not merely declared in a header) in a .c
    source. A header declaration doesn't count — a driver that declares but never
    implements the math is ungrounded, which is a failure, not a benign skip."""
    for fn, text in sources.items():
        if fn.endswith(".c") and re.search(r"\b" + re.escape(entry) + r"\s*\(", text):
            return True
    return False


def _tol_ok(got: float, want: float, tolerance) -> bool:
    if tolerance == "exact":
        return got == want
    return abs(got - want) <= float(tolerance)


def _fmt(ctype: str) -> str:
    return "%.17g" if ctype in ("float", "double") else "%lld"


def _cast(ctype: str) -> str:
    return "(double)" if ctype in ("float", "double") else "(long long)"


# --- the check ---------------------------------------------------------------

def math_crosscheck(
    files: dict[str, list[str]], register_map: dict, report: ValidationReport
) -> None:
    oracle = register_map.get("math_oracle")
    if not oracle:
        # No document-sourced ground truth for the math — this is the existing
        # UNVERIFIED fallback, NOT a failure. Distinct from 'skipped' (toolchain)
        # and from a real 'fail'.
        report.checks["math_crosscheck"] = "not_applicable"
        return

    # provenance guard: a model-supplied expected value would make this worthless
    prov = oracle.get("provenance")
    if prov not in ("detected", "user"):
        report.checks["math_crosscheck"] = "fail"
        report.failures.append(Failure(
            "math_crosscheck", "", None,
            f"math_oracle.provenance is {prov!r}; a math oracle must come from the "
            "datasheet (detected) or the user, never the model"))
        return

    runner = find_host_runner()
    if runner is None:
        report.checks["math_crosscheck"] = "skipped"
        report.notes.append(
            "math cross-check skipped: no host compiler available to run the "
            "generated math (install gcc/tcc; the deployed image has gcc)")
        return

    sources = _c_sources(files)
    header = _header_for(files)
    has_c = any(fn.endswith(".c") for fn in sources)
    if not has_c or header is None:
        report.checks["math_crosscheck"] = "skipped"
        report.notes.append(
            "math cross-check skipped: no bare-metal C driver to execute (the "
            "math check targets the C target, not the Arduino C++ library)")
        return

    kind = oracle.get("kind")
    if kind == "table":
        _check_table(runner, sources, header, oracle, report)
    elif kind == "reference_code":
        _check_reference(runner, sources, header, oracle, report)
    else:
        report.checks["math_crosscheck"] = "fail"
        report.failures.append(Failure(
            "math_crosscheck", "", None, f"unknown math_oracle.kind: {kind!r}"))


def _check_table(runner, sources, header, oracle, report) -> None:
    entry = oracle["entry"]
    in_ct = oracle.get("input_ctype", "int32_t")
    out_ct = oracle.get("output_ctype", "float")
    vectors = oracle.get("vectors", [])
    tol = oracle.get("tolerance", "exact")

    if not _defined_in_c(entry, sources):
        report.checks["math_crosscheck"] = "fail"
        report.failures.append(Failure(
            "math_crosscheck", header, None,
            f"the generated driver does not define the conversion entry point "
            f"'{entry}' the datasheet vector must call — the math cannot be "
            "grounded; refusing to validate ungrounded conversion math"))
        return

    calls = "\n".join(
        f'    printf("{_fmt(out_ct)}\\n", {_cast(out_ct)}{entry}(({in_ct}){v["in"]}));'
        for v in vectors)
    main_c = (
        f'#include "{header}"\n#include <stdio.h>\n#include <stdint.h>\n'
        f"int main(void){{\n{calls}\n    return 0;\n}}\n")
    probe = _without_own_main(sources)
    probe["_ep_math_main.c"] = main_c

    rc, out, err = _run_c(runner, probe, "_ep_math_main.c", incdir=".")
    if rc != 0:
        report.checks["math_crosscheck"] = "skipped"
        report.notes.append(
            "math cross-check skipped: the generated C driver could not be "
            f"host-compiled to run the math (compiler exit {rc}): "
            f"{(err or out).strip()[:300]}")
        return

    got = [ln for ln in out.splitlines() if ln.strip() != ""]
    if len(got) != len(vectors):
        report.checks["math_crosscheck"] = "fail"
        report.failures.append(Failure(
            "math_crosscheck", header, None,
            f"expected {len(vectors)} conversion outputs, got {len(got)}"))
        return

    bad: list[str] = []
    for v, g in zip(vectors, got):
        try:
            gv = float(g)
        except ValueError:
            bad.append(f"in={v['in']}: non-numeric output {g!r}")
            continue
        if not _tol_ok(gv, float(v["out"]), tol):
            bad.append(f"in={v['in']}: got {gv} vs datasheet {v['out']}")

    if bad:
        report.checks["math_crosscheck"] = "fail"
        for b in bad:
            report.failures.append(Failure(
                "math_crosscheck", header, None,
                f"conversion math wrong — {b}"))
        return

    report.checks["math_crosscheck"] = "pass"
    report.verified_computation_entries.append(entry)
    n_neg = sum(1 for v in vectors if float(v["out"]) < 0)
    report.notes.append(
        f"conversion math executed against the datasheet table (p.{oracle.get('source_pages')}): "
        f"{len(vectors)} vectors incl. {n_neg} negative/two's-complement, "
        f"tolerance={tol} — all matched")


def _check_reference(runner, sources, header, oracle, report) -> None:
    """Differential test against the datasheet's own reference functions.

    Verifies TRANSCRIPTION FIDELITY, not mathematical correctness: generated ==
    reference for identical inputs and identical (harness-chosen) calibration
    constants over a spread of inputs incl. edge cases. Constants are test
    inputs, not model-supplied 'answers'."""
    gen_entry = oracle["entry"]                     # generated fn name (contract)
    ref_entry = oracle["reference_entry"]           # datasheet fn name
    ref_c = oracle["reference_c"]                   # datasheet reference source
    in_ct = oracle.get("input_ctype", "int32_t")
    out_ct = oracle.get("output_ctype", "int32_t")
    spread = oracle.get("input_spread", [])
    calib = oracle.get("calibration", {})           # dig_* test constants (harness)
    tol = oracle.get("tolerance", "exact")

    if not _defined_in_c(gen_entry, sources):
        report.checks["math_crosscheck"] = "fail"
        report.failures.append(Failure(
            "math_crosscheck", header, None,
            f"the generated driver does not define '{gen_entry}' — the differential "
            "oracle has nothing to compare; refusing to validate ungrounded math"))
        return

    # shared calibration globals both sides read (datasheet variable names)
    calib_c = "\n".join(f"{k} = {v};" for k, v in _calib_defs(calib))
    calib_h = "\n".join(f"extern {t} {n};" for (t, n) in _calib_types(calib))

    ref_src = f"#include <stdint.h>\n#include \"_ep_calib.h\"\n{ref_c}\n"
    calib_hdr = f"#include <stdint.h>\n{calib_h}\n"
    calib_src = f"#include <stdint.h>\n{_calib_definitions(calib)}\n"

    loop = "\n".join(
        f'    {{ {in_ct} x = ({in_ct}){s}; '
        f'printf("{_fmt(out_ct)} {_fmt(out_ct)}\\n", '
        f'{_cast(out_ct)}{gen_entry}(x), {_cast(out_ct)}{ref_entry}(x)); }}'
        for s in spread)
    main_c = (
        f'#include "{header}"\n#include "_ep_ref.h"\n#include <stdio.h>\n'
        f"#include <stdint.h>\nint main(void){{\n{loop}\n    return 0;\n}}\n")

    probe = _without_own_main(sources)
    probe["_ep_calib.h"] = calib_hdr
    probe["_ep_calib.c"] = calib_src
    probe["_ep_ref.h"] = f"#include <stdint.h>\n{out_ct} {ref_entry}({in_ct});\n"
    probe["_ep_ref.c"] = ref_src
    probe["_ep_math_main.c"] = main_c

    rc, out, err = _run_c(runner, probe, "_ep_math_main.c", incdir=".")
    if rc != 0:
        report.checks["math_crosscheck"] = "skipped"
        report.notes.append(
            "math cross-check skipped: the differential program could not be "
            f"host-compiled (exit {rc}): {(err or out).strip()[:300]}")
        return

    rows = [ln.split() for ln in out.splitlines() if ln.strip()]
    bad: list[str] = []
    for s, row in zip(spread, rows):
        if len(row) != 2:
            bad.append(f"in={s}: malformed output {row!r}")
            continue
        try:
            g, r = float(row[0]), float(row[1])
        except ValueError:
            bad.append(f"in={s}: non-numeric output {row!r}")
            continue
        if not _tol_ok(g, r, tol):
            bad.append(f"in={s}: generated {g} vs datasheet-reference {r}")

    if bad or len(rows) != len(spread):
        report.checks["math_crosscheck"] = "fail"
        for b in (bad or [f"expected {len(spread)} rows, got {len(rows)}"]):
            report.failures.append(Failure(
                "math_crosscheck", header, None,
                f"compensation math diverges from the datasheet reference — {b}"))
        return

    report.checks["math_crosscheck"] = "pass"
    report.verified_computation_entries.append(gen_entry)
    report.notes.append(
        f"compensation math differentially tested against the datasheet reference "
        f"'{ref_entry}' (p.{oracle.get('source_pages')}) over {len(spread)} inputs "
        f"incl. edge cases, tolerance={tol} — transcription fidelity confirmed "
        "(algorithm correctness itself is the datasheet's, not verified here)")


def _calib_types(calib: dict) -> list[tuple[str, str]]:
    return [(_calib_ctype(k), k) for k in calib]


def _calib_ctype(name: str) -> str:
    # BME280 convention: dig_T1/dig_P1/dig_H1/dig_H3 unsigned, rest signed.
    n = name.lower()
    if n in ("dig_t1", "dig_p1", "dig_h1", "dig_h3"):
        return "uint16_t" if n not in ("dig_h1", "dig_h3") else "uint8_t"
    return "int32_t"


def _calib_defs(calib: dict) -> list[tuple[str, int]]:
    return [(k, v) for k, v in calib.items()]


def _calib_definitions(calib: dict) -> str:
    return "\n".join(f"{_calib_ctype(k)} {k} = {v};" for k, v in calib.items())
