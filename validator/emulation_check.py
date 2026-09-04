"""V2 workstream 5: the runtime check — does the firmware ACTUALLY RUN?

Every other check in this system reasons about firmware without executing it.
`compile_check` proves it builds. `register_crosscheck` proves the names it uses
exist. `resource_crosscheck` proves the composed devices do not collide.
`math_crosscheck` (V1.10a) was the first EXECUTION capability, but it executes a
conversion function on the HOST — not the firmware, and not the peripherals.

None of that can catch the failure mode V2 exists to eliminate: firmware that
compiles clean, uses only real registers, has no resource conflicts, and still
does not work — a driver that never releases the bus, a main loop that never
reaches its threshold, an init sequence in the wrong order. The only way to know
is to RUN it on the target, with the devices answering, and look at what comes
out. That is this check.

WHAT THIS CHECK VERIFIES (and what it does NOT)
-----------------------------------------------
It verifies that the firmware ELF, loaded onto an EMULATED MCU with the composed
devices present as Renode's own device models, produces the observable UART
output the spec requires, within a bounded amount of virtual time.

It does NOT verify that the firmware works on physical hardware. Renode models a
device's register interface, not its silicon: analogue behaviour, real timing,
electrical faults, errata and board wiring are all outside it. A pass here means
"runs in emulation" — V2_PLAN §3 tier 2 — and must be labelled exactly that. The
last mile to a real board stays a human step (V5).

THE MOCKED-SENSOR RULE (the one that matters most)
--------------------------------------------------
A device is emulated ONLY with the Renode model that actually corresponds to it.
If Renode has no model for a device, this check reports the gap and refuses to
run — it NEVER substitutes a different sensor. Mocking a BME280 with a BMP180
because both are Bosch I2C barometers would produce a green check that proves
nothing about the code under test. That is precisely the "unverified presented
as verified" failure this product exists to prevent, so an absent model is an
honest `skipped`, never a quiet pass.

Model resolution order, most trustworthy first:
  1. `device["renode_model"]` — stated explicitly by the caller.
  2. a catalogue SCANNED from the installed Renode's own platform files, matched
     on the model's type name. Derived from the installation on disk, not from
     the model's memory.
  3. nothing — `skipped`, naming the device.

Note the asymmetry: the scan is used only to FIND a model, never to DENY one. If
a model exists but no shipped platform file happens to reference it, the caller
can still name it via `renode_model` and it will be used.

STATE (following the math_crosscheck / resource_crosscheck precedent)
    pass            the firmware ran and every expected pattern appeared
    fail            it ran and the output was wrong, it hung, or Renode rejected
                    the platform/script
    skipped         the check COULD NOT RUN — no Renode, no firmware ELF, or no
                    Renode model for a composed device. Never a pass.
    not_applicable  there is nothing to emulate — no composed devices, or no
                    declared expectations to assert against.

`skipped` and `not_applicable` are deliberately distinct and are never collapsed:
"we could not check" and "there was nothing to check" are different sentences,
and only one of them is a gap in coverage.

SANDBOXING AND BOUNDS
---------------------
* every generated file is written into a fresh scratch directory that is deleted
  afterwards; the firmware ELF is COPIED in, and the UART capture is written via
  Renode's `$ORIGIN` (the script's own directory) so nothing is written next to
  the user's sources or into the Renode installation;
* a WALL-CLOCK timeout kills Renode — a hung emulation FAILS, it never hangs the
  validator. This is not belt-and-braces: `emulation RunFor` bounds VIRTUAL time
  only, and enough virtual time still costs unbounded real time;
* `stdin` is closed. Without this, ANY script error drops Renode into its
  interactive monitor and it waits for input forever. Measured: a `.repl` naming
  an unknown model hangs indefinitely with an open stdin and exits in ~5s with a
  closed one;
* the base platform's `sysbus init:` block is re-emitted WITHOUT its remote
  `ApplySVD @http...` line, so a run needs no network. (Renode's shipped
  `platforms/cpus/stm32f4.repl` fetches an SVD over HTTPS purely to pretty-print
  register names in the monitor; nothing in the emulation depends on it.)

RENODE'S EXIT CODE IS NOT A VERDICT
-----------------------------------
Measured on Renode 1.16.1: a `.resc` whose `LoadPlatformDescription` fails prints
`Error E04: Could not resolve type` and STILL exits 0. Nothing here trusts the
exit code. The verdict comes from the captured UART bytes plus explicit scanning
of Renode's own stdout for its error markers.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile

from validator.report import Failure, ValidationReport

CHECK = "emulation_check"

# Wall-clock ceiling for one Renode invocation. A hung emulation FAILS.
RUN_TIMEOUT = 120
# Default virtual time to run for, in emulated seconds.
DEFAULT_RUN_FOR = "1"
DEFAULT_PLATFORM = "platforms/cpus/stm32f4.repl"
DEFAULT_UART = "usart2"

# Renode's own error markers on stdout. Its exit code is 0 even for these.
_RENODE_ERROR_RE = re.compile(
    r"(There was an error executing command|^Error E\d+:|Errors during parsing)",
    re.MULTILINE)
_MACHINE_STARTED = "Machine started"

# `name: Namespace.Type @ parent ...` in a Renode platform description.
_REPL_NODE_RE = re.compile(
    r"^\s*[A-Za-z_]\w*\s*:\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*@", re.MULTILINE)
_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")


# --- locating Renode ---------------------------------------------------------

def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_renode() -> str | None:
    """Path to a Renode executable, or None.

    Mirrors `math_crosscheck.find_host_runner`: prefer the gitignored local
    `.tools/` copy, then anything on PATH, then an explicit override. Version
    directories are globbed so an upgrade does not silently disable the check.
    """
    override = os.environ.get("EMBEDDPILOT_RENODE")
    if override and os.path.isfile(override):
        return override

    root = _repo_root()
    patterns = [
        os.path.join(root, ".tools", "renode_x", "*", "renode.exe"),
        os.path.join(root, ".tools", "renode_x", "*", "renode"),
        os.path.join(root, ".tools", "renode", "*", "renode.exe"),
        os.path.join(root, ".tools", "renode", "*", "renode"),
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]

    return shutil.which("renode")


def renode_root(renode_exe: str) -> str:
    """The Renode installation directory — where `platforms/` lives."""
    return os.path.dirname(os.path.abspath(renode_exe))


# --- the device-model catalogue ----------------------------------------------

def model_catalogue(root: str) -> dict[str, str]:
    """Map TYPE NAME (upper-cased, e.g. "BMP180") -> fully-qualified Renode model
    (e.g. "Sensors.BMP180"), scanned from the platform files of the Renode
    installation on disk.

    This is evidence, not recall: if `Sensors.BMP180` is in this map it is
    because a `.repl` shipped with THIS Renode build instantiates it. Absence
    proves nothing (a model can exist without any shipped board using it), which
    is why absence never produces a failure — only a `skipped`, and only after
    the caller's own `renode_model` was given priority.
    """
    catalogue: dict[str, str] = {}
    platforms = os.path.join(root, "platforms")
    if not os.path.isdir(platforms):
        return catalogue
    for path in glob.glob(os.path.join(platforms, "**", "*.repl"), recursive=True):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for qualified in _REPL_NODE_RE.findall(text):
            catalogue.setdefault(qualified.rsplit(".", 1)[-1].upper(), qualified)
    return catalogue


def _resolve_model(device: dict, catalogue: dict[str, str]) -> str | None:
    """The Renode model for one composed device, or None. NEVER approximates."""
    explicit = device.get("renode_model")
    if explicit:
        return str(explicit).strip()
    name = str(device.get("name") or device.get("device") or "").strip()
    if not name:
        return None
    # exact type-name match only; "BME280" must not resolve to "BMP180"
    return catalogue.get(re.sub(r"[^A-Za-z0-9_]", "", name).upper())


# --- generating the platform + script ----------------------------------------

def _node_name(device: dict, index: int, taken: set[str]) -> str:
    raw = str(device.get("name") or device.get("device") or f"dev{index}")
    node = re.sub(r"[^A-Za-z0-9_]", "_", raw).strip("_").lower() or f"dev{index}"
    if not node[0].isalpha():
        node = f"d_{node}"
    candidate, n = node, 1
    while candidate in taken:
        n += 1
        candidate = f"{node}{n}"
    taken.add(candidate)
    return candidate


def _bus_node(device: dict) -> str | None:
    """The Renode peripheral a device hangs off, e.g. "i2c1". Renode's node names
    are lower-case; the spec's "I2C1" is the same instance."""
    explicit = device.get("renode_bus")
    if explicit:
        return str(explicit).strip()
    instance = str((device.get("bus") or {}).get("instance") or "").strip()
    return instance.lower() or None


