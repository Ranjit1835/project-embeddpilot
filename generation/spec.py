"""V2 WS1: natural-language requirement -> structured application spec.

THE RULE (V2_PLAN.md 4b(b)): **never invent a requirement — ask.**

This is the application-scale continuation of V1.6's input-provenance work
(`generation/inputs.py::assert_input_provenance`), which killed silent auto-fill
at device scale: a chip or interface that was never stated is never guessed, it
BLOCKS. The failure mode it prevents is the nastiest one this product has,
because it is invisible: the generated code can be perfectly self-consistent
with the map and still be the wrong driver entirely, so no downstream check can
catch it. At application scale the same hole is wider — an invented threshold, an
invented bus, an invented board produces a *complete, compiling, emulation-
passing* application that implements a requirement the user never asked for.
Emulation would happily prove it works. It would be working, verified, and wrong.

So the spec is the contract, and every field in it carries a provenance:

    "user"   the human stated it in their requirement text, and we can point at
             the exact span of their text that says so
    "asked"  the human answered a clarifying question we asked them

There is no third value. There is deliberately no "inferred", no "model", no
"default" — a value that cannot be grounded in something the user actually said
is not a value, it is a QUESTION. `assert_spec_complete` refuses to let
generation start while any required field is missing or unanswered, mirroring
`assert_input_provenance` field-for-field.

HOW THE LLM IS CONTAINED
------------------------
Parsing free-form English needs a model (`generation/provider.py::make_provider`,
no vendor hard-coded). But a model asked to "extract a spec" will cheerfully
complete the picture: "a temp sensor" becomes BME280, "an STM32 board" becomes a
Nucleo-F411RE, "when it gets hot" becomes 30 C. Prompting against that is not a
guarantee, so the prompt is the *weakest* of the four defences here:

  1. the model must return a verbatim `evidence` span from the user's text for
     every value it extracts;
  2. `_verbatim` checks that span really occurs in the user's text (no fabricated
     quotes), and `_grounded` checks the VALUE is actually supported by that span
     (token-level, so "Nucleo-F411" cannot ground the mcu "STM32F411");
  3. anything that fails 1 or 2 is DROPPED — recorded in `spec.dropped` for the
     audit trail — and the field becomes a clarifying question instead;
  4. provenance is never read from the model's output at all. It is assigned by
     this module: grounded-in-the-text -> "user", answered-a-question -> "asked".

The model may also PROPOSE extra questions (it sees nuance a rule cannot), but
its questions can only be *added* to fields already known to be unknown, are
screened for specificity, and can never remove a question or set a value.
The question list itself is produced deterministically by `detect_ambiguities`,
so the same spec always yields the same questions with or without a model.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field as dc_field
from typing import Any

from generation.inputs import canonical_bus

SCHEMA_VERSION = "2.0"
SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schema", "application-spec.schema.json",
)

# The ONLY two origins a spec value may have. Mirrors inputs.ALLOWED, minus
# "detected"/"sample": there is no document to detect an application requirement
# from and no curated fixture that could legitimately supply one — a requirement
# comes from a human or it does not exist.
ALLOWED_PROVENANCE = {"user", "asked"}
# Origins that are explicitly named in the error message when they show up,
# because each one is a specific way of inventing a requirement.
FORBIDDEN_PROVENANCE = {
    "inferred": "inferred from context",
    "model": "supplied by the language model",
    "llm": "supplied by the language model",
    "default": "a silent default",
    "assumed": "assumed",
    "guess": "guessed",
    "detected": "detected from a document (applications have no datasheet oracle)",
}


class SpecError(ValueError):
    """Base for every reason a spec may not proceed to generation."""


class SpecIncompleteError(SpecError):
    """A required spec field is missing, or a clarifying question is unanswered."""


class SpecProvenanceError(SpecError):
    """A spec field carries an origin other than 'user' or 'asked'."""


# --- ambiguity classes ------------------------------------------------------
# Each is a distinct way a requirement can fail to be buildable. They are named
# so the UI can group questions and so tests can assert on classes rather than
# on question wording.
MISSING_TARGET = "missing_target"                    # no board / no MCU
MISSING_DEVICE = "missing_device"                    # no devices at all
AMBIGUOUS_CHIP = "ambiguous_chip"                    # "a temp sensor" — which part?
MISSING_INTERFACE = "missing_interface"              # device named, no bus
MISSING_ROLE = "missing_role"                        # device named, no job
MISSING_PIN = "missing_pin"                          # GPIO device, no pin
MISSING_ADDRESS = "missing_address"                  # I2C device, no address
MISSING_BEHAVIOR = "missing_behavior"                # nothing for the app to do
MISSING_TRIGGER_SOURCE = "missing_trigger_source"    # "when it's hot" — what reading?
MISSING_COMPARATOR = "missing_comparator"            # above or below?
MISSING_THRESHOLD = "missing_threshold"              # no number
MISSING_UNITS = "missing_units"                      # number with no unit
MISSING_ACTION = "missing_action"                    # trigger with no consequence
MISSING_SAMPLE_RATE = "missing_sample_rate"          # how often to read
MISSING_FAILURE_BEHAVIOR = "missing_failure_behavior"  # what if the read fails
MISSING_OUTPUT_TARGET = "missing_output_target"      # what artifact to produce

# Closed vocabularies this project OWNS. Offering these as `options` on a
# question is not inventing a device fact — it is telling the user which answers
# the generator can act on. Nothing here is ever auto-selected.
INTERFACES = ("I2C", "SPI", "GPIO", "ANALOG", "UART", "1-WIRE")
COMPARATORS = (">", ">=", "<", "<=", "==", "!=")
OUTPUT_TARGETS = ("arduino-sketch", "platformio-project", "cmake-project")


# ---------------------------------------------------------------------------
# provenanced value
# ---------------------------------------------------------------------------

@dataclass
class Field:
    """One spec value plus the receipt that proves the user supplied it.

    `evidence` is the whole point: for provenance "user" it is the verbatim span
    of the requirement text the value came from, for "asked" it is the question
    id and the answer. A Field with no evidence is not a value with a missing
    citation — it is an invented value, and the guard treats it as one."""

    value: Any
    provenance: str
    evidence: str

    def __post_init__(self) -> None:
        # Assign-time guard so an invented value cannot even be CONSTRUCTED and
        # sit in memory looking legitimate until assert_spec_complete runs.
        if self.provenance not in ALLOWED_PROVENANCE:
            why = FORBIDDEN_PROVENANCE.get(str(self.provenance).lower())
            detail = f" ({why})" if why else ""
            raise SpecProvenanceError(
                f"provenance {self.provenance!r}{detail} is not allowed on a spec "
                f"value (got value {self.value!r}). Only 'user' (the human stated "
                "it) and 'asked' (the human answered a clarifying question) exist "
                "— anything else is an invented requirement, which must be a "
                "question instead."
            )

    def to_dict(self) -> dict:
        return {"value": self.value, "provenance": self.provenance,
                "evidence": self.evidence}


def user_field(value: Any, evidence: str) -> Field:
    return Field(value=value, provenance="user", evidence=evidence)


def asked_field(value: Any, question_id: str, answer: str) -> Field:
    return Field(value=value, provenance="asked",
                 evidence=f"answer to {question_id}: {answer.strip()}")


# ---------------------------------------------------------------------------
# spec structure
# ---------------------------------------------------------------------------

@dataclass
class Target:
    board: Field | None = None   # "Nucleo-F411RE"
    mcu: Field | None = None     # "STM32F411RE"


@dataclass
class Device:
    """A composed device. Shape is deliberately close to the dict
    `validator/resource_crosscheck.py` consumes, so the spec feeds the resource
    map without a translation layer inventing anything in between."""

    name: Field | None = None       # part number, e.g. "BME280"
    role: Field | None = None       # "temperature sensor", "relay output"
    interface: Field | None = None  # one of INTERFACES
    address: Field | None = None    # I2C 7-bit address, when the user stated one
    pin: Field | None = None        # required for GPIO/ANALOG devices


@dataclass
class Trigger:
    source: Field | None = None      # "temperature" — which reading
    comparator: Field | None = None  # one of COMPARATORS
    threshold: Field | None = None   # number
    unit: Field | None = None        # "C", "%", "hPa"


@dataclass
class Behavior:
    """trigger -> action. "when temp > 30 turn the relay on"."""

    id: str = "b1"
    trigger: Trigger = dc_field(default_factory=Trigger)
    action: Field | None = None      # "turn relay on"


@dataclass
class Constraint:
    """A named non-functional value. `name` is our vocabulary key (not a user
    value, so it carries no provenance); `value`/`unit` are the user's."""

    name: str
    value: Field | None = None
    unit: Field | None = None


