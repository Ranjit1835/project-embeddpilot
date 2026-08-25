"""V2 WS1 tests: requirement -> ambiguity detection -> clarifying questions ->
spec lock. All LLM calls are mocked (MockProvider) — no network.

The thing under test is not "can we parse English", it is "can the model make us
write down something the user never said". Every test here is an attempt to get
an invented requirement into the spec, from a different direction.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from generation.provider import MockProvider
from generation.spec import (
    AMBIGUOUS_CHIP,
    MISSING_COMPARATOR,
    MISSING_DEVICE,
    MISSING_FAILURE_BEHAVIOR,
    MISSING_INTERFACE,
    MISSING_OUTPUT_TARGET,
    MISSING_PIN,
    MISSING_ROLE,
    MISSING_SAMPLE_RATE,
    MISSING_TARGET,
    MISSING_THRESHOLD,
    MISSING_TRIGGER_SOURCE,
    MISSING_UNITS,
    SCHEMA_PATH,
    ApplicationSpec,
    Field,
    SpecError,
    SpecIncompleteError,
    SpecProvenanceError,
    analyze_requirement,
    answer_questions,
    assert_spec_complete,
    detect_ambiguities,
    is_specific_part,
    spec_line_ids,
)

# --- fixtures --------------------------------------------------------------------

VAGUE = ("I want a greenhouse controller. It should read a temp sensor and turn "
         "on a relay when it gets hot.")

# What a helpful model does with a vague requirement: it completes the picture.
# Every leaf below quotes REAL text from VAGUE (so the quote check passes) but
# the quoted text does not state the value — which is the interesting case,
# because a fabricated-quote check alone would let all of this through.
GREEDY_RESPONSE = {
    "target": {
        "board": {"value": "Nucleo-F411RE", "evidence": "greenhouse controller"},
        "mcu": {"value": "STM32F411RE", "evidence": "greenhouse controller"},
    },
    "devices": [
        {"name": {"value": "BME280", "evidence": "read a temp sensor"},
         "role": {"value": "temp sensor", "evidence": "read a temp sensor"},
         "interface": {"value": "I2C", "evidence": "read a temp sensor"}},
        {"name": {"value": "relay", "evidence": "turn on a relay"},
         "role": {"value": "relay output", "evidence": "turn on a relay"}},
    ],
    "behaviors": [
        {"trigger": {"source": {"value": "temperature", "evidence": "when it gets hot"},
                     "comparator": {"value": ">", "evidence": "when it gets hot"},
                     "threshold": {"value": 30, "evidence": "when it gets hot"},
                     "unit": {"value": "C", "evidence": "when it gets hot"}},
         "action": {"value": "turn on a relay", "evidence": "turn on a relay"}},
    ],
    "questions": [
        # duplicates a rule-derived question -> must be deduped away
        {"field": "devices[0].name",
         "text": "Which temperature sensor part should we use?"},
        # genuinely novel and specific -> kept, but non-blocking
        {"field": "devices[1].address",
         "text": "Is the relay module active-high or active-low?"},
        # vague -> rejected
        {"field": "notes", "text": "Anything else I should know?"},
    ],
}

FULL = (
    "Build a greenhouse controller on a Nucleo-F411RE board with an STM32F411RE "
    "MCU. It reads a BME280 over I2C as the temperature sensor, and drives a "
    "SRD-05VDC relay module on pin PB5 as a GPIO output. When the temperature is "
    "above 30 C, turn the relay on. Sample every 500 ms. If the sensor read "
    "fails, hold the relay off and log an error. Produce a platformio-project."
)

FULL_RESPONSE = {
    "target": {
        "board": {"value": "Nucleo-F411RE", "evidence": "on a Nucleo-F411RE board"},
        "mcu": {"value": "STM32F411RE", "evidence": "with an STM32F411RE MCU"},
    },
    "devices": [
        {"name": {"value": "BME280", "evidence": "reads a BME280 over I2C"},
         "interface": {"value": "I2C", "evidence": "reads a BME280 over I2C"},
         "role": {"value": "temperature sensor",
                  "evidence": "as the temperature sensor"}},
        {"name": {"value": "SRD-05VDC",
                  "evidence": "drives a SRD-05VDC relay module"},
         "role": {"value": "relay module",
                  "evidence": "drives a SRD-05VDC relay module"},
         "interface": {"value": "GPIO", "evidence": "as a GPIO output"},
         "pin": {"value": "PB5", "evidence": "on pin PB5"}},
    ],
    "behaviors": [
        {"trigger": {
            "source": {"value": "temperature",
                       "evidence": "When the temperature is above 30 C"},
            "comparator": {"value": ">",
                           "evidence": "When the temperature is above 30 C"},
            "threshold": {"value": 30,
                          "evidence": "When the temperature is above 30 C"},
            "unit": {"value": "C", "evidence": "When the temperature is above 30 C"}},
         "action": {"value": "turn the relay on", "evidence": "turn the relay on"}},
    ],
    "constraints": [
        {"name": "sample_rate",
         "value": {"value": 500, "evidence": "Sample every 500 ms"},
         "unit": {"value": "ms", "evidence": "Sample every 500 ms"}},
    ],
    "failure_behavior": {"value": "hold the relay off and log an error",
                         "evidence": "hold the relay off and log an error"},
    "output_target": {"value": "platformio-project",
                      "evidence": "Produce a platformio-project"},
    "questions": [],
}


def values_only(spec: ApplicationSpec) -> str:
    """JSON of the VALUE-bearing part of the spec (no question text, which
    legitimately contains example values like '30 C')."""
    d = spec.to_dict()
    return json.dumps({k: d[k] for k in ("target", "devices", "behaviors",
                                         "constraints", "failure_behavior",
                                         "output_target")})


def kinds(questions) -> set:
    return {q.kind for q in questions}


def by_field(questions) -> dict:
    return {q.field: q for q in questions}


# --- 1. a vague requirement asks, and invents nothing -----------------------------

def test_vague_requirement_produces_questions_and_no_invented_values():
    provider = MockProvider([GREEDY_RESPONSE])
    spec, questions = analyze_requirement(VAGUE, provider)

    # NOTHING the model completed for the user survived.
    payload = values_only(spec)
    for invented in ("BME280", "Nucleo", "F411", "STM32", "30", "I2C"):
        assert invented not in payload, f"{invented} was invented into the spec"
    assert spec.target.board is None and spec.target.mcu is None
    assert spec.behaviors[0].trigger.threshold is None
    assert spec.behaviors[0].trigger.comparator is None

    # ...and each refusal is on the record, not silently swallowed.
    dropped = {d["field"] for d in spec.dropped}
    assert {"target.board", "target.mcu", "devices[0].name",
            "behaviors[0].trigger.threshold"} <= dropped

    # every ambiguity class the requirement actually contains got asked about
    assert kinds(questions) >= {
        MISSING_TARGET,            # no board / no MCU
        AMBIGUOUS_CHIP,            # "a temp sensor" / "a relay" — which part?
        MISSING_INTERFACE,         # devices named with no bus
        MISSING_ROLE,
        MISSING_TRIGGER_SOURCE,
        MISSING_COMPARATOR,
        MISSING_THRESHOLD,         # "when it gets hot" has no number
        MISSING_SAMPLE_RATE,
        MISSING_FAILURE_BEHAVIOR,  # nothing said about a failed read
        MISSING_OUTPUT_TARGET,
    }


def test_questions_are_specific_and_answerable():
    provider = MockProvider([GREEDY_RESPONSE])
    _, questions = analyze_requirement(VAGUE, provider)
    vague_words = ("anything else", "clarify", "more details", "please specify",
                   "what else")
    for q in questions:
        # a real question, and long enough to actually name the field — the
        # trailing text after the '?' is a worked example, which is the point
        assert "?" in q.text, q.text
        assert len(q.text) > 25, q.text
        assert not any(v in q.text.lower() for v in vague_words), q.text
    # a category device is asked about by name, not generically
    q = by_field(questions)["devices[1].name"]
    assert "relay" in q.text and q.kind == AMBIGUOUS_CHIP


def test_vague_requirement_blocks_generation():
    provider = MockProvider([GREEDY_RESPONSE])
    spec, questions = analyze_requirement(VAGUE, provider)
    with pytest.raises(SpecIncompleteError) as exc:
        assert_spec_complete(spec)
    assert "unanswered" in str(exc.value)


# --- 2. a fully-specified requirement locks -----------------------------------------

def test_fully_specified_requirement_produces_complete_spec():
    provider = MockProvider([FULL_RESPONSE])
    spec, questions = analyze_requirement(FULL, provider)

    assert questions == [], [q.text for q in questions]
    assert spec.dropped == []
    assert_spec_complete(spec)  # must not raise

    assert spec.target.board.value == "Nucleo-F411RE"
    assert spec.target.mcu.value == "STM32F411RE"
    assert [d.name.value for d in spec.devices] == ["BME280", "SRD-05VDC"]
    assert [d.interface.value for d in spec.devices] == ["I2C", "GPIO"]
    assert spec.devices[1].pin.value == "PB5"
    beh = spec.behaviors[0]
    assert (beh.trigger.source.value, beh.trigger.comparator.value,
            beh.trigger.threshold.value, beh.trigger.unit.value) == \
        ("temperature", ">", 30, "C")
    assert spec.constraint("sample_rate").value.value == 500
    assert spec.constraint("sample_rate").unit.value == "MS"
    assert spec.output_target.value == "platformio-project"


def test_every_value_carries_user_provenance_and_evidence():
    provider = MockProvider([FULL_RESPONSE])
    spec, _ = analyze_requirement(FULL, provider)

    leaves = _walk_leaves(spec.to_dict())
    assert leaves, "spec has no provenanced values"
    for path, leaf in leaves:
        assert leaf["provenance"] == "user", (path, leaf)
        # the receipt must be real: a verbatim span of what the user wrote
        assert leaf["evidence"], path
        assert leaf["evidence"] in FULL, (path, leaf["evidence"])


def _walk_leaves(node, path="") -> list:
    out = []
    if isinstance(node, dict):
        if set(node) == {"value", "provenance", "evidence"}:
            return [(path, node)]
        for k, v in node.items():
            out += _walk_leaves(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _walk_leaves(v, f"{path}[{i}]")
    return out


def test_spec_line_ids_cover_the_contract():
    provider = MockProvider([FULL_RESPONSE])
    spec, _ = analyze_requirement(FULL, provider)
    ids = spec_line_ids(spec)
    assert "target.mcu" in ids
    assert "device.BME280.interface" in ids
    assert "device.SRD-05VDC.pin" in ids
    assert "behavior.b1.trigger" in ids
    assert "constraint.sample_rate" in ids


# --- 3. answering the questions completes the spec ------------------------------------

ANSWERS = {
    "target.board": "Nucleo-F411RE",
    "target.mcu": "STM32F411RE",
    "devices[0].name": "BME280",
    "devices[0].interface": "I2C",
    "devices[0].role": "temperature sensor",
    "devices[1].name": "plain GPIO output",   # honest "there is no part number"
    "devices[1].interface": "GPIO",
    "devices[1].role": "relay output",
    "devices[1].pin": "PB5",                  # only asked once GPIO is known
    "behaviors[0].trigger.source": "temperature",
    "behaviors[0].trigger.comparator": "above",
    "behaviors[0].trigger.threshold": "30 C",  # answers the unit question too
    "constraints.sample_rate": "every 500 ms",
    "failure_behavior": "hold the relay off and log an error",
    "output_target": "platformio-project",
}


def test_answering_questions_completes_the_spec():
    provider = MockProvider([GREEDY_RESPONSE])
    spec, questions = analyze_requirement(VAGUE, provider)
    assert questions

    rounds = 0
    while [q for q in questions if q.blocking]:
        rounds += 1
        assert rounds < 6, "clarification is not converging"
        answers = {}
        for q in questions:
            if not q.blocking:
                continue
            assert q.field in ANSWERS, f"no scripted answer for {q.field}: {q.text}"
            answers[q.id] = ANSWERS[q.field]
        spec, questions = answer_questions(spec, answers)

    assert_spec_complete(spec)  # the contract is now satisfiable
    assert provider.calls == [provider.calls[0]], "answering must not call the LLM"

    # answered fields are provenance 'asked' — a distinct, truthful origin
    assert spec.target.board.provenance == "asked"
    assert "answer to q:target.board" in spec.target.board.evidence
    beh = spec.behaviors[0]
    assert (beh.trigger.comparator.value, beh.trigger.threshold.value,
            beh.trigger.unit.value) == (">", 30, "C")
    assert beh.trigger.unit.provenance == "asked"
    # the action survived from the original text, so it stays 'user'
    assert beh.action.provenance == "user"


def test_answering_never_calls_the_provider():
    provider = MockProvider([GREEDY_RESPONSE])
    spec, questions = analyze_requirement(VAGUE, provider)
    before = len(provider.calls)
    q = by_field(questions)["target.board"]
    answer_questions(spec, {q.id: "Nucleo-F411RE"})
    assert len(provider.calls) == before


def test_unparseable_answer_is_not_coerced_and_is_reasked():
    provider = MockProvider([GREEDY_RESPONSE])
    spec, questions = analyze_requirement(VAGUE, provider)
    q = by_field(questions)["behaviors[0].trigger.threshold"]
    spec, questions = answer_questions(spec, {q.id: "when it feels warm"})

    assert spec.behaviors[0].trigger.threshold is None  # nothing was invented
    again = by_field(questions)["behaviors[0].trigger.threshold"]
    assert "could not be read" in again.text
    assert again.blocking


def test_unknown_interface_answer_is_rejected_not_guessed():
    provider = MockProvider([GREEDY_RESPONSE])
    spec, questions = analyze_requirement(VAGUE, provider)
    q = by_field(questions)["devices[0].interface"]
    spec, questions = answer_questions(spec, {q.id: "whatever is easiest"})
    assert spec.devices[0].interface is None
    assert "devices[0].interface" in by_field(questions)


def test_gpio_device_must_declare_a_pin():
    provider = MockProvider([GREEDY_RESPONSE])
    spec, questions = analyze_requirement(VAGUE, provider)
    q = by_field(questions)["devices[1].interface"]
    spec, questions = answer_questions(spec, {q.id: "GPIO"})
    pin_q = by_field(questions).get("devices[1].pin")
    assert pin_q is not None and pin_q.kind == MISSING_PIN


# --- 4. assert_spec_complete is the gate ----------------------------------------------

def complete_spec() -> ApplicationSpec:
    spec, _ = analyze_requirement(FULL, MockProvider([FULL_RESPONSE]))
    return spec


def test_assert_spec_complete_rejects_an_incomplete_spec():
    spec = complete_spec()
    spec.target.mcu = None
    with pytest.raises(SpecIncompleteError) as exc:
        assert_spec_complete(spec)
    assert "MCU" in str(exc.value)


def test_clearing_open_questions_does_not_buy_permission_to_build():
    # the gate recomputes ambiguities; it never trusts the stored list
    spec = complete_spec()
    spec.behaviors[0].trigger.threshold = None
    spec.open_questions = []
    with pytest.raises(SpecIncompleteError):
        assert_spec_complete(spec)


def test_missing_failure_behavior_blocks():
    spec = complete_spec()
    spec.failure_behavior = None
    assert MISSING_FAILURE_BEHAVIOR in kinds(detect_ambiguities(spec))
    with pytest.raises(SpecIncompleteError):
        assert_spec_complete(spec)


def test_value_without_evidence_is_treated_as_invented():
    spec = complete_spec()
    spec.target.board.evidence = ""
    with pytest.raises(SpecProvenanceError) as exc:
        assert_spec_complete(spec)
    assert "evidence" in str(exc.value)


def test_no_devices_or_no_behaviors_blocks():
    spec = complete_spec()
    spec.devices = []
    assert MISSING_DEVICE in kinds(detect_ambiguities(spec))
    with pytest.raises(SpecIncompleteError):
        assert_spec_complete(spec)


# --- 5. provenance can only ever be 'user' or 'asked' ----------------------------------

@pytest.mark.parametrize("bad", ["inferred", "model", "default", "assumed",
                                 "detected", "", None])
def test_forbidden_provenance_cannot_even_be_constructed(bad):
    with pytest.raises(SpecProvenanceError):
        Field(value="STM32F411RE", provenance=bad, evidence="x")


def test_tampered_spec_cannot_be_loaded_back():
    d = complete_spec().to_dict()
    d["target"]["mcu"]["provenance"] = "inferred"
    with pytest.raises(SpecProvenanceError):
        ApplicationSpec.from_dict(d)


def test_model_supplied_provenance_is_ignored():
    # the model claims 'inferred' on a value that IS grounded; we assign 'user'
    # ourselves, because provenance is never read from model output at all
    response = json.loads(json.dumps(FULL_RESPONSE))
    response["target"]["mcu"]["provenance"] = "inferred"
    response["target"]["mcu"]["confidence"] = "high"
    spec, _ = analyze_requirement(FULL, MockProvider([response]))
    assert spec.target.mcu.provenance == "user"


# --- 6. specific grounding failures ------------------------------------------------------

def test_fabricated_quote_is_rejected():
    # evidence that does not occur in the user's text at all
    response = {"target": {"board": {"value": "Nucleo-F411RE",
                                     "evidence": "target the Nucleo-F411RE board"}}}
    spec, questions = analyze_requirement(VAGUE, MockProvider([response]))
    assert spec.target.board is None
    assert any("verbatim" in d["reason"] for d in spec.dropped)


def test_board_name_does_not_ground_the_mcu_part():
    # the classic silent inference: Nucleo-F411RE -> STM32F411RET6. Real quote,
    # real board, but the user never named the MCU part, so we ask.
    text = "Target the Nucleo-F411RE board."
    response = {"target": {
        "board": {"value": "Nucleo-F411RE", "evidence": "the Nucleo-F411RE board"},
        "mcu": {"value": "STM32F411RET6", "evidence": "the Nucleo-F411RE board"}}}
    spec, questions = analyze_requirement(text, MockProvider([response]))
    assert spec.target.board.value == "Nucleo-F411RE"
    assert spec.target.mcu is None
    assert by_field(questions)["target.mcu"].kind == MISSING_TARGET


def test_comparator_direction_must_come_from_the_users_words():
    text = "Turn the fan on when the temperature drops below 18 C."
    flipped = {"behaviors": [{
        "trigger": {"source": {"value": "temperature",
                               "evidence": "the temperature drops below 18 C"},
                    "comparator": {"value": ">",   # user said BELOW
                                   "evidence": "the temperature drops below 18 C"},
                    "threshold": {"value": 18,
                                  "evidence": "the temperature drops below 18 C"},
                    "unit": {"value": "C",
                             "evidence": "the temperature drops below 18 C"}},
        "action": {"value": "Turn the fan on", "evidence": "Turn the fan on"}}]}
    spec, questions = analyze_requirement(text, MockProvider([flipped]))
    assert spec.behaviors[0].trigger.comparator is None  # ">" was not grounded
    assert spec.behaviors[0].trigger.threshold.value == 18  # this one was
    assert by_field(questions)["behaviors[0].trigger.comparator"].kind == \
        MISSING_COMPARATOR

    ok = json.loads(json.dumps(flipped))
    ok["behaviors"][0]["trigger"]["comparator"]["value"] = "<"
    spec2, _ = analyze_requirement(text, MockProvider([ok]))
    assert spec2.behaviors[0].trigger.comparator.value == "<"


def test_threshold_without_a_unit_asks_for_the_unit():
    text = "Turn the relay on when temperature goes above 30."
    response = {"behaviors": [{
        "trigger": {"source": {"value": "temperature",
                               "evidence": "when temperature goes above 30"},
                    "comparator": {"value": ">",
                                   "evidence": "when temperature goes above 30"},
                    "threshold": {"value": 30,
                                  "evidence": "when temperature goes above 30"},
                    "unit": {"value": "C",     # never stated
                             "evidence": "when temperature goes above 30"}},
        "action": {"value": "Turn the relay on", "evidence": "Turn the relay on"}}]}
    spec, questions = analyze_requirement(text, MockProvider([response]))
    assert spec.behaviors[0].trigger.threshold.value == 30
    assert spec.behaviors[0].trigger.unit is None
    q = by_field(questions)["behaviors[0].trigger.unit"]
    assert q.kind == MISSING_UNITS and "30" in q.text


def test_free_text_may_drop_filler_but_not_add_meaning():
    text = "When the tank is full, turn the pump off and log it."
    response = {"behaviors": [{
        "trigger": {},
        # paraphrase that ADDS a concept the user never used ("shut down")
        "action": {"value": "shut down the pump",
                   "evidence": "turn the pump off and log it"}}],
        "failure_behavior": {"value": "log it",       # faithful subset
                             "evidence": "turn the pump off and log it"}}
    spec, _ = analyze_requirement(text, MockProvider([response]))
    assert spec.failure_behavior.value == "log it"
    assert not spec.behaviors  # the paraphrased action was dropped


@pytest.mark.parametrize("name,expected", [
    ("BME280", True), ("SSD1306", True), ("DS18B20", True), ("SRD-05VDC", True),
    ("a temp sensor", False), ("relay", False), ("sensor", False),
    ("temperature sensor", False), ("TBD", False), ("display module", False),
])
def test_part_number_vs_category(name, expected):
    assert is_specific_part(name) is expected


# --- 7. the model may propose questions, never values -----------------------------------

def test_model_questions_are_screened_deduped_and_non_blocking():
    provider = MockProvider([GREEDY_RESPONSE])
    _, questions = analyze_requirement(VAGUE, provider)
    proposed = [q for q in questions if q.kind == "model_proposed"]
    assert len(proposed) == 1
    assert "active-high" in proposed[0].text
    assert proposed[0].blocking is False        # cannot hold generation hostage
    # the vague one was dropped, the duplicate collapsed into the rule question
    assert not any("Anything else" in q.text for q in questions)
    assert by_field(questions)["devices[0].name"].kind == AMBIGUOUS_CHIP


def test_provider_failure_degrades_to_asking_not_assuming():
    spec, questions = analyze_requirement(VAGUE, MockProvider([]))  # exhausted
    assert values_only(spec) == values_only(ApplicationSpec())
    assert kinds(questions) >= {MISSING_TARGET, MISSING_DEVICE}
    assert any("extraction unavailable" in n for n in spec.notes)
    with pytest.raises(SpecError):
        assert_spec_complete(spec)


def test_non_object_model_output_extracts_nothing():
    spec, questions = analyze_requirement(VAGUE, MockProvider([["not", "a", "dict"]]))
    assert spec.devices == [] and spec.target.board is None
    assert questions


# --- 8. schema mirrors the dataclasses ---------------------------------------------------

def test_spec_validates_against_the_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)

    partial, _ = analyze_requirement(VAGUE, MockProvider([GREEDY_RESPONSE]))
    jsonschema.validate(partial.to_dict(), schema)
    jsonschema.validate(complete_spec().to_dict(), schema)
    jsonschema.validate(ApplicationSpec().to_dict(), schema)


def test_schema_forbids_any_third_provenance():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    enum = schema["definitions"]["provenancedValue"]["properties"]["provenance"]["enum"]
    assert enum == ["user", "asked"]


def test_round_trip_through_dict_preserves_the_spec():
    spec = complete_spec()
    again = ApplicationSpec.from_dict(spec.to_dict())
    assert again.to_dict()["target"] == spec.to_dict()["target"]
    assert again.to_dict()["devices"] == spec.to_dict()["devices"]
    assert_spec_complete(again)


# --- 9. no vendor is hard-coded ------------------------------------------------------------

def test_spec_module_hardcodes_no_vendor():
    text = open(os.path.join(PROJECT_ROOT, "generation", "spec.py"),
                encoding="utf-8").read()
    assert "make_provider" in text
    for vendor in ("groq.", "openai.", "anthropic", "Groq(", "OpenAI("):
        assert vendor not in text, vendor