def _address(device: dict) -> int | None:
    bus = device.get("bus") or {}
    raw = bus.get("address", bus.get("addr"))
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(str(raw).strip(), 0)
    except (TypeError, ValueError):
        return None


def _sysbus_init_lines(root: str, platform_rel: str) -> list[str] | None:
    """The base platform's `sysbus: init:` body, minus any REMOTE `ApplySVD`.

    Re-emitting this block in the derived platform REPLACES the base one, which
    is how the network fetch is dropped while every other init directive (the
    `Tag`s a platform needs to boot) is preserved verbatim. Best-effort: on any
    surprise return None, and the caller keeps the base init and says so.
    """
    path = os.path.join(root, *platform_rel.replace("\\", "/").split("/"))
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read().splitlines()
    except OSError:
        return None

    lines: list[str] = []
    in_sysbus = in_init = False
    for line in raw:
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_sysbus = line.strip() == "sysbus:"
            in_init = False
            continue
        if not in_sysbus:
            continue
        if not in_init:
            in_init = line.strip() in ("init:", "init add:")
            continue
        if indent <= 4:                     # left the init body
            in_init = line.strip() in ("init:", "init add:")
            continue
        body = line.strip()
        if body.startswith("ApplySVD") and "@http" in body:
            continue                        # the only network access in the run
        lines.append(body)
    return lines if lines else None


