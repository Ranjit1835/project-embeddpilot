"""V1.5 validation layer — the judge, mechanically separate from the generator.

Inputs are ONLY: generated code files on disk + register map JSON + toolchain.
This package must never import from generation/ (and generation/ never from
here); tests/test_ws2_pipeline.py enforces that. Run as a subprocess:

    python -m validator <workdir> --map <register-map.json> [--platform esp32]

Verdicts (Amendment 1, three-state — never collapsed):
    validated
    validated-with-unverified-fields
    failed
"""
