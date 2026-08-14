"""The assumption ledger: the part that keeps a business case honest.

Most AI-written business cases fail the same way. They are internally coherent,
beautifully formatted, and quietly built on numbers nobody measured. The
sentence "industry research shows a 30% productivity gain" survives right up
until a CFO asks which industry, whose research, and measured how — at which
point the entire case, including its true parts, loses credibility.

This module makes that failure mode structurally hard. Every number entering a
model must declare what kind of number it is:

``fact``
    Measured from a named system, export, or document the reader could open.
    Requires a specific source. "Zendesk ticket export, FY25 Q1-Q4" qualifies;
    "internal data" does not.

``assumption``
    A chosen value nobody measured. Requires a stated rationale *and* a plausible
    range. Unbounded assumptions are how business cases lie, so a range is
    mandatory — if you cannot bound it, you do not understand it well enough to
    put it in the model.

``inference``
    Derived from facts by stated reasoning. Requires the derivation, not just a
    citation. "Blended hourly cost = fully loaded salary / 2080 hours" qualifies.

The payoff is :func:`grade_evidence`, which reports what share of the modeled
value rests on measurement versus on hope. A case where 80% of the NPV comes
from assumptions is not necessarily wrong — but the reader deserves to know
before they fund it, and stating it first is disarming rather than damaging.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

__all__ = [
    "CONFIDENCE_LEVELS",
    "EvidenceError",
    "Input",
    "validate_input",
    "grade_evidence",
    "weasel_phrases",
]

#: Ordered from strongest to weakest. Order matters: the grader reports the
#: weakest link, and reviewers scan for it.
CONFIDENCE_LEVELS = ("fact", "inference", "assumption")


class EvidenceError(ValueError):
    """Raised when a declared input fails the honesty rules."""


#: Sources that sound authoritative and cite nothing. These are the exact
#: phrases that get business cases dismissed in review, so they are rejected at
#: the door rather than flagged in a report nobody reads.
_WEASEL_PATTERNS = (
    r"^industry (standard|average|benchmark|research)s?\.?$",
    r"^(research|studies|data) shows?\b",
    r"^(best|common) practice\.?$",
    r"^internal (data|analysis|estimate)s?\.?$",
    r"^(gartner|forrester|idc|mckinsey)\.?$",
    r"^(analyst|vendor) (report|data|claim)s?\.?$",
    r"^(widely|generally) (known|accepted|reported)\b",
    r"^experience\.?$",
    r"^estimate[ds]?\.?$",
    r"^tbd\.?$",
    r"^n/?a\.?$",
    r"^assumed?\.?$",
    r"^unknown\.?$",
)

_WEASEL_RE = tuple(re.compile(p, re.IGNORECASE) for p in _WEASEL_PATTERNS)

#: A source this short cannot identify anything a reader could go open.
_MIN_SOURCE_CHARS = 12


def weasel_phrases(source: str) -> List[str]:
    """Return the weasel patterns a source string matches, if any."""
    text = (source or "").strip()
    return [
        pattern.pattern
        for pattern in _WEASEL_RE
        if pattern.search(text)
    ]


class Input:
    """A single declared number, with its provenance and uncertainty.

    Attributes mirror the JSON spec format so a spec file reads the same as the
    object it produces.
    """

    __slots__ = (
        "name",
        "value",
        "confidence",
        "source",
        "low",
        "high",
        "unit",
        "note",
    )

    def __init__(
        self,
        name: str,
        value: float,
        confidence: str,
        source: str,
        low: Optional[float] = None,
        high: Optional[float] = None,
        unit: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        self.name = name
        self.value = float(value)
        self.confidence = confidence
        self.source = source
        self.low = None if low is None else float(low)
        self.high = None if high is None else float(high)
        self.unit = unit
        self.note = note

    @property
    def range(self):
        """The (low, high) band, defaulting to the point value when absent."""
        return (
            self.value if self.low is None else self.low,
            self.value if self.high is None else self.high,
        )

    @property
    def swing(self) -> float:
        """Width of the uncertainty band in absolute terms."""
        low, high = self.range
        return high - low

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": self.name,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
        }
        if self.low is not None:
            out["low"] = self.low
        if self.high is not None:
            out["high"] = self.high
        if self.unit:
            out["unit"] = self.unit
        if self.note:
            out["note"] = self.note
        return out

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Input(%r, %r, %r)" % (self.name, self.value, self.confidence)


def validate_input(name: str, raw: Mapping[str, Any]) -> Input:
    """Turn a raw spec mapping into a validated :class:`Input`.

    Raises :class:`EvidenceError` with a message written for the person who has
    to fix the spec, naming the input and saying what would satisfy the rule.
    """
    if not isinstance(raw, Mapping):
        raise EvidenceError(
            "input %r must be an object with at least value, confidence, and "
            "source" % name
        )

    if "value" not in raw:
        raise EvidenceError("input %r is missing 'value'" % name)
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(
            "input %r has a non-numeric value %r" % (name, value)
        )

    confidence = str(raw.get("confidence", "")).strip().lower()
    if confidence not in CONFIDENCE_LEVELS:
        raise EvidenceError(
            "input %r must declare confidence as one of %s (got %r). This is "
            "not bureaucracy: a reader needs to know which numbers were "
            "measured and which were chosen."
            % (name, ", ".join(CONFIDENCE_LEVELS), raw.get("confidence"))
        )

    source = str(raw.get("source", "")).strip()
    if not source:
        raise EvidenceError(
            "input %r needs a 'source'. For a fact, name the system or export. "
            "For an assumption, state the rationale. For an inference, state "
            "the derivation." % name
        )
    if len(source) < _MIN_SOURCE_CHARS:
        raise EvidenceError(
            "source for %r is too vague to verify: %r. Name something a "
            "reader could actually open or reproduce." % (name, source)
        )
    matched = weasel_phrases(source)
    if matched:
        raise EvidenceError(
            "source for %r reads as an unfalsifiable claim: %r. Replace it "
            "with a specific artifact (a named export, dashboard, contract, "
            "or a stated derivation). If the number really is unmeasured, "
            "mark it confidence='assumption' and give it a range."
            % (name, source)
        )

    low = raw.get("low")
    high = raw.get("high")
    if low is not None and high is not None and low > high:
        raise EvidenceError(
            "input %r has low (%r) above high (%r)" % (name, low, high)
        )
    for bound_name, bound in (("low", low), ("high", high)):
        if bound is not None and (
            isinstance(bound, bool) or not isinstance(bound, (int, float))
        ):
            raise EvidenceError(
                "input %r has non-numeric %s %r" % (name, bound_name, bound)
            )
    if low is not None and high is not None and not (low <= value <= high):
        raise EvidenceError(
            "input %r has a base value (%r) outside its own range [%r, %r]. "
            "Either the base case or the range is wrong."
            % (name, value, low, high)
        )

    if confidence == "assumption" and (low is None or high is None):
        raise EvidenceError(
            "input %r is an assumption and needs both 'low' and 'high'. An "
            "unbounded assumption cannot be stress-tested, and a business "
            "case whose assumptions cannot be stress-tested is a brochure."
            % name
        )

    return Input(
        name=name,
        value=float(value),
        confidence=confidence,
        source=source,
        low=low,
        high=high,
        unit=raw.get("unit"),
        note=raw.get("note"),
    )


def grade_evidence(
    contributions: Sequence[Any],
) -> Dict[str, Any]:
    """Score how much of the modeled value rests on measurement.

    ``contributions`` is a sequence of ``(confidence, value)`` pairs — typically
    one per benefit driver, where ``value`` is that driver's contribution to
    NPV and ``confidence`` is the weakest confidence among the driver's inputs
    (a chain is only as sound as its softest link).

    Returns a dict with per-level shares plus a letter grade. The letter is a
    communication device, not a science: it exists so the headline of a review
    can be "this case grades C — 71% of the value rests on assumptions" instead
    of a paragraph nobody finishes.
    """
    pairs = []
    for item in contributions:
        confidence, value = item
        confidence = str(confidence).strip().lower()
        if confidence not in CONFIDENCE_LEVELS:
            raise EvidenceError(
                "unknown confidence level %r in evidence grading" % confidence
            )
        pairs.append((confidence, abs(float(value))))

    total = sum(value for _, value in pairs)
    shares = {level: 0.0 for level in CONFIDENCE_LEVELS}
    for confidence, value in pairs:
        shares[confidence] += value

    if total > 0:
        shares = {k: v / total for k, v in shares.items()}
    else:
        shares = {k: 0.0 for k in shares}

    measured = shares["fact"] + 0.5 * shares["inference"]
    if total == 0:
        letter = "n/a"
    elif measured >= 0.80:
        letter = "A"
    elif measured >= 0.60:
        letter = "B"
    elif measured >= 0.40:
        letter = "C"
    elif measured >= 0.20:
        letter = "D"
    else:
        letter = "F"

    return {
        "total_value_graded": total,
        "share_fact": shares["fact"],
        "share_inference": shares["inference"],
        "share_assumption": shares["assumption"],
        "measured_share": measured,
        "grade": letter,
        "headline": _grade_headline(letter, shares),
    }


def _grade_headline(letter: str, shares: Mapping[str, float]) -> str:
    if letter == "n/a":
        return "No value modeled yet — nothing to grade."
    assumption_pct = round(shares["assumption"] * 100)
    fact_pct = round(shares["fact"] * 100)
    if letter in ("A", "B"):
        return (
            "Grade %s. %d%% of modeled value traces to measured facts; %d%% "
            "rests on assumptions. Lead with the measurement."
            % (letter, fact_pct, assumption_pct)
        )
    return (
        "Grade %s. %d%% of modeled value rests on assumptions and only %d%% on "
        "measured facts. State this before the reader finds it, and prioritize "
        "measuring the largest assumption."
        % (letter, assumption_pct, fact_pct)
    )


def weakest_confidence(confidences: Iterable[str]) -> str:
    """Return the weakest confidence level in a set, for chain grading."""
    levels = [str(c).strip().lower() for c in confidences]
    for level in reversed(CONFIDENCE_LEVELS):
        if level in levels:
            return level
    return "assumption"