def _build_repl(root: str, platform_rel: str, nodes: list[tuple[str, str, str, int]],
                notes: list[str]) -> str:
    parts = [f'using "{platform_rel}"', ""]
    for node, model, bus, address in nodes:
        # SPI attaches by chip-select, so no address is written
        where = f"{bus} 0x{address:02X}" if address is not None else bus
        parts.append(f"{node}: {model} @ {where}")
    parts.append("")

    init = _sysbus_init_lines(root, platform_rel)
    if init is None:
        notes.append(
            f"could not re-emit the `sysbus init:` block of {platform_rel}; the "
            "base platform's init runs unchanged, so this run may fetch an SVD "
            "over the network if Renode has not already cached one")
    else:
        parts.append("sysbus:")
        parts.append("    init:")
        parts += [f"        {line}" for line in init]
        parts.append("")
    return "\n".join(parts) + "\n"


def _format_value(value) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if "\n" in text or '"' in text:
        return None
    return f'"{text}"'


def _stimulus_lines(device: dict, node: str, bus: str, notes: list[str]) -> list[str]:
    """Monitor commands that feed KNOWN values into a mocked device, e.g.
    `sysbus.i2c1.bmp180 Temperature 24`. Property names must be identifiers and
    values must be scalars — the spec never gets to inject arbitrary script."""
    out: list[str] = []
    stimulus = device.get("stimulus") or {}
    if not isinstance(stimulus, dict):
        return out
    for prop, value in stimulus.items():
        name = str(prop).strip()
        formatted = _format_value(value)
        if not _IDENT_RE.match(name) or formatted is None:
            notes.append(
                f"ignored unusable stimulus {prop!r}={value!r} for {node}: a "
                "stimulus must be an identifier set to a scalar")
            continue
        out.append(f"sysbus.{bus}.{node} {name} {formatted}")
    return out


def _build_resc(uart: str, run_for: str, stimulus: list[str]) -> str:
    return "\n".join([
        'mach create "ep"',
        "machine LoadPlatformDescription @platform.repl",
        "sysbus LoadELF @firmware.elf",
        *stimulus,
        # $ORIGIN = this script's directory = the scratch dir. Keeps the capture
        # sandboxed AND survives spaces in the path, which a bare `@` path does not.
        f"sysbus.{uart} CreateFileBackend $ORIGIN/uart.txt true",
        f'emulation RunFor "{run_for}"',
        "quit",
        "",
    ])


