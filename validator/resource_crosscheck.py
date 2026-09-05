"""V2 workstream 3: the system-integration cross-check — resource conflicts.

Every V1 check verifies ONE device against ONE document. Composition breaks that
assumption: two individually-verified drivers can each be perfectly correct and
still produce a system that cannot work, because they claim the same physical
pin, the same 7-bit address on one bus, incompatible speeds on one peripheral,
or the same DMA stream. Nothing in the per-device pipeline can see that — the
conflict only exists at the system level. This check is the system-level analog
of `register_crosscheck`: a conflict is a HARD FAILURE, never a warning, because
a double-booked pin is not a style opinion, it is a board that does not work.

WHAT THIS CHECK VERIFIES (and what it does NOT)
-----------------------------------------------
It verifies that the resource claims the composed devices make are mutually
CONSISTENT. It does not verify that any individual claim is CORRECT for the
target MCU — that needs a pin/alternate-function table, and the V1.7 MCU map
(`schema/mcu-map.schema.json`) extracts clock / GPIO / peripheral REGISTERS
only; it carries no AF table. So:

  * if `mcu_map["pin_alternate_functions"]` IS supplied, each claimed pin
    function is checked against it and an impossible mapping is a hard failure;
  * if it is NOT supplied, pin capability is reported as NOT VERIFIED in a note.

We never guess whether PB6 can be I2C1_SCL. Inventing that mapping would be the
exact class of bug the V1.6 provenance work exists to prevent — an unverified
fact presented as verified.

INPUT: `devices`
----------------
A list of dicts, one per composed device. Every key is optional; a device that
declares nothing simply contributes no claims.

    {
      "name": "BME280",              # label used in conflict messages

      "pins": [                      # physical MCU pins this device occupies
        {"pin": "PB6",               #   required: the MCU pin designator
         "function": "I2C1_SCL",     #   what the pin is muxed to ("<INST>_<SIG>"
                                     #   for a peripheral AF, e.g. "GPIO_OUT" for
                                     #   a plain GPIO)
         "shared": True},            #   optional override: True = this device
                                     #   knowingly shares the pin, False = it
                                     #   must have the pin exclusively. Omitted
                                     #   means "decide from bus topology".
        "PB7",                       #   shorthand: a bare string is a pin claim
      ],                             #   with no declared function

      "bus": {                       # the bus this device hangs off
        "kind": "i2c",               #   i2c | spi | uart | can | onewire | ...
        "instance": "I2C1",          #   the MCU peripheral instance
        "address": "0x76",           #   i2c only: 7-bit address (int or "0x76")
        "speed_hz": 400000,          #   any further scalar keys (mode,
        "mode": "master",            #   spi_mode, bit_order, addressing, ...)
      },                             #   are compared across devices on the same
                                     #   instance; a disagreement is contention.

      "dma": [                       # DMA claims
        {"controller": "DMA1", "stream": 0, "channel": 1, "direction": "rx"},
      ],

      "irq": [                       # interrupt-line claims
        {"line": "I2C1_EV_IRQn", "shared": True},
        "EXTI9_5",                   #   shorthand: a bare string is a line name
      ],
    }

CONFLICT RULES
--------------
1. PIN MUX — two claims on one pin conflict unless they can legitimately
   coexist. They coexist when every claim says `shared: true`, or when all
   claims name the SAME function on the SAME bus instance AND that signal is
   electrically multi-drop for that bus kind (see `_MULTIDROP`). That table is
   BUS TOPOLOGY from the bus standards (I2C is a shared two-wire bus; SPI
   SCK/MOSI/MISO are shared but each device needs its own CS) — it is not
   chip-specific data and nothing in it is invented about a particular part.
   Anything unrecognised defaults to NOT shareable, so an unknown bus produces a
   reported conflict rather than a silent pass.

2. BUS ADDRESS — two I2C devices on one instance claiming the same 7-bit
   address. An address above 0x7F is also a hard failure (it is an 8-bit
   read/write address, not a 7-bit device address).

3. CLOCK / BUS CONTENTION — devices sharing a bus instance must agree on that
   instance's configuration. Any scalar key present in both `bus` dicts (other
   than the per-device `address`) must match: differing `speed_hz` on one I2C
   peripheral, differing `spi_mode`, or the same instance declared with two
   different `kind`s. A key only one device declares is NOT a conflict — an
   undeclared value contradicts nothing.

4. DMA / IRQ — two devices claiming the same DMA stream (or channel, on parts
   without streams) on one controller, or the same IRQ line. An IRQ is shared
   legitimately when every claimant says `shared: true`, or when all claimants
   sit on the same bus instance and the line name names that instance (e.g. both
   I2C1 devices claiming `I2C1_EV_IRQn` — that is the peripheral's own
   interrupt, demultiplexed by the driver).

STATE (following the math_crosscheck precedent — four states, never conflated)
    pass            resources were compared and no conflict exists
    fail            at least one conflict; every conflict is also a Failure
    not_applicable  nothing to compose (< 2 devices, or no resource data at all)
                    — this is NOT a failure and NOT "skipped"
This check needs no toolchain, so it has no `skipped` state: it can always run.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from validator.report import Failure, ValidationReport

CHECK = "resource_crosscheck"

# Bus kinds whose signals are electrically multi-drop: several devices may
# legitimately occupy the same physical pin. Bus topology from the bus
# standards, NOT MCU data. Note SPI: SCK/MOSI/MISO are shared, CS/NSS/SS is
# deliberately absent — every SPI device needs its own chip select.
_MULTIDROP: dict[str, set[str]] = {
    "i2c": {"SCL", "SDA", "SMBA"},
    "smbus": {"SCL", "SDA", "SMBA"},
    "spi": {"SCK", "SCLK", "CLK", "MOSI", "MISO", "SDI", "SDO", "SDIO"},
    "onewire": {"DQ", "DATA"},
    "can": {"TX", "RX", "CANTX", "CANRX"},
}

# Instance-name prefix -> bus kind. Read off the instance name the SPEC supplied
# (pure syntax on the caller's own string); used only when the caller did not
# state `kind` explicitly. Unknown prefixes resolve to None -> not shareable.
_INSTANCE_KIND = (
    ("SMBUS", "smbus"), ("I2C", "i2c"), ("SPI", "spi"), ("QSPI", "spi"),
    ("CAN", "can"), ("FDCAN", "can"), ("USART", "uart"), ("UART", "uart"),
    ("LPUART", "uart"), ("OW", "onewire"), ("ONEWIRE", "onewire"),
)

# bus keys that are per-device, not per-instance, so they are never "contention"
_PER_DEVICE_BUS_KEYS = {"address", "addr", "cs", "cs_pin", "name", "instance", "kind"}

_PIN_RE = re.compile(r"^([A-Z]+)0*(\d+)$")


# --- claim model -------------------------------------------------------------

@dataclass(frozen=True)
class _Claim:
    """One device's claim on one resource. `resource` is the normalized key that
    two claims must share to collide; everything else is for the message."""

    device: str
    resource: str
    function: str              # display text: "I2C1_SCL", "GPIO_OUT", "rx", ...
    signal: str                # "SCL" — the tail of a "<INST>_<SIG>" function
    instance: str              # "I2C1" — bus/peripheral instance, "" if unknown
    shared: bool | None        # explicit caller declaration; None = infer


def _norm_pin(pin: str) -> str:
    """Uppercase and drop leading zeros in the numeric tail (PB06 -> PB6). Pure
    syntax on the designator the caller supplied — no MCU knowledge involved."""
    p = str(pin).strip().upper().replace(" ", "")
    m = _PIN_RE.match(p)
    return f"{m.group(1)}{int(m.group(2))}" if m else p


def _split_function(function: str) -> tuple[str, str]:
    """'I2C1_SCL' -> ('I2C1', 'SCL'). No underscore -> ('', <whole>)."""
    f = (function or "").strip().upper()
    if "_" in f:
        head, sig = f.rsplit("_", 1)
        return head, sig
    return "", f


def _kind_from_instance(instance: str) -> str | None:
    inst = (instance or "").strip().upper()
    for prefix, kind in _INSTANCE_KIND:
        if inst.startswith(prefix):
            return kind
    return None


def _device_name(dev: dict, index: int) -> str:
    return str(dev.get("name") or dev.get("device") or f"device[{index}]")


def _as_int(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return None


def _bus_instance(dev: dict) -> str:
    bus = dev.get("bus") or {}
    return str(bus.get("instance") or "").strip().upper()


# --- claim extraction --------------------------------------------------------

def _pin_claims(dev: dict, name: str) -> list[_Claim]:
    claims: list[_Claim] = []
    dev_instance = _bus_instance(dev)
    for entry in dev.get("pins") or []:
        if isinstance(entry, str):
            entry = {"pin": entry}
        pin = entry.get("pin") or entry.get("name")
        if not pin:
            continue
        function = str(entry.get("function") or entry.get("signal") or "")
        inst, sig = _split_function(function)
        claims.append(_Claim(
            device=name,
            resource=_norm_pin(pin),
            function=function or "(unspecified)",
            signal=sig,
            # a bare-signal function ("SCL") belongs to the device's own bus
            instance=inst or (dev_instance if sig else ""),
            shared=entry.get("shared"),
        ))
    return claims


def _dma_claims(dev: dict, name: str) -> list[_Claim]:
    claims: list[_Claim] = []
    for entry in dev.get("dma") or []:
        if isinstance(entry, str):
            entry = {"controller": entry}
        controller = str(entry.get("controller") or entry.get("name") or "DMA").upper()
        stream = _as_int(entry.get("stream"))
        channel = _as_int(entry.get("channel"))
        if stream is None and channel is None:
            continue
        # On parts with streams the STREAM is the exclusive resource (its channel
        # only selects which request drives it); on parts without, the channel is.
        if stream is not None:
            resource, unit = f"{controller}:stream{stream}", f"stream {stream}"
        else:
            resource, unit = f"{controller}:channel{channel}", f"channel {channel}"
        detail = unit if channel is None or stream is None else f"{unit}/channel {channel}"
        direction = entry.get("direction")
        if direction:
            detail += f" ({direction})"
        claims.append(_Claim(
            device=name, resource=resource, function=detail, signal="",
            instance=controller, shared=entry.get("shared")))
    return claims


def _irq_claims(dev: dict, name: str) -> list[_Claim]:
    claims: list[_Claim] = []
    dev_instance = _bus_instance(dev)
    for entry in dev.get("irq") or dev.get("irqs") or []:
        if isinstance(entry, str):
            entry = {"line": entry}
        line = entry.get("line") or entry.get("name")
        if not line:
            continue
        claims.append(_Claim(
            device=name, resource=str(line).strip().upper(), function=str(line),
            signal="", instance=dev_instance, shared=entry.get("shared")))
    return claims


def build_resource_map(devices: list[dict] | None) -> dict:
    """The system resource map: every claim, grouped by the resource it claims.

    Pure data — it decides nothing. `resource_crosscheck` reads it to find
    collisions, and the V2 Resource Map screen renders it (a group with more
    than one claimant is what lights up red)."""
    devices = devices or []
    pins: dict[str, list[_Claim]] = defaultdict(list)
    dma: dict[str, list[_Claim]] = defaultdict(list)
    irq: dict[str, list[_Claim]] = defaultdict(list)
    buses: dict[str, list[tuple[str, dict]]] = defaultdict(list)

    for i, dev in enumerate(devices):
        name = _device_name(dev, i)
        for c in _pin_claims(dev, name):
            pins[c.resource].append(c)
        for c in _dma_claims(dev, name):
            dma[c.resource].append(c)
        for c in _irq_claims(dev, name):
            irq[c.resource].append(c)
        instance = _bus_instance(dev)
        if instance:
            buses[instance].append((name, dict(dev.get("bus") or {})))

    return {
        "pins": {k: [vars(c) for c in v] for k, v in sorted(pins.items())},
        "buses": {k: [{"device": n, **b} for n, b in v] for k, v in sorted(buses.items())},
        "dma": {k: [vars(c) for c in v] for k, v in sorted(dma.items())},
        "irq": {k: [vars(c) for c in v] for k, v in sorted(irq.items())},
        "device_count": len(devices),
    }


def _claim_count(rmap: dict) -> int:
    return sum(len(v) for group in ("pins", "dma", "irq")
               for v in rmap[group].values()) + len(rmap["buses"])


# --- compatibility rules -----------------------------------------------------

def _explicit(claims: list[_Claim]) -> bool | None:
    """Caller-declared sharing wins over any inference. An explicit `False`
    anywhere means the pin must be exclusive."""
    if any(c.shared is False for c in claims):
        return False
    if claims and all(c.shared is True for c in claims):
        return True
    return None


def _pins_coexist(claims: list[_Claim], bus_kinds: dict[str, str]) -> bool:
    decided = _explicit(claims)
    if decided is not None:
        return decided
    functions = {c.function.strip().upper() for c in claims}
    instances = {c.instance for c in claims}
    if len(functions) != 1 or len(instances) != 1:
        return False
    instance = next(iter(instances))
    if not instance:
        return False
    kind = bus_kinds.get(instance) or _kind_from_instance(instance)
    return bool(kind) and claims[0].signal in _MULTIDROP.get(kind, set())


def _irqs_coexist(claims: list[_Claim]) -> bool:
    decided = _explicit(claims)
    if decided is not None:
        return decided
    instances = {c.instance for c in claims}
    if len(instances) != 1:
        return False
    instance = next(iter(instances))
    # the peripheral's own interrupt, claimed by devices on that peripheral
    return bool(instance) and instance in claims[0].resource


def _claimants(claims: list[_Claim]) -> str:
    seen: list[str] = []
    for c in claims:
        label = f"{c.device} as {c.function}" if c.function else c.device
        if label not in seen:
            seen.append(label)
    return "; ".join(seen)


# --- the check ---------------------------------------------------------------

def resource_crosscheck(
    devices: list[dict] | None, mcu_map: dict | None, report: ValidationReport
) -> None:
    """Cross-check the composed system's resource claims. See the module
    docstring for the `devices` structure and the conflict rules."""
    devices = devices or []
    mcu_map = mcu_map or {}
    rmap = build_resource_map(devices)

    if len(devices) < 2 or _claim_count(rmap) == 0:
        # Nothing to COMPOSE. A single device's resources were already the
        # concern of the per-device pipeline, and a system with no declared
        # resources gives this check nothing to compare. Neither is a defect and
        # neither is a check that could not run — say exactly that.
        report.checks[CHECK] = "not_applicable"
        report.notes.append(
            "resource cross-check not applicable: "
            + ("fewer than two devices to compose"
               if len(devices) < 2
               else f"{len(devices)} devices but no pin/bus/DMA/IRQ claims to compare"))
        return

    # instance -> declared bus kind, so a pin claim on I2C1 knows I2C1 is an I2C
    # bus. Only what a device actually declared; never inferred from the part.
    bus_kinds: dict[str, str] = {}
    for instance, entries in _raw_buses(devices).items():
        for _name, bus in entries:
            if bus.get("kind"):
                bus_kinds.setdefault(instance, str(bus["kind"]).strip().lower())

    failures: list[str] = []
    failures += _check_pins(rmap, bus_kinds)
    failures += _check_pin_capability(rmap, mcu_map)
    failures += _check_addresses(devices)
    failures += _check_bus_config(devices)
    failures += _check_exclusive(rmap["dma"], "DMA",
                                 "Assign one of them a different DMA stream/channel "
                                 "(which streams can serve which peripheral request "
                                 "is MCU-specific and is not in the supplied MCU map "
                                 "— check the reference manual before reassigning)")
    failures += _check_irqs(rmap)

    for message in failures:
        report.failures.append(Failure(CHECK, "", None, message))

    if failures:
        report.checks[CHECK] = "fail"
        return

    report.checks[CHECK] = "pass"
    report.notes.append(
        f"resource cross-check: {len(devices)} composed devices, "
        f"{len(rmap['pins'])} pin(s), {len(rmap['buses'])} bus instance(s), "
        f"{len(rmap['dma'])} DMA claim(s), {len(rmap['irq'])} IRQ line(s) — "
        "no pin-mux, bus-address, bus-config, DMA or IRQ conflicts")
    if not _af_table(mcu_map):
        report.notes.append(
            "pin alternate-function capability was NOT verified: the supplied MCU "
            "map has no pin_alternate_functions table (the V1.7 MCU map extracts "
            "clock/GPIO/peripheral registers only). Conflicts BETWEEN claims were "
            "checked; whether each pin can actually provide its claimed function "
            "was not — that mapping is unavailable and is not guessed here")


def _raw_buses(devices: list[dict]) -> dict[str, list[tuple[str, dict]]]:
    out: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for i, dev in enumerate(devices):
        instance = _bus_instance(dev)
        if instance:
            out[instance].append((_device_name(dev, i), dict(dev.get("bus") or {})))
    return out


def _check_pins(rmap: dict, bus_kinds: dict[str, str]) -> list[str]:
    out: list[str] = []
    for pin, raw in rmap["pins"].items():
        claims = [_Claim(**c) for c in raw]
        if len(claims) < 2 or _pins_coexist(claims, bus_kinds):
            continue
        by_function: dict[str, list[str]] = defaultdict(list)
        for c in claims:
            if c.device not in by_function[c.function]:
                by_function[c.function].append(c.device)
        parts = " vs ".join(f"{fn} ({', '.join(devs)})" for fn, devs in by_function.items())
        out.append(
            f"pin {pin} double-booked: {parts} — these claims cannot coexist on one "
            "pin. Reassign one device to a free pin, or, if this pin really is a "
            "shared bus signal here, declare it with \"shared\": true so the "
            "intent is stated rather than assumed")
    return out


def _af_table(mcu_map: dict) -> dict:
    table = mcu_map.get("pin_alternate_functions")
    return table if isinstance(table, dict) else {}


def _af_signals(entry) -> list[str]:
    """Accepts ["I2C1_SCL", ...] or [{"af": 4, "signal": "I2C1_SCL"}, ...]."""
    signals: list[str] = []
    for item in entry or []:
        if isinstance(item, str):
            signals.append(item.strip().upper())
        elif isinstance(item, dict):
            sig = item.get("signal") or item.get("function") or item.get("name")
            if sig:
                signals.append(str(sig).strip().upper())
    return signals


def _check_pin_capability(rmap: dict, mcu_map: dict) -> list[str]:
    """Only runs when an AF table was SUPPLIED. Without one we verify nothing
    here and say so in a note — we never infer that a pin can (or cannot) carry
    a function. Plain-GPIO claims are not checked against the AF table: an AF
    table describes alternate functions, so its silence about GPIO proves
    nothing either way."""
    table = _af_table(mcu_map)
    if not table:
        return []
    known = {_norm_pin(k): _af_signals(v) for k, v in table.items()}
    mcu = mcu_map.get("variant") or mcu_map.get("mcu_family") or "the MCU map"
    out: list[str] = []
    for pin, raw in rmap["pins"].items():
        for c in (_Claim(**d) for d in raw):
            function = c.function.strip().upper()
            if not c.instance or function in ("", "(UNSPECIFIED)") or \
                    function.startswith("GPIO"):
                continue
            signals = known.get(pin)
            if signals is None or function not in signals:
                if signals is None:
                    continue  # pin absent from the table -> unverifiable, not false
                out.append(
                    f"pin {pin} cannot provide {c.function} for {c.device}: the "
                    f"alternate-function table for {mcu} lists {', '.join(signals)} "
                    f"on {pin} — pick a pin that maps to {c.function}")
    return out


def _check_addresses(devices: list[dict]) -> list[str]:
    out: list[str] = []
    by_bus: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for i, dev in enumerate(devices):
        bus = dev.get("bus") or {}
        raw = bus.get("address", bus.get("addr"))
        if raw is None:
            continue
        name = _device_name(dev, i)
        instance = _bus_instance(dev) or str(bus.get("kind") or "bus").upper()
        addr = _as_int(raw)
        if addr is None:
            out.append(f"{name} declares an unparseable I2C address {raw!r} on "
                       f"{instance} — expected a 7-bit address such as 0x76")
            continue
        if addr > 0x7F or addr < 0:
            shifted = (addr >> 1) & 0x7F
            out.append(
                f"{name} declares address 0x{addr:02X} on {instance}, which is not a "
                f"7-bit address — this looks like an 8-bit read/write address; the "
                f"7-bit device address is 0x{shifted:02X}")
            continue
        by_bus[instance].append((name, addr, str(bus.get("kind") or "").lower()))

    for instance, entries in by_bus.items():
        seen: dict[int, list[str]] = defaultdict(list)
        for name, addr, _kind in entries:
            seen[addr].append(name)
        for addr, names in seen.items():
            if len(names) > 1:
                out.append(
                    f"bus address 0x{addr:02X} on {instance} claimed by "
                    f"{len(names)} devices: {', '.join(names)} — two devices cannot "
                    "answer to one address. Strap one device to its alternate "
                    "address (most parts have an address-select pin) or move it to "
                    "a different bus instance")
    return out


def _check_bus_config(devices: list[dict]) -> list[str]:
    """Devices sharing one peripheral share its configuration. A key only one
    device declares is not contention — an undeclared value contradicts nothing;
    we only compare values both sides actually stated."""
    out: list[str] = []
    for instance, entries in sorted(_raw_buses(devices).items()):
        if len(entries) < 2:
            continue
        kinds = {(name, str(bus.get("kind") or "").strip().lower())
                 for name, bus in entries if bus.get("kind")}
        distinct = {k for _n, k in kinds}
        if len(distinct) > 1:
            listed = ", ".join(f"{n} wants {k}" for n, k in sorted(kinds))
            out.append(
                f"bus instance {instance} is claimed as two different peripheral "
                f"kinds: {listed} — one peripheral instance cannot be both. "
                "Move one device to a different instance")
            continue

        keys: set[str] = set()
        for _name, bus in entries:
            keys |= {k for k, v in bus.items()
                     if k not in _PER_DEVICE_BUS_KEYS
                     and isinstance(v, (int, float, str, bool))}
        for key in sorted(keys):
            stated = [(name, bus[key]) for name, bus in entries if key in bus]
            values = {v for _n, v in stated}
            if len(stated) > 1 and len(values) > 1:
                listed = ", ".join(f"{n} requires {key}={v}" for n, v in stated)
                out.append(
                    f"bus configuration contention on {instance}: {listed} — one "
                    "peripheral has one configuration. Configure "
                    f"{instance} at a single {key} both devices' datasheets permit "
                    "(verify that against each datasheet — this check compares the "
                    "declared values, it does not know either part's limits), or "
                    "move one device to a different instance")
    return out


def _check_exclusive(group: dict, label: str, resolution: str) -> list[str]:
    out: list[str] = []
    for resource, raw in group.items():
        claims = [_Claim(**c) for c in raw]
        if len(claims) < 2 or _explicit(claims) is True:
            continue
        out.append(
            f"{label} resource {resource} claimed by {len(claims)} devices: "
            f"{_claimants(claims)} — it can serve only one. {resolution}")
    return out


def _check_irqs(rmap: dict) -> list[str]:
    out: list[str] = []
    for line, raw in rmap["irq"].items():
        claims = [_Claim(**c) for c in raw]
        if len(claims) < 2 or _irqs_coexist(claims):
            continue
        devices = ", ".join(dict.fromkeys(c.device for c in claims))
        out.append(
            f"IRQ line {line} claimed by {len(claims)} devices: {devices} — a vector "
            "runs one handler. Give one device a different interrupt line, or, if a "
            "single handler is genuinely meant to demultiplex both sources, declare "
            "the claims with \"shared\": true so that is stated rather than assumed")
    return out