@dataclass
class Question:
    """A clarifying question. Specific and answerable, never 'anything else?'.

    `blocking` is True for every field `assert_spec_complete` requires: an
    unanswered blocking question means NO CODE. `options` is only ever drawn
    from a closed vocabulary this project owns (INTERFACES, COMPARATORS,
    OUTPUT_TARGETS) — never a suggested part number, board or threshold, because
    a suggestion is an invented value wearing a question mark."""

    id: str
    field: str
    kind: str
    text: str
    options: list[str] = dc_field(default_factory=list)
    blocking: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ApplicationSpec:
    requirement_text: str = ""
    target: Target = dc_field(default_factory=Target)
    devices: list[Device] = dc_field(default_factory=list)
    behaviors: list[Behavior] = dc_field(default_factory=list)
    constraints: list[Constraint] = dc_field(default_factory=list)
    failure_behavior: Field | None = None
    output_target: Field | None = None
    open_questions: list[Question] = dc_field(default_factory=list)
    # audit trail: values the model produced that could NOT be grounded in the
    # user's text and were therefore discarded. Kept so the honesty story is
    # inspectable ("the model wanted to say BME280; we refused and asked").
    dropped: list[dict] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)

    # -- constraints helper --------------------------------------------------
    def constraint(self, name: str) -> Constraint | None:
        for c in self.constraints:
            if c.name == name:
                return c
        return None

    def set_constraint(self, name: str, value: Field | None,
                       unit: Field | None = None) -> None:
        existing = self.constraint(name)
        if existing is None:
            self.constraints.append(Constraint(name=name, value=value, unit=unit))
            return
        if value is not None:
            existing.value = value
        if unit is not None:
            existing.unit = unit

    # -- serialization -------------------------------------------------------
    def to_dict(self) -> dict:
        def f(x: Field | None):
            return x.to_dict() if x else None

        return {
            "schema_version": SCHEMA_VERSION,
            "requirement_text": self.requirement_text,
            "target": {"board": f(self.target.board), "mcu": f(self.target.mcu)},
            "devices": [
                {"name": f(d.name), "role": f(d.role), "interface": f(d.interface),
                 "address": f(d.address), "pin": f(d.pin)}
                for d in self.devices
            ],
            "behaviors": [
                {"id": b.id,
                 "trigger": {"source": f(b.trigger.source),
                             "comparator": f(b.trigger.comparator),
                             "threshold": f(b.trigger.threshold),
                             "unit": f(b.trigger.unit)},
                 "action": f(b.action)}
                for b in self.behaviors
            ],
            "constraints": [
                {"name": c.name, "value": f(c.value), "unit": f(c.unit)}
                for c in self.constraints
            ],
            "failure_behavior": f(self.failure_behavior),
            "output_target": f(self.output_target),
            "open_questions": [q.to_dict() for q in self.open_questions],
            "dropped": list(self.dropped),
            "notes": list(self.notes),
        }

    @staticmethod
    def from_dict(data: dict) -> "ApplicationSpec":
        def f(x) -> Field | None:
            if not x:
                return None
            # Field.__post_init__ re-runs the provenance guard, so a spec that
            # was tampered with on disk cannot be loaded back in.
            return Field(value=x.get("value"), provenance=x.get("provenance"),
                         evidence=x.get("evidence", ""))

        t = data.get("target") or {}
        spec = ApplicationSpec(
            requirement_text=data.get("requirement_text", ""),
            target=Target(board=f(t.get("board")), mcu=f(t.get("mcu"))),
            devices=[
                Device(name=f(d.get("name")), role=f(d.get("role")),
                       interface=f(d.get("interface")), address=f(d.get("address")),
                       pin=f(d.get("pin")))
                for d in data.get("devices") or []
            ],
            behaviors=[
                Behavior(
                    id=b.get("id") or f"b{i + 1}",
                    trigger=Trigger(
                        source=f((b.get("trigger") or {}).get("source")),
                        comparator=f((b.get("trigger") or {}).get("comparator")),
                        threshold=f((b.get("trigger") or {}).get("threshold")),
                        unit=f((b.get("trigger") or {}).get("unit")),
                    ),
                    action=f(b.get("action")),
                )
                for i, b in enumerate(data.get("behaviors") or [])
            ],
            constraints=[
                Constraint(name=c.get("name", ""), value=f(c.get("value")),
                           unit=f(c.get("unit")))
                for c in data.get("constraints") or []
            ],
            failure_behavior=f(data.get("failure_behavior")),
            output_target=f(data.get("output_target")),
            dropped=list(data.get("dropped") or []),
            notes=list(data.get("notes") or []),
        )
        spec.open_questions = detect_ambiguities(spec)
        return spec