# --- firmware discovery ------------------------------------------------------

def find_firmware(workdir: str, spec_path: str | None) -> str | None:
    """The ELF to emulate: the spec's path if given, else the newest `*.elf`
    under `workdir`. Only ELF — Renode's `LoadELF` needs the symbols and load
    addresses that a raw `.bin` has thrown away."""
    if spec_path:
        candidate = spec_path if os.path.isabs(spec_path) else os.path.join(workdir, spec_path)
        return candidate if os.path.isfile(candidate) else None
    matches = [p for p in glob.glob(os.path.join(workdir, "**", "*.elf"), recursive=True)
               if os.path.isfile(p)]
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


# --- matching ----------------------------------------------------------------

def _matches(entry, text: str) -> tuple[bool, str]:
    """(matched, description). An expectation is a plain string or a dict with
    `pattern` and an optional `kind` of "substring" (default) or "regex"."""
    if isinstance(entry, str):
        entry = {"pattern": entry}
    pattern = str(entry.get("pattern", ""))
    kind = str(entry.get("kind", "substring")).lower()
    label = str(entry.get("description") or pattern)
    if kind == "regex":
        try:
            return bool(re.search(pattern, text, re.MULTILINE)), label
        except re.error as exc:
            return False, f"{label} (invalid regex: {exc})"
    return pattern in text, label


def _excerpt(text: str, limit: int = 600) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " ...[truncated]"


# --- the check ---------------------------------------------------------------

