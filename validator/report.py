"""Validation report structure shared by all checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Failure:
    check: str        # compile | register_crosscheck | static_analysis
    file: str
    line: int | None
    message: str


@dataclass
class UnverifiedField:
    """A bit-field definition the map could not confirm (Amendment 1)."""

    file: str
    line: int
    register: str
    define: str
    claimed_bits: str        # "[msb:lsb]" or "bit N"
    has_unverified_comment: bool
    source_pages: list[int] = field(default_factory=list)


@dataclass
class UnverifiedComputation:
    """A block of compensation/conversion math transcribed from datasheet prose
    (V1.6.1 Fix 3). The register cross-check can confirm register ACCESS but
    nothing verifies computation LOGIC — a wrong shift compiles clean and passes
    cross-check. We do not verify the math here; we make the verdict honest by
    surfacing that such math is present and unchecked, exactly like an unverified
    bit field. Detected by the worker-emitted marker comment."""

    file: str
    line: int
    marker: str              # the marker comment text found


@dataclass
class ValidationReport:
    status: str = "failed"   # validated | validated-with-unverified-fields | failed
    checks: dict = field(default_factory=dict)   # name -> pass|fail|skipped
    failures: list[Failure] = field(default_factory=list)
    unverified_fields: list[UnverifiedField] = field(default_factory=list)
    unverified_computations: list[UnverifiedComputation] = field(default_factory=list)
    # V1.8: per-core Arduino compile results — {name, fqbn, result, detail?}.
    # Surfaced in the Results provenance panel; a failing core is also a Failure.
    cores: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def finalize(self) -> "ValidationReport":
        """Compute the three-state verdict. Compile and cross-check are the
        core guarantees: if either was skipped (toolchain missing), the result
        is NOT validated — a skipped judge never passes anyone."""
        if self.failures:
            self.status = "failed"
        elif (
            self.checks.get("compile") == "skipped"
            or self.checks.get("register_crosscheck") == "skipped"
        ):
            self.status = "failed"
            self.notes.append(
                "required check could not run (missing toolchain) — result is unvalidated"
            )
        elif self.unverified_fields or self.unverified_computations:
            # unverified bit fields AND/OR transcribed computation math: the code
            # builds and its register access checks out, but something in it was
            # not cross-checked against the map. Never collapse this to a clean
            # "validated".
            self.status = "validated-with-unverified-fields"
        else:
            self.status = "validated"
        if self.checks.get("static_analysis") == "skipped":
            self.notes.append(
                "static analysis skipped (cppcheck unavailable) — install cppcheck for full coverage"
            )
        return self

    def to_json(self) -> dict:
        return asdict(self)