# ---------------------------------------------------------------------------
# grounding: does the user's text actually say this?
# ---------------------------------------------------------------------------

# Superscripts written as escapes so this file stays pure ASCII (a Windows
# cp1252 console chokes on the literals when pytest echoes a failing value).
# "I²C" is how humans write I2C, so it must fold to the same tokens.
_SUPERSCRIPT = {chr(0xB2): "2", chr(0xB3): "3", chr(0xB9): "1"}
_STOPWORDS = {"THE", "A", "AN", "OF", "TO", "AND", "THEN", "THAT", "PLEASE",
              "SHOULD", "MUST", "WILL", "IT", "IS", "BE", "PER"}


def _fold(text: str) -> str:
    return "".join(_SUPERSCRIPT.get(ch, ch) for ch in str(text))


def _tokenize(text: Any) -> list[str]:
    """Words and numbers, uppercased, punctuation dropped. 'I²C' -> I,2,C so
    it matches a stated 'I2C'; '0x76' -> 0,X,76; '30.5' stays one token."""
    return [t.upper() for t in re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", _fold(text))]


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Contiguous token subsequence."""
    if not needle:
        return False
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def _value_variants(value: Any) -> list[list[str]]:
    out = [_tokenize(value)]
    if isinstance(value, float) and value.is_integer():
        out.append(_tokenize(int(value)))
    if isinstance(value, (int, float)):
        out.append(_tokenize(f"{value}"))
    return [v for v in out if v]


_BUS_ALIASES = {
    "I2C": ("I2C", "IIC", "TWI"),
    "SPI": ("SPI", "QSPI"),
    "UART": ("UART", "USART", "SERIAL"),
    "1-Wire": ("1WIRE", "ONEWIRE", "1 WIRE"),
    "GPIO": ("GPIO", "DIGITAL OUTPUT", "DIGITAL INPUT", "DIGITAL PIN", "PIN"),
    "ANALOG": ("ANALOG", "ANALOGUE", "ADC"),
}

_COMPARATOR_PHRASES = {
    ">": (["ABOVE"], ["GREATER", "THAN"], ["EXCEEDS"], ["EXCEED"], ["OVER"],
          ["HIGHER", "THAN"], ["MORE", "THAN"], ["RISES", "ABOVE"], ["HOTTER"]),
    ">=": (["AT", "LEAST"], ["OR", "MORE"], ["NO", "LESS", "THAN"],
           ["GREATER", "OR", "EQUAL"]),
    "<": (["BELOW"], ["LESS", "THAN"], ["UNDER"], ["LOWER", "THAN"],
          ["DROPS", "BELOW"], ["FALLS", "BELOW"], ["COLDER"]),
    "<=": (["AT", "MOST"], ["OR", "LESS"], ["NO", "MORE", "THAN"],
           ["LESS", "OR", "EQUAL"]),
    "==": (["EQUALS"], ["EQUAL", "TO"], ["EXACTLY"]),
    "!=": (["NOT", "EQUAL"], ["DIFFERS"], ["OTHER", "THAN"]),
}

_UNIT_ALIASES = {
    "C": ("C", "CELSIUS", "DEGC", "DEG C", "DEGREES C", "DEGREES CELSIUS"),
    "F": ("F", "FAHRENHEIT", "DEGF"),
    "%": ("%", "PERCENT", "RH", "PERCENT RH"),
    "HZ": ("HZ", "HERTZ"),
    "MS": ("MS", "MILLISECOND", "MILLISECONDS"),
    "S": ("S", "SEC", "SECS", "SECOND", "SECONDS"),
    "HPA": ("HPA", "HECTOPASCAL", "MBAR", "MILLIBAR"),
    "PA": ("PA", "PASCAL", "PASCALS"),
    "V": ("V", "VOLT", "VOLTS"),
    "LUX": ("LUX", "LX"),
}


def canonical_interface(value: Any) -> str | None:
    """Map a stated interface to our closed vocabulary, or None when it is not
    an interface at all. Reuses V1.6's `canonical_bus` for the bus tokens so
    exactly one table decides what 'I2C' means across the codebase."""
    squashed = re.sub(r"[^A-Za-z0-9]", "", _fold(value)).upper()
    if not squashed:
        return None
    if squashed.startswith("GPIO") or squashed.startswith("DIGITAL"):
        return "GPIO"
    if squashed.startswith("ANALOG") or squashed.startswith("ADC"):
        return "ANALOG"
    return canonical_bus(str(value))


def canonical_unit(value: Any) -> str:
    squashed = re.sub(r"[^A-Za-z0-9%]", "", _fold(value)).upper()
    for canon, aliases in _UNIT_ALIASES.items():
        if squashed in {re.sub(r"[^A-Za-z0-9%]", "", a).upper() for a in aliases}:
            return canon
    return squashed


def _verbatim(evidence: str, text: str) -> bool:
    """The quoted span must really occur in the user's requirement. Compared on
    tokens so quoting is robust to whitespace/punctuation but NOT to invention —
    a model that manufactures a quote fails here before its value is ever read."""
    ev = _tokenize(evidence)
    return bool(ev) and _contains(_tokenize(text), ev)


def _grounded(value: Any, evidence: str, kind: str) -> bool:
    """Is `value` actually supported by `evidence`? Per-kind, because 'above'
    grounds '>' while nothing about the string '>' appears in the user's text."""
    ev_tokens = _tokenize(evidence)
    if not ev_tokens:
        return False

    if kind == "comparator":
        op = str(value).strip()
        if op not in COMPARATORS:
            return False
        raw = re.sub(r"\s+", "", _fold(evidence))
        if op in ("<=", ">=", "==", "!=") and op in raw:
            return True
        if op in ("<", ">") and op in raw and (op + "=") not in raw:
            return True
        return any(_contains(ev_tokens, list(p))
                   for p in _COMPARATOR_PHRASES.get(op, ()))

    if kind == "interface":
        canon = canonical_interface(value)
        if canon is None:
            return False
        for alias in _BUS_ALIASES.get(canon, (canon,)):
            if _contains(ev_tokens, _tokenize(alias)):
                return True
        return False

    if kind == "unit":
        canon = canonical_unit(value)
        for alias in _UNIT_ALIASES.get(canon, (str(value),)):
            if _contains(ev_tokens, _tokenize(alias)):
                return True
        return False

    if kind == "free_text":
        # Prose (a role, an action, a failure behavior) is allowed to drop
        # filler words the user wrote, but may not ADD a content word they did
        # not: every non-stopword token of the value must appear in the quote.
        vt = [t for t in _tokenize(value) if t not in _STOPWORDS]
        return bool(vt) and set(vt) <= set(ev_tokens)

    if kind == "number":
        try:
            float(str(value))
        except (TypeError, ValueError):
            return False

    # identifiers and numbers: the value must appear verbatim in the quote.
    return any(_contains(ev_tokens, v) for v in _value_variants(value))


# ---------------------------------------------------------------------------
# LLM extraction, contained
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a requirements analyst for an embedded-systems code \
generator. You convert a user's natural-language requirement into a structured \
application spec.

THE ONE RULE: NEVER INVENT A REQUIREMENT. You EXTRACT what the user said and you \
ASK about everything else. You are not allowed to complete the picture, fill a \
sensible default, or normalise a vague phrase into a specific part. If the user \
wrote "a temperature sensor", the device name is NOT "BME280" — it is unknown, \
and it is a question. If the user wrote "an STM32 board", the board is NOT \
"Nucleo-F411RE". If the user wrote "when it gets hot", there is NO threshold.

Every value you extract MUST be accompanied by "evidence": a VERBATIM span \
copied from the user's requirement text that states that value. Evidence is \
checked mechanically against the user's text and against your value; a value \
whose evidence does not literally support it is DISCARDED and turned into a \
question, so guessing gains you nothing. If you cannot quote it, omit the field.

Omit any field the user did not state. Do NOT emit nulls, empty strings, "TBD", \
"unknown", or placeholders. Omission is the correct, expected answer.

Return ONLY a JSON object of this shape (every leaf is {"value": ..., \
"evidence": "verbatim quote"}), omitting anything not stated:

{
  "target": {"board": LEAF, "mcu": LEAF},
  "devices": [{"name": LEAF, "role": LEAF, "interface": LEAF, "address": LEAF,
               "pin": LEAF}],
  "behaviors": [{"trigger": {"source": LEAF, "comparator": LEAF,
                             "threshold": LEAF, "unit": LEAF},
                 "action": LEAF}],
  "constraints": [{"name": "sample_rate", "value": LEAF, "unit": LEAF}],
  "failure_behavior": LEAF,
  "output_target": LEAF,
  "questions": [{"field": "devices[0].interface", "text": "..."}]
}

"interface" must be one of I2C, SPI, GPIO, ANALOG, UART, 1-WIRE. "comparator" \
must be one of >, >=, <, <=, ==, !=. "threshold" must be a bare number. \
Constraint "name" must be a key like sample_rate, timeout, baud_rate.

You MAY add entries to "questions" for anything ambiguous that the fields above \
cannot express. Every question must be SPECIFIC and answerable in one line \
("Which I2C address is the BME280 strapped to?"), never vague ("Any other \
details?", "Can you clarify?"). Never put a value in a question as a suggestion.

Do not output provenance, confidence, or commentary — only the JSON object."""


def _extraction_prompt(text: str, spec: ApplicationSpec | None) -> str:
    parts = ["USER REQUIREMENT (the ONLY source of truth — quote from it):",
             "---", text.strip(), "---"]
    if spec is not None and (spec.devices or spec.target.board or spec.behaviors):
        parts += [
            "",
            "ALREADY ESTABLISHED (do not re-extract; extract only what is NEW in "
            "the requirement text above):",
            json.dumps(_established(spec), indent=2),
        ]
    parts += ["", "Return the JSON object now."]
    return "\n".join(parts)


def _established(spec: ApplicationSpec) -> dict:
    d = spec.to_dict()
    return {k: d[k] for k in ("target", "devices", "behaviors", "constraints",
                              "failure_behavior", "output_target")}


def _leaf(raw: Any, kind: str, text: str, path: str,
          dropped: list[dict]) -> Field | None:
    """Turn one model leaf into a Field, or into nothing at all.

    This is where the model's authority ends. It supplies a candidate value and
    a quote; it does NOT supply provenance (assigned here) and it does not get
    the benefit of the doubt. Four ways to be discarded: not a leaf object, an
    empty/placeholder value, a fabricated quote, a quote that does not support
    the value."""
    if not isinstance(raw, dict):
        return None
    value = raw.get("value")
    evidence = raw.get("evidence") or ""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str) and value.strip().lower() in {
        "tbd", "unknown", "n/a", "na", "none", "null", "todo", "?", "-"
    }:
        dropped.append({"field": path, "reason": "placeholder value discarded"})
        return None
    if not isinstance(evidence, str) or not _verbatim(evidence, text):
        dropped.append({
            "field": path,
            "reason": "no verbatim evidence in the requirement text — value "
                      "discarded and asked instead",
        })
        return None
    if not _grounded(value, evidence, kind):
        dropped.append({
            "field": path,
            "reason": "quoted text does not state this value — value discarded "
                      "and asked instead",
        })
        return None
    if isinstance(value, str):
        value = value.strip()
    if kind == "interface":
        value = canonical_interface(value) or value
    if kind == "unit":
        value = canonical_unit(value) or value
    if kind == "number":
        value = float(value) if "." in str(value) else int(float(str(value)))
    # provenance is ASSIGNED here; whatever the model claimed is ignored.
    return user_field(value, evidence.strip())


def extract(text: str, provider, spec: ApplicationSpec | None = None
            ) -> tuple[ApplicationSpec, list[Question]]:
    """Run the model over `text` and fold every value that survives grounding
    into `spec` (a fresh spec when None). Returns (spec, model-proposed
    questions). Never raises on a bad model response — a provider that returns
    junk simply extracts nothing, which means everything becomes a question.
    Degrading to 'ask the user' is always safe; degrading to 'assume' is not."""
    spec = spec or ApplicationSpec()
    spec.requirement_text = (
        f"{spec.requirement_text}\n{text}".strip() if spec.requirement_text
        else text.strip()
    )
    try:
        raw = provider.complete_json(SYSTEM_PROMPT, _extraction_prompt(text, spec))
    except Exception as exc:  # provider/network/JSON failure
        spec.notes.append(
            f"extraction unavailable ({type(exc).__name__}: {exc}); every field "
            "will be asked rather than assumed"
        )
        return spec, []
    if not isinstance(raw, dict):
        spec.notes.append("model returned a non-object; nothing extracted")
        return spec, []

    dropped: list[dict] = []

    tgt = raw.get("target") if isinstance(raw.get("target"), dict) else {}
    board = _leaf(tgt.get("board"), "identifier", text, "target.board", dropped)
    mcu = _leaf(tgt.get("mcu"), "identifier", text, "target.mcu", dropped)
    if board:
        spec.target.board = board
    if mcu:
        spec.target.mcu = mcu

    for i, d in enumerate(raw.get("devices") or []):
        if not isinstance(d, dict):
            continue
        base = f"devices[{i}]"
        dev = Device(
            name=_leaf(d.get("name"), "identifier", text, f"{base}.name", dropped),
            role=_leaf(d.get("role"), "free_text", text, f"{base}.role", dropped),
            interface=_leaf(d.get("interface"), "interface", text,
                            f"{base}.interface", dropped),
            address=_leaf(d.get("address"), "identifier", text, f"{base}.address",
                          dropped),
            pin=_leaf(d.get("pin"), "identifier", text, f"{base}.pin", dropped),
        )
        if any([dev.name, dev.role, dev.interface, dev.address, dev.pin]):
            _merge_device(spec, dev)

    for i, b in enumerate(raw.get("behaviors") or []):
        if not isinstance(b, dict):
            continue
        base = f"behaviors[{i}]"
        t = b.get("trigger") if isinstance(b.get("trigger"), dict) else {}
        beh = Behavior(
            id=f"b{len(spec.behaviors) + 1}",
            trigger=Trigger(
                source=_leaf(t.get("source"), "free_text", text,
                             f"{base}.trigger.source", dropped),
                comparator=_leaf(t.get("comparator"), "comparator", text,
                                 f"{base}.trigger.comparator", dropped),
                threshold=_leaf(t.get("threshold"), "number", text,
                                f"{base}.trigger.threshold", dropped),
                unit=_leaf(t.get("unit"), "unit", text, f"{base}.trigger.unit",
                           dropped),
            ),
            action=_leaf(b.get("action"), "free_text", text, f"{base}.action",
                         dropped),
        )
        if any([beh.trigger.source, beh.trigger.comparator, beh.trigger.threshold,
                beh.trigger.unit, beh.action]):
            spec.behaviors.append(beh)

    for i, c in enumerate(raw.get("constraints") or []):
        if not isinstance(c, dict) or not str(c.get("name") or "").strip():
            continue
        name = re.sub(r"[^a-z0-9_]", "_", str(c["name"]).strip().lower())
        base = f"constraints[{i}]"
        value = _leaf(c.get("value"), "number", text, f"{base}.value", dropped)
        unit = _leaf(c.get("unit"), "unit", text, f"{base}.unit", dropped)
        if value or unit:
            spec.set_constraint(name, value, unit)

    fb = _leaf(raw.get("failure_behavior"), "free_text", text, "failure_behavior",
               dropped)
    if fb:
        spec.failure_behavior = fb
    ot = _leaf(raw.get("output_target"), "free_text", text, "output_target", dropped)
    if ot:
        spec.output_target = ot

    spec.dropped.extend(dropped)
    return spec, _model_questions(raw.get("questions"))


def _merge_device(spec: ApplicationSpec, dev: Device) -> None:
    """Fold an extracted device into the spec, matching on part name so a second
    message about the same device fills gaps instead of duplicating it."""
    key = _tokenize(dev.name.value) if dev.name else None
    if key:
        for existing in spec.devices:
            if existing.name and _tokenize(existing.name.value) == key:
                for attr in ("role", "interface", "address", "pin"):
                    if getattr(dev, attr) is not None:
                        setattr(existing, attr, getattr(dev, attr))
                return
    spec.devices.append(dev)


_VAGUE = (
    "anything else", "any other", "more detail", "more details", "clarify",
    "elaborate", "tell me more", "additional information", "further information",
    "what else", "any thoughts", "is that correct", "please specify",
)
MAX_MODEL_QUESTIONS = 6


def _model_questions(raw: Any) -> list[Question]:
    """Screen the model's proposed questions. It may surface nuance the rules
    miss, but a vague question is worse than none — it makes the user do the
    analysis. Rejected: too short, not a question, generic filler."""
    out: list[Question] = []
    for i, q in enumerate(raw or []):
        if not isinstance(q, dict):
            continue
        text = str(q.get("text") or "").strip()
        low = text.lower()
        if len(text) < 12 or "?" not in text or any(v in low for v in _VAGUE):
            continue
        field = str(q.get("field") or "").strip() or f"model[{i}]"
        out.append(Question(id=f"q:model:{field}", field=field, kind="model_proposed",
                            text=text, blocking=False))
        if len(out) >= MAX_MODEL_QUESTIONS:
            break
    return out


# ---------------------------------------------------------------------------
# deterministic ambiguity detection
# ---------------------------------------------------------------------------

_GENERIC = re.compile(
    r"SENSOR|MODULE|DEVICE|CHIP|PART|BOARD|SOMETHING|THING|DISPLAY|SCREEN|"
    r"RELAY|MOTOR|LED|BUZZER|PUMP|FAN|VALVE|TBD|UNKNOWN|TODO"
)


# The user's escape hatch for a device that genuinely has no part number (a
# relay coil on a GPIO, an LED). Only honoured on an ANSWER — we never conclude
# it ourselves.
_NO_PART = re.compile(r"PLAIN\s*GPIO|NO\s*PART|NO\s*CHIP|DISCRETE|BARE\s*GPIO",
                      re.IGNORECASE)


def is_specific_part(name: Any) -> bool:
    """Does this read as an orderable part number rather than a category?

    'BME280' yes, 'SSD1306' yes, 'a temp sensor' no, 'relay' no. The rule is
    structural (letters + a digit, no category word), NOT a lookup against a
    parts list — a lookup would let us 'resolve' a category to a part, which is
    exactly the invention this module exists to prevent."""
    squashed = re.sub(r"[^A-Za-z0-9]", "", _fold(name)).upper()
    if len(squashed) < 4 or _GENERIC.search(squashed):
        return False
    return bool(re.match(r"^[A-Z]{1,6}[A-Z0-9]*\d", squashed))


def _part_settled(f: Field | None) -> bool:
    """A device name we can build against: a real part number, or an explicit
    'this has no part number' from a human answering the question. The second
    branch requires provenance 'asked' — the same phrase appearing in the
    original prose is not a confirmation, it is still worth asking about."""
    if f is None:
        return False
    if is_specific_part(f.value):
        return True
    return f.provenance == "asked" and bool(_NO_PART.search(str(f.value)))


def _q(field: str, kind: str, text: str, options: list[str] | None = None,
       blocking: bool = True) -> Question:
    return Question(id=f"q:{field}", field=field, kind=kind, text=text,
                    options=options or [], blocking=blocking)


def _device_label(dev: Device, index: int) -> str:
    if dev.name:
        return str(dev.name.value)
    if dev.role:
        return str(dev.role.value)
    return f"device #{index + 1}"


def detect_ambiguities(spec: ApplicationSpec) -> list[Question]:
    """Every question this spec still needs answered, derived purely from what
    is present and absent. Deterministic: no model, no randomness, same spec ->
    same questions. This is the function `assert_spec_complete` trusts."""
    qs: list[Question] = []

    if spec.target.board is None:
        qs.append(_q("target.board", MISSING_TARGET,
                     "Which board are you targeting? Give the exact board name "
                     "(for example 'Nucleo-F411RE' or 'Arduino Uno R3')."))
    if spec.target.mcu is None:
        qs.append(_q("target.mcu", MISSING_TARGET,
                     "Which MCU part is on that board? Give the full part number "
                     "(for example 'STM32F411RET6') - we will not infer it from "
                     "the board name."))

    if not spec.devices:
        qs.append(_q("devices", MISSING_DEVICE,
                     "Which devices does the application talk to? List each one "
                     "by part number (sensors, displays, actuators)."))

    for i, dev in enumerate(spec.devices):
        label = _device_label(dev, i)
        base = f"devices[{i}]"
        if dev.name is None:
            qs.append(_q(f"{base}.name", AMBIGUOUS_CHIP,
                         f"What is the exact part number of the {label}?"))
        elif not _part_settled(dev.name):
            qs.append(_q(f"{base}.name", AMBIGUOUS_CHIP,
                         f"'{dev.name.value}' names a category, not a part. Which "
                         "exact part is it (for example BME280, SHT31, DS18B20)? "
                         "If it is a plain GPIO-driven output with no chip to "
                         "drive, answer 'plain GPIO output'."))
        if dev.interface is None:
            qs.append(_q(f"{base}.interface", MISSING_INTERFACE,
                         f"How is the {label} connected - which interface?",
                         options=list(INTERFACES)))
        if dev.role is None:
            qs.append(_q(f"{base}.role", MISSING_ROLE,
                         f"What is the {label} for in this application (what does "
                         "it measure, display or actuate)?"))
        if dev.interface is not None and dev.pin is None and \
                str(dev.interface.value) in ("GPIO", "ANALOG"):
            qs.append(_q(f"{base}.pin", MISSING_PIN,
                         f"Which MCU pin is the {label} wired to (for example "
                         "'PB5')?"))
        # An I2C part is addressed ON THE WIRE, so without its 7-bit address it
        # cannot be read: the read plan cannot be derived and the build ends
        # with no firmware. Treating the address as optional let a spec look
        # COMPLETE while being unbuildable — the intake said nothing and the
        # pipeline silently produced nothing, which is precisely the quiet
        # failure this project exists to prevent. So ask for it.
        # (SPI selects by chip-select and correctly needs no address.)
        if dev.interface is not None and dev.address is None and \
                str(dev.interface.value).upper() == "I2C":
            qs.append(_q(f"{base}.address", MISSING_ADDRESS,
                         f"What is the {label}'s 7-bit I2C address (for example "
                         "'0x77')? Without it the device cannot be read."))

    if not spec.behaviors:
        qs.append(_q("behaviors", MISSING_BEHAVIOR,
                     "What should the application actually do? Describe it as "
                     "trigger and action (for example 'when temperature is above "
                     "30 C, turn the relay on')."))

    for i, beh in enumerate(spec.behaviors):
        base = f"behaviors[{i}]"
        ref = f"behavior {beh.id}"
        if beh.action:
            ref = f"'{beh.action.value}'"
        elif beh.trigger.source:
            ref = f"the {beh.trigger.source.value} behavior"
        if beh.trigger.source is None:
            qs.append(_q(f"{base}.trigger.source", MISSING_TRIGGER_SOURCE,
                         f"Which measured value triggers {ref} (for example "
                         "temperature, humidity, pressure)?"))
        if beh.trigger.comparator is None:
            qs.append(_q(f"{base}.trigger.comparator", MISSING_COMPARATOR,
                         f"Does {ref} trigger when the reading goes above or below "
                         "the threshold?", options=list(COMPARATORS)))
        if beh.trigger.threshold is None:
            qs.append(_q(f"{base}.trigger.threshold", MISSING_THRESHOLD,
                         f"What threshold value triggers {ref}? Give the number "
                         "and its unit (for example '30 C')."))
        elif beh.trigger.unit is None:
            qs.append(_q(f"{base}.trigger.unit", MISSING_UNITS,
                         f"What unit is the threshold {beh.trigger.threshold.value} "
                         f"for {ref} expressed in (for example C, %, hPa)?"))
        if beh.action is None:
            qs.append(_q(f"{base}.action", MISSING_ACTION,
                         "What should happen when that trigger fires?"))

    rate = spec.constraint("sample_rate")
    if spec.devices and (rate is None or rate.value is None):
        qs.append(_q("constraints.sample_rate", MISSING_SAMPLE_RATE,
                     "How often should the application sample the sensors? Give a "
                     "rate or an interval (for example '2 Hz' or 'every 500 ms')."))

    if spec.failure_behavior is None:
        qs.append(_q("failure_behavior", MISSING_FAILURE_BEHAVIOR,
                     "What should the application do if a device read fails or the "
                     "sensor stops responding (hold last value, retry, fail safe, "
                     "log and continue)?"))

    if spec.output_target is None:
        qs.append(_q("output_target", MISSING_OUTPUT_TARGET,
                     "What should we produce - an Arduino sketch, a PlatformIO "
                     "project, or a CMake project?", options=list(OUTPUT_TARGETS)))

    return qs


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def analyze_requirement(text: str, provider=None, spec: ApplicationSpec | None = None
                        ) -> tuple[ApplicationSpec, list[Question]]:
    """Natural-language requirement -> (partial spec, clarifying questions).

    The spec contains ONLY what the user's own words support; everything else
    comes back as a specific, answerable question. Call again with `spec=` to
    fold in a follow-up message, or use `answer_questions` for direct answers.

    `provider` defaults to `make_provider()` so the configured backend
    (EMBEDDPILOT_PROVIDER=gemini on a free-tier model) is used with no vendor
    hard-coded here; tests inject MockProvider. If no provider can be built we
    still return a spec - an empty one, with every field as a question, which is
    the honest degradation."""
    if provider is None:
        try:
            from generation.provider import make_provider

            provider = make_provider()
        except Exception as exc:
            spec = spec or ApplicationSpec()
            spec.requirement_text = (
                f"{spec.requirement_text}\n{text}".strip()
                if spec.requirement_text else text.strip()
            )
            spec.notes.append(
                f"no LLM provider available ({exc}); nothing was extracted and "
                "every field is being asked"
            )
            spec.open_questions = detect_ambiguities(spec)
            return spec, list(spec.open_questions)

    spec, proposed = extract(text, provider, spec)
    questions = detect_ambiguities(spec)
    known = {q.field for q in questions}
    # A model question is only allowed to ADD nuance about a field that is
    # already unknown. It can never contradict, replace or silence a rule-derived
    # question, and it is non-blocking, so the model cannot hold generation
    # hostage either.
    for q in proposed:
        if q.field in known or q.id in {x.id for x in questions}:
            continue
        questions.append(q)
    spec.open_questions = questions
    return spec, list(questions)


# ---------------------------------------------------------------------------
# answering
# ---------------------------------------------------------------------------

_DEGREE = chr(0xB0)
_NUM_UNIT = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*([A-Za-z%" + _DEGREE + r"/]+(?:\s*[A-Za-z]+)?)?")


def _parse_number_unit(answer: str) -> tuple[float | int | None, str | None]:
    m = _NUM_UNIT.search(_fold(answer))
    if not m:
        return None, None
    raw = m.group(1)
    value = float(raw) if "." in raw else int(raw)
    unit = (m.group(2) or "").strip() or None
    return value, unit


def _comparator_from_answer(answer: str) -> str | None:
    a = answer.strip()
    if a in COMPARATORS:
        return a
    raw = re.sub(r"\s+", "", _fold(a))
    for op in (">=", "<=", "==", "!="):
        if op in raw:
            return op
    toks = _tokenize(a)
    for op, phrases in _COMPARATOR_PHRASES.items():
        if any(_contains(toks, list(p)) for p in phrases):
            return op
    if ">" in raw:
        return ">"
    if "<" in raw:
        return "<"
    return None


_IDX = re.compile(r"^(\w+)\[(\d+)\]\.(.+)$")


def answer_questions(spec: ApplicationSpec, answers: dict[str, str]
                     ) -> tuple[ApplicationSpec, list[Question]]:
    """Apply the user's answers and recompute what is still missing.

    Answers are applied DETERMINISTICALLY, without the model: the user's answer
    is the value, so there is nothing to infer. An answer that does not parse
    into the shape the field needs (a threshold that is not a number, a
    comparator that is neither above nor below) is NOT coerced or guessed - the
    question stays open and is re-asked. Accepting a value we could not read
    would be inventing one."""
    by_id = {q.id: q for q in spec.open_questions}
    unparsed: dict[str, str] = {}

    for qid, answer in (answers or {}).items():
        q = by_id.get(qid)
        if q is None or not str(answer or "").strip():
            continue
        if not _apply_answer(spec, q, str(answer).strip()):
            unparsed[q.field] = str(answer).strip()

    remaining = detect_ambiguities(spec)
    for q in remaining:
        if q.field in unparsed:
            q.text = (f"That answer ({unparsed[q.field]!r}) could not be read as a "
                      f"value for this field, so it was not recorded. {q.text}")
    # model-proposed questions are non-blocking and survive until answered
    answered = set(answers or {})
    remaining += [q for q in spec.open_questions
                  if q.kind == "model_proposed" and q.id not in answered]
    spec.open_questions = remaining
    return spec, list(remaining)


def _apply_answer(spec: ApplicationSpec, q: Question, answer: str) -> bool:
    """Set the field `q` asks about from `answer`. False = could not parse."""
    path, qid = q.field, q.id

    def fld(value: Any) -> Field:
        return asked_field(value, qid, answer)

    if path == "target.board":
        spec.target.board = fld(answer)
        return True
    if path == "target.mcu":
        spec.target.mcu = fld(answer)
        return True

    if path == "devices":
        # "BME280, SSD1306" -> two devices, each of which now gets its own
        # interface/role questions. Names are NOT validated as part numbers here;
        # detect_ambiguities re-asks for anything still generic.
        names = [n.strip() for n in re.split(r"[,;]|\band\b", answer) if n.strip()]
        if not names:
            return False
        for n in names:
            _merge_device(spec, Device(name=fld(n)))
        return True

    if path == "behaviors":
        # A free-text behavior answer cannot be split into trigger/action here
        # without guessing which half is which, so it is recorded as the action
        # and the trigger parts are asked individually.
        spec.behaviors.append(Behavior(id=f"b{len(spec.behaviors) + 1}",
                                       action=fld(answer)))
        return True

    if path == "constraints.sample_rate":
        value, unit = _parse_number_unit(answer)
        if value is None:
            return False
        spec.set_constraint("sample_rate", fld(value),
                            fld(unit) if unit else None)
        return True

    if path == "failure_behavior":
        spec.failure_behavior = fld(answer)
        return True

    if path == "output_target":
        spec.output_target = fld(answer)
        return True

    m = _IDX.match(path)
    if not m:
        return False
    collection, index, rest = m.group(1), int(m.group(2)), m.group(3)

    if collection == "devices":
        if index >= len(spec.devices):
            return False
        dev = spec.devices[index]
        if rest == "name":
            dev.name = fld(answer)
            return True
        if rest == "role":
            dev.role = fld(answer)
            return True
        if rest == "pin":
            dev.pin = fld(answer)
            return True
        if rest == "address":
            dev.address = fld(answer)
            return True
        if rest == "interface":
            canon = canonical_interface(answer)
            if canon is None or canon not in INTERFACES:
                return False
            dev.interface = fld(canon)
            return True
        return False

    if collection == "behaviors":
        if index >= len(spec.behaviors):
            return False
        beh = spec.behaviors[index]
        if rest == "action":
            beh.action = fld(answer)
            return True
        if rest == "trigger.source":
            beh.trigger.source = fld(answer)
            return True
        if rest == "trigger.comparator":
            op = _comparator_from_answer(answer)
            if op is None:
                return False
            beh.trigger.comparator = fld(op)
            return True
        if rest == "trigger.threshold":
            value, unit = _parse_number_unit(answer)
            if value is None:
                return False
            beh.trigger.threshold = fld(value)
            # "30 C" answers the unit question too; a bare "30" leaves it open.
            if unit and beh.trigger.unit is None:
                beh.trigger.unit = fld(canonical_unit(unit))
            return True
        if rest == "trigger.unit":
            beh.trigger.unit = fld(canonical_unit(answer))
            return True
        return False

    return False


# ---------------------------------------------------------------------------
# the contract: no spec line => no code
# ---------------------------------------------------------------------------

def _require(label: str, f: Field | None) -> None:
    """The application-scale twin of `inputs._check_field`."""
    if f is None:
        raise SpecIncompleteError(
            f"{label} is missing from the spec — it was never stated and the "
            "clarifying question about it has not been answered. EmbeddPilot "
            "does not generate from an unanswered question."
        )
    if f.value is None or (isinstance(f.value, str) and not f.value.strip()):
        raise SpecIncompleteError(f"{label} is empty in the spec.")
    if f.provenance not in ALLOWED_PROVENANCE:
        why = FORBIDDEN_PROVENANCE.get(str(f.provenance).lower())
        raise SpecProvenanceError(
            f"{label} = {f.value!r} has provenance {f.provenance!r}"
            f"{f' ({why})' if why else ''} — refusing to generate from a "
            "requirement the user never stated. Only 'user' and 'asked' exist."
        )
    if not str(f.evidence or "").strip():
        raise SpecProvenanceError(
            f"{label} = {f.value!r} carries provenance {f.provenance!r} but no "
            "evidence — there is nothing to trace it back to. A value with no "
            "receipt is an invented value."
        )


def assert_spec_complete(spec: ApplicationSpec) -> None:
    """Raise unless every required field is present, provenanced and evidenced,
    and no blocking question is outstanding. Returns None when the spec is a
    valid contract to build against.

    This is `assert_input_provenance` at application scale, and it enforces the
    V2 rule literally: **no spec line => no code.** Call it at the API boundary
    AND again where generation is assembled (belt-and-suspenders, exactly as V1.6
    does), so a spec can never reach a generator by any path without passing."""
    if not isinstance(spec, ApplicationSpec):
        raise SpecError(f"expected an ApplicationSpec, got {type(spec).__name__}")

    # Recomputed, never read from spec.open_questions: a caller that clears the
    # list must not thereby acquire permission to build.
    outstanding = [q for q in detect_ambiguities(spec) if q.blocking]
    if outstanding:
        first = outstanding[0]
        raise SpecIncompleteError(
            f"{len(outstanding)} clarifying question(s) are unanswered — "
            f"generation is blocked. First: [{first.kind}] {first.text} "
            f"(field: {first.field})"
        )

    _require("Target board", spec.target.board)
    _require("Target MCU", spec.target.mcu)

    if not spec.devices:
        raise SpecIncompleteError("The spec declares no devices.")
    for i, dev in enumerate(spec.devices):
        label = _device_label(dev, i)
        _require(f"Device {i + 1} part number", dev.name)
        _require(f"Device '{label}' interface", dev.interface)
        _require(f"Device '{label}' role", dev.role)
        iface = canonical_interface(dev.interface.value)
        if iface is None or iface not in INTERFACES:
            raise SpecIncompleteError(
                f"Device '{label}' interface {dev.interface.value!r} is not one "
                f"of {', '.join(INTERFACES)}."
            )
        if iface in ("GPIO", "ANALOG"):
            _require(f"Device '{label}' pin", dev.pin)

    if not spec.behaviors:
        raise SpecIncompleteError("The spec declares no behaviors.")
    for beh in spec.behaviors:
        _require(f"Behavior {beh.id} trigger source", beh.trigger.source)
        _require(f"Behavior {beh.id} comparator", beh.trigger.comparator)
        _require(f"Behavior {beh.id} threshold", beh.trigger.threshold)
        _require(f"Behavior {beh.id} threshold unit", beh.trigger.unit)
        _require(f"Behavior {beh.id} action", beh.action)
        if str(beh.trigger.comparator.value) not in COMPARATORS:
            raise SpecIncompleteError(
                f"Behavior {beh.id} comparator "
                f"{beh.trigger.comparator.value!r} is not one of "
                f"{', '.join(COMPARATORS)}."
            )
        try:
            float(str(beh.trigger.threshold.value))
        except (TypeError, ValueError):
            raise SpecIncompleteError(
                f"Behavior {beh.id} threshold "
                f"{beh.trigger.threshold.value!r} is not a number."
            ) from None

    rate = spec.constraint("sample_rate")
    _require("Sample rate", rate.value if rate else None)
    _require("Failure behavior", spec.failure_behavior)
    _require("Output target", spec.output_target)


def spec_line_ids(spec: ApplicationSpec) -> list[str]:
    """Every addressable line of the spec contract, as stable ids.

    V2_PLAN 4b(b): "every generated file traces to a spec line; no spec line =>
    no code." This is the id space that traceability is expressed in — a
    generated artifact that cannot name one of these has no requirement behind
    it."""
    ids = ["target.board", "target.mcu"]
    for i, dev in enumerate(spec.devices):
        name = str(dev.name.value) if dev.name else f"device{i + 1}"
        ids += [f"device.{name}.interface", f"device.{name}.role"]
        if dev.pin:
            ids.append(f"device.{name}.pin")
    for beh in spec.behaviors:
        ids += [f"behavior.{beh.id}.trigger", f"behavior.{beh.id}.action"]
    ids += [f"constraint.{c.name}" for c in spec.constraints]
    if spec.failure_behavior:
        ids.append("failure_behavior")
    if spec.output_target:
        ids.append("output_target")
    return ids