def emulation_check(workdir: str, spec: dict | None, report: ValidationReport) -> None:
    """Run the composed firmware in Renode and assert its UART behaviour.

    `workdir`  directory holding the built project (searched for the ELF).
    `spec`     the application spec. Relevant keys:
                 target.platform  Renode-root-relative base platform description
                                  (default `platforms/cpus/stm32f4.repl`)
                 target.uart      peripheral whose output is asserted (`usart2`)
                 target.firmware  ELF path, relative to `workdir` (else newest)
                 target.run_for   virtual seconds to run (default "1")
                 target.timeout   wall-clock ceiling in seconds
                 devices          composed devices — the `resource_crosscheck`
                                  shape, plus optional `renode_model`,
                                  `renode_bus` and `stimulus`
                 expect           UART patterns that MUST appear
                 reject           UART patterns that must NOT appear
    `report`   mutated in place: `checks[CHECK]`, `failures`, `notes`.
    """
    spec = spec or {}
    target = spec.get("target") or {}
    devices = spec.get("devices") or []
    expect = spec.get("expect") or []
    reject = spec.get("reject") or []
    notes: list[str] = []

    # --- applicability, decided BEFORE tooling so the verdict does not depend
    # on which machine it ran on -------------------------------------------
    if not devices:
        report.checks[CHECK] = "not_applicable"
        report.notes.append(
            "emulation check not applicable: the spec composes no devices, so "
            "there is no mocked system for the firmware to exercise")
        return
    if not expect:
        report.checks[CHECK] = "not_applicable"
        report.notes.append(
            "emulation check not applicable: the spec declares no expected "
            "behaviour, and running firmware while asserting nothing about its "
            "output would demonstrate nothing")
        return

    # --- can the check run at all? ----------------------------------------
    renode = find_renode()
    if renode is None:
        report.checks[CHECK] = "skipped"
        report.notes.append(
            "emulation check skipped: Renode is not available, so the firmware "
            "was NOT executed — 'runs in emulation' is unproven for this build "
            "(install Renode, or set EMBEDDPILOT_RENODE to its executable)")
        return

    root = renode_root(renode)
    platform_rel = str(target.get("platform") or DEFAULT_PLATFORM)
    if not os.path.isfile(os.path.join(root, *platform_rel.split("/"))):
        report.checks[CHECK] = "skipped"
        report.notes.append(
            f"emulation check skipped: the base platform {platform_rel!r} is not "
            f"present in the Renode installation at {root}")
        return

    # --- map every device to ITS OWN model, or refuse ----------------------
    # Resolved BEFORE looking for the firmware: a device Renode cannot model is
    # a permanent property of the spec and this installation, whereas a missing
    # ELF is transient (the build simply has not run yet). Reporting the durable
    # gap first tells the caller the thing that will not fix itself.
    catalogue = model_catalogue(root)
    nodes: list[tuple[str, str, str, int]] = []
    stimulus: list[str] = []
    taken: set[str] = set()
    gaps: list[str] = []

    for i, device in enumerate(devices):
        label = str(device.get("name") or device.get("device") or f"device[{i}]")
        model = _resolve_model(device, catalogue)
        if model is None:
            gaps.append(
                f"{label}: Renode has no device model for this part in this "
                "installation")
            continue
        bus = _bus_node(device)
        address = _address(device)
        # An I2C device is addressed on the wire; an SPI device is selected by
        # its chip-select line and therefore has no bus address. Requiring one
        # would make every SPI part permanently unemulatable.
        needs_address = not (bus or "").lower().startswith("spi")
        if bus is None or (needs_address and address is None):
            gaps.append(
                f"{label}: emulating it needs a bus instance"
                + (" and an address" if needs_address else "")
                + f"; the spec gives instance={bus!r} address={address!r}")
            continue
        node = _node_name(device, i, taken)
        nodes.append((node, model, bus, address))
        stimulus += _stimulus_lines(device, node, bus, notes)

    if gaps:
        # The honest gap. We will NOT stand in a different sensor to make the
        # run go green: an assertion satisfied by the wrong device is a lie
        # about the code under test.
        report.checks[CHECK] = "skipped"
        report.notes.append(
            "emulation check skipped: " + "; ".join(gaps)
            + ". No substitute device was mocked in its place — a different "
            "sensor answering the bus would produce a result that says nothing "
            "about this firmware. This device's runtime behaviour is UNVERIFIED")
        return

    firmware = find_firmware(workdir, target.get("firmware"))
    if firmware is None:
        report.checks[CHECK] = "skipped"
        report.notes.append(
            "emulation check skipped: no firmware ELF was found to run "
            f"(searched {workdir}) — the project must be built before its "
            "runtime behaviour can be verified")
        return

    # --- run it ------------------------------------------------------------
    run_for = str(target.get("run_for") or DEFAULT_RUN_FOR)
    uart = str(target.get("uart") or DEFAULT_UART)
    timeout = int(target.get("timeout") or RUN_TIMEOUT)

    captured, stdout, timed_out = _run_emulation(
        renode, root, platform_rel, nodes, stimulus, firmware, uart, run_for,
        timeout, notes)

    for note in notes:
        report.notes.append(f"emulation check: {note}")

    # SPI parts are selected by chip-select and carry no bus address
    device_summary = ", ".join(
        f"{m} @ {b} 0x{a:02X}" if a is not None else f"{m} @ {b}"
        for _n, m, b, a in nodes)

    if timed_out:
        report.checks[CHECK] = "fail"
        report.failures.append(Failure(
            CHECK, os.path.basename(firmware), None,
            f"emulation did not finish within {timeout}s and was killed — the "
            "firmware or the emulator hung. A run that never terminates is a "
            "failure, not a pass; suspect an unbounded wait on a peripheral flag "
            f"(UART captured before the kill: {_excerpt(captured) or '<nothing>'})"))
        return

    renode_error = _RENODE_ERROR_RE.search(stdout)
    if renode_error:
        report.checks[CHECK] = "fail"
        report.failures.append(Failure(
            CHECK, "platform.repl", None,
            "Renode rejected the emulation setup, so the firmware never ran: "
            + _excerpt(_error_context(stdout), 400)))
        return

    if _MACHINE_STARTED not in stdout:
        report.checks[CHECK] = "fail"
        report.failures.append(Failure(
            CHECK, os.path.basename(firmware), None,
            "Renode never reported the machine as started, so no firmware was "
            f"executed: {_excerpt(stdout, 400)}"))
        return

    if not captured:
        report.checks[CHECK] = "fail"
        report.failures.append(Failure(
            CHECK, os.path.basename(firmware), None,
            f"the firmware ran for {run_for}s of virtual time on {uart} and "
            "produced NO output at all — expected "
            f"{len(expect)} pattern(s). Either it never reached its transmit "
            "path, or it is blocked waiting on a peripheral flag"))
        return

    missing = [label for entry in expect
               for ok, label in [_matches(entry, captured)] if not ok]
    present = [label for entry in reject
               for ok, label in [_matches(entry, captured)] if ok]

    if missing or present:
        report.checks[CHECK] = "fail"
        for label in missing:
            report.failures.append(Failure(
                CHECK, os.path.basename(firmware), None,
                f"the emulated firmware never produced the required output "
                f"{label!r} — it ran, but it did not behave as the spec requires. "
                f"Captured on {uart}: {_excerpt(captured)}"))
        for label in present:
            report.failures.append(Failure(
                CHECK, os.path.basename(firmware), None,
                f"the emulated firmware produced forbidden output {label!r}. "
                f"Captured on {uart}: {_excerpt(captured)}"))
        return

    report.checks[CHECK] = "pass"
    report.notes.append(
        f"emulation: firmware ran on {platform_rel} for {run_for}s of virtual "
        f"time with {len(nodes)} mocked device(s) ({device_summary}); "
        f"{len(expect)} expected pattern(s) observed on {uart}"
        + (f", {len(reject)} forbidden pattern(s) absent" if reject else "")
        + ". This is tier-2 'works': verified RUNNING IN EMULATION. Renode models "
        "each device's register interface, not its silicon — analogue behaviour, "
        "real timing and board wiring are NOT covered, so this is not evidence "
        "that the firmware works on physical hardware")


def _run_emulation(renode: str, root: str, platform_rel: str,
                   nodes: list[tuple[str, str, str, int]], stimulus: list[str],
                   firmware: str, uart: str, run_for: str, timeout: int,
                   notes: list[str]) -> tuple[str, str, bool]:
    """Execute ONE bounded Renode run and return `(uart_text, stdout, timed_out)`.

    Split out of `emulation_check` so that a test can observe the exact bytes
    the check itself judges, rather than a re-implementation of the run that
    could drift away from it. Every sandboxing rule documented at the top of
    this module lives here and applies to every caller: fresh scratch directory,
    deleted afterwards; the ELF copied in; the capture written via `$ORIGIN`;
    a wall-clock kill; `stdin` closed.

    This is a pure extraction — it adds no way to relax a verdict. The caller
    still decides what the bytes mean.
    """
    with tempfile.TemporaryDirectory(prefix="ep_emu_") as scratch:
        repl = _build_repl(root, platform_rel, nodes, notes)
        resc = _build_resc(uart, run_for, stimulus)
        with open(os.path.join(scratch, "platform.repl"), "w", encoding="utf-8") as f:
            f.write(repl)
        with open(os.path.join(scratch, "run.resc"), "w", encoding="utf-8") as f:
            f.write(resc)
        shutil.copyfile(firmware, os.path.join(scratch, "firmware.elf"))

        try:
            proc = subprocess.run(
                [renode, "--console", "--disable-xwt", "--plain",
                 "-e", "include @run.resc"],
                capture_output=True, text=True, cwd=scratch, timeout=timeout,
                # MANDATORY: with an open stdin any script error parks Renode in
                # its interactive monitor and it never returns.
                stdin=subprocess.DEVNULL,
            )
            stdout, timed_out = (proc.stdout or "") + (proc.stderr or ""), False
        except subprocess.TimeoutExpired as exc:
            stdout = _decode(exc.stdout) + _decode(exc.stderr)
            timed_out = True

        uart_path = os.path.join(scratch, "uart.txt")
        captured = ""
        if os.path.isfile(uart_path):
            with open(uart_path, "rb") as f:
                captured = f.read().decode("utf-8", errors="replace")

    return captured, stdout, timed_out


def _decode(raw) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _error_context(stdout: str) -> str:
    """The Renode error plus the following lines — its parser points at the
    offending line underneath the message, which is the useful part."""
    match = _RENODE_ERROR_RE.search(stdout)
    if not match:
        return _excerpt(stdout, 400)
    tail = stdout[match.start():].splitlines()
    return "\n".join(line for line in tail[:8] if line.strip())
