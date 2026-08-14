"""Weighted rubric scoring with honest coverage reporting.

One engine serves three jobs that are the same math wearing different hats:
ICP fit scoring, deal qualification (MEDDPICC and friends), and account health.
Rather than three half-implementations, there is one rubric format and one
scorer::

    python3 -m gtmkit.scoring --rubric rubric.json --records accounts.csv

The feature that makes this worth using instead of a spreadsheet is **coverage**.
Every scoring model quietly treats missing data as bad data — an account with no
headcount on file scores like an account known to be tiny. That single behavior
has misdirected more territory plans than any modeling error, because it
systematically penalizes the accounts nobody has researched yet.

So this scorer tracks two numbers per record: the score, and the share of
weight that had data behind it. An account at 82% fit on 40% coverage is not a
good account; it is an unresearched one, and it gets flagged as such rather than
ranked next to a fully-diligenced peer.

Rubric format (see ``skills/icp-scoring/references/rubric-format.md``)::

    {
      "name": "ICP fit — mid-market logistics",
      "scale": 5,
      "tiers": [{"min": 0.8, "label": "A"}, {"min": 0.6, "label": "B"}],
      "disqualifiers": [
        {"field": "employees", "op": "<", "value": 50,
         "reason": "Below the support threshold where our ROI clears"}
      ],
      "criteria": [
        {"id": "employees", "label": "Headcount", "weight": 3,
         "type": "numeric",
         "bands": [{"min": 500, "score": 5}, {"min": 200, "score": 4},
                   {"min": 50, "score": 2}]},
        {"id": "uses_salesforce", "label": "Runs Salesforce", "weight": 2,
         "type": "boolean", "true_score": 5, "false_score": 1},
        {"id": "industry", "label": "Industry", "weight": 2,
         "type": "categorical",
         "map": {"logistics": 5, "manufacturing": 4}, "default": 1}
      ]
    }
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .fmt import fmt_pct, table

__all__ = ["Rubric", "RubricError", "main", "score_all", "score_record"]

_MISSING = (None, "", "unknown", "n/a", "na", "null", "-", "?")


class RubricError(ValueError):
    """Raised for malformed rubrics or records."""


class Criterion:
    __slots__ = (
        "bands",
        "default",
        "false_score",
        "id",
        "label",
        "map",
        "note",
        "true_score",
        "type",
        "weight",
    )

    def __init__(self, raw: Mapping[str, Any], scale: float) -> None:
        self.id = str(raw.get("id") or "").strip()
        if not self.id:
            raise RubricError("every criterion needs an 'id'")
        self.label = str(raw.get("label") or self.id)
        weight = raw.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise RubricError("criterion %r has a non-numeric weight" % self.id)
        if weight <= 0:
            raise RubricError(
                "criterion %r has weight %r; drop it from the rubric rather "
                "than weighting it zero, so readers can see what you chose "
                "not to measure" % (self.id, weight)
            )
        self.weight = float(weight)
        self.type = str(raw.get("type") or "numeric").strip().lower()
        self.note = raw.get("note")

        self.bands = None
        self.true_score = None
        self.false_score = None
        self.map = None
        self.default = None

        if self.type == "numeric":
            bands = raw.get("bands")
            if not isinstance(bands, list) or not bands:
                raise RubricError(
                    "numeric criterion %r needs a non-empty 'bands' array" % self.id
                )
            parsed = []
            for band in bands:
                if not isinstance(band, Mapping) or "score" not in band:
                    raise RubricError(
                        "criterion %r has a malformed band: %r" % (self.id, band)
                    )
                parsed.append(
                    {
                        "min": band.get("min"),
                        "max": band.get("max"),
                        "score": _check_score(band["score"], scale, self.id),
                    }
                )
            # Highest threshold first so the first match wins.
            parsed.sort(
                key=lambda b: b["min"] if b["min"] is not None else float("-inf"),
                reverse=True,
            )
            self.bands = parsed
        elif self.type == "boolean":
            self.true_score = _check_score(raw.get("true_score", scale), scale, self.id)
            self.false_score = _check_score(raw.get("false_score", 0), scale, self.id)
        elif self.type == "categorical":
            mapping = raw.get("map")
            if not isinstance(mapping, Mapping) or not mapping:
                raise RubricError(
                    "categorical criterion %r needs a non-empty 'map'" % self.id
                )
            self.map = {
                str(key).strip().lower(): _check_score(value, scale, self.id)
                for key, value in mapping.items()
            }
            self.default = _check_score(raw.get("default", 0), scale, self.id)
        else:
            raise RubricError(
                "criterion %r has unknown type %r; use numeric, boolean, or "
                "categorical" % (self.id, self.type)
            )

    def score(self, value: Any) -> Optional[float]:
        """Score a raw value, or ``None`` when the data is missing.

        Returning ``None`` rather than zero is the whole point — see the module
        docstring.
        """
        # An explicit entry in a categorical map always wins over the
        # missing-data check. Otherwise a rubric that legitimately maps a
        # value like "unknown" as a *state* ("we asked, nobody could say")
        # would have that answer silently reclassified as "nobody filled the
        # field in" — two genuinely different things that would then be
        # impossible to tell apart in the coverage figure.
        if self.type == "categorical" and value is not None:
            explicit = self.map.get(str(value).strip().lower())
            if explicit is not None:
                return explicit

        if _is_missing(value):
            return None

        if self.type == "numeric":
            try:
                number = float(str(value).replace(",", "").replace("$", ""))
            except (TypeError, ValueError):
                return None
            for band in self.bands:
                low = band["min"]
                high = band["max"]
                if low is not None and number < low:
                    continue
                if high is not None and number > high:
                    continue
                return band["score"]
            return 0.0

        if self.type == "boolean":
            truthy = str(value).strip().lower() in ("true", "yes", "y", "1", "t")
            return self.true_score if truthy else self.false_score

        key = str(value).strip().lower()
        return self.map.get(key, self.default)


def _check_score(value: Any, scale: float, criterion_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RubricError(
            "criterion %r has a non-numeric score %r" % (criterion_id, value)
        )
    if not (0 <= value <= scale):
        raise RubricError(
            "criterion %r has score %r outside the 0–%s scale"
            % (criterion_id, value, scale)
        )
    return float(value)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    return bool(isinstance(value, str) and value.strip().lower() in _MISSING)


class Rubric:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        if not isinstance(raw, Mapping):
            raise RubricError("rubric must be a JSON object")
        self.name = str(raw.get("name") or "Unnamed rubric")

        scale = raw.get("scale", 5)
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or scale <= 0:
            raise RubricError("'scale' must be a positive number")
        self.scale = float(scale)

        criteria = raw.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise RubricError("rubric needs a non-empty 'criteria' array")
        self.criteria = [Criterion(item, self.scale) for item in criteria]

        seen = set()
        for criterion in self.criteria:
            if criterion.id in seen:
                raise RubricError("duplicate criterion id %r" % criterion.id)
            seen.add(criterion.id)

        self.disqualifiers = []
        for item in raw.get("disqualifiers") or []:
            if not isinstance(item, Mapping):
                raise RubricError("each disqualifier must be an object")
            field = item.get("field")
            op = item.get("op")
            if not field or op not in (
                "<",
                "<=",
                ">",
                ">=",
                "==",
                "!=",
                "in",
                "not in",
            ):
                raise RubricError(
                    "disqualifier needs 'field' and a valid 'op' "
                    "(<, <=, >, >=, ==, !=, in, not in): %r" % (item,)
                )
            if not item.get("reason"):
                raise RubricError(
                    "disqualifier on %r needs a 'reason'. A record removed "
                    "without a stated reason looks like a bug to whoever "
                    "reviews the list." % field
                )
            self.disqualifiers.append(item)

        # Below this share of scoring weight, a record is not ranked at all.
        # It is held out as "research this first", because a fit score built on
        # a minority of the criteria is an opinion wearing a percentage sign.
        min_coverage = raw.get("min_coverage", 0.6)
        if (
            isinstance(min_coverage, bool)
            or not isinstance(min_coverage, (int, float))
            or not (0 <= min_coverage <= 1)
        ):
            raise RubricError("'min_coverage' must be between 0 and 1")
        self.min_coverage = float(min_coverage)

        tiers = raw.get("tiers") or [
            {"min": 0.8, "label": "A"},
            {"min": 0.6, "label": "B"},
            {"min": 0.4, "label": "C"},
            {"min": 0.0, "label": "D"},
        ]
        self.tiers = sorted(tiers, key=lambda t: t["min"], reverse=True)

        self.total_weight = sum(c.weight for c in self.criteria)

    def tier(self, fit: float) -> str:
        for entry in self.tiers:
            if fit >= entry["min"]:
                return str(entry["label"])
        return str(self.tiers[-1]["label"]) if self.tiers else "?"


def _disqualified(rubric: Rubric, record: Mapping[str, Any]) -> Optional[str]:
    for rule in rubric.disqualifiers:
        value = record.get(rule["field"])
        if _is_missing(value):
            continue
        op = rule["op"]
        target = rule["value"]
        try:
            if op in ("<", "<=", ">", ">="):
                number = float(str(value).replace(",", "").replace("$", ""))
                target_number = float(target)
                hit = (
                    (op == "<" and number < target_number)
                    or (op == "<=" and number <= target_number)
                    or (op == ">" and number > target_number)
                    or (op == ">=" and number >= target_number)
                )
            elif op == "==":
                hit = str(value).strip().lower() == str(target).strip().lower()
            elif op == "!=":
                hit = str(value).strip().lower() != str(target).strip().lower()
            elif op == "in":
                hit = str(value).strip().lower() in [
                    str(t).strip().lower() for t in target
                ]
            else:  # not in
                hit = str(value).strip().lower() not in [
                    str(t).strip().lower() for t in target
                ]
        except (TypeError, ValueError):
            continue
        if hit:
            return str(rule["reason"])
    return None


def score_record(rubric: Rubric, record: Mapping[str, Any]) -> Dict[str, Any]:
    """Score one record, reporting both fit and how much data backed it."""
    disqualifier = _disqualified(rubric, record)

    earned = 0.0
    known_weight = 0.0
    detail: List[Dict[str, Any]] = []
    missing: List[str] = []

    for criterion in rubric.criteria:
        raw_value = record.get(criterion.id)
        points = criterion.score(raw_value)
        if points is None:
            missing.append(criterion.label)
            detail.append(
                {
                    "id": criterion.id,
                    "label": criterion.label,
                    "weight": criterion.weight,
                    "value": None,
                    "score": None,
                }
            )
            continue
        known_weight += criterion.weight
        earned += points * criterion.weight
        detail.append(
            {
                "id": criterion.id,
                "label": criterion.label,
                "weight": criterion.weight,
                "value": raw_value,
                "score": points,
            }
        )

    # Fit is computed over *known* weight only, so an unresearched account is
    # reported as low-coverage rather than low-fit. Scoring it over total
    # weight would bury good accounts nobody has looked at yet.
    fit = (earned / (known_weight * rubric.scale)) if known_weight else 0.0
    coverage = known_weight / rubric.total_weight if rubric.total_weight else 0.0

    if disqualifier:
        tier = "OUT"
    elif coverage < rubric.min_coverage:
        tier = "UNKNOWN"
    else:
        tier = rubric.tier(fit)

    return {
        "record": dict(record),
        "fit": fit,
        "coverage": coverage,
        "tier": tier,
        "disqualified": disqualifier is not None,
        "disqualifier_reason": disqualifier,
        "missing_criteria": missing,
        "detail": detail,
        "confidence_note": _confidence_note(coverage, missing, rubric.min_coverage),
    }


def _confidence_note(
    coverage: float, missing: Sequence[str], min_coverage: float = 0.6
) -> str:
    if coverage >= 0.999:
        return "Fully covered."
    if coverage >= min_coverage:
        return "Missing %s — fill these before acting on the rank." % ", ".join(missing)
    return (
        "Only %s of scoring weight has data. This is not a low-fit record, it "
        "is an unresearched one. Missing: %s" % (fmt_pct(coverage), ", ".join(missing))
    )


def score_all(
    rubric: Rubric, records: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Score and rank records, qualified first, then by fit."""
    scored = [score_record(rubric, record) for record in records]
    # Order: researched and qualified first, then under-researched, then
    # disqualified. Sorting purely by fit would float a barely-researched
    # record above a fully-diligenced one, which is the exact mistake the
    # coverage metric exists to prevent.
    scored.sort(
        key=lambda r: (
            r["disqualified"],
            r["tier"] == "UNKNOWN",
            -(r["fit"] if not r["disqualified"] else 0),
            -r["coverage"],
        )
    )
    return scored


def to_markdown(
    rubric: Rubric, scored: Sequence[Mapping[str, Any]], name_field: str
) -> str:
    lines: List[str] = []
    lines.append("# %s" % rubric.name)
    lines.append("")

    qualified = [r for r in scored if not r["disqualified"]]
    unknown = [r for r in qualified if r["tier"] == "UNKNOWN"]
    lines.append(
        "%d record(s) scored against %d criteria. %d disqualified, %d ranked, "
        "%d held back as insufficiently researched."
        % (
            len(scored),
            len(rubric.criteria),
            len(scored) - len(qualified),
            len(qualified) - len(unknown),
            len(unknown),
        )
    )
    lines.append("")

    rows = []
    for entry in scored:
        record = entry["record"]
        rows.append(
            [
                record.get(name_field, "(unnamed)"),
                entry["tier"],
                fmt_pct(entry["fit"]) if not entry["disqualified"] else "—",
                fmt_pct(entry["coverage"]),
                entry["disqualifier_reason"] or entry["confidence_note"],
            ]
        )
    lines.append(table(["Record", "Tier", "Fit", "Coverage", "Notes"], rows))
    lines.append("")

    if unknown:
        lines.append("## Research these before ranking them")
        lines.append("")
        lines.append(
            "These records fell below %s data coverage. Ranking them against "
            "fully-researched peers would be comparing a measurement to a "
            "guess." % fmt_pct(rubric.min_coverage)
        )
        lines.append("")
        for entry in unknown:
            lines.append(
                "- **%s** — missing %s"
                % (
                    entry["record"].get(name_field, "(unnamed)"),
                    ", ".join(entry["missing_criteria"]),
                )
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by [gtm-skills](https://github.com/erickdronski/gtm-skills)._"
    )
    return "\n".join(lines)


def load_records(path: str) -> List[Dict[str, Any]]:
    """Load records from CSV or JSON, inferring from the extension."""
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data = data.get("records", [])
        if not isinstance(data, list):
            raise RubricError(
                "%s must contain a JSON array of records (or an object with a "
                "'records' array)" % path
            )
        return data
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m gtmkit.scoring",
        description=(
            "Score records against a weighted rubric, reporting both fit and "
            "how much of the score had real data behind it."
        ),
    )
    parser.add_argument("--rubric", required=True, help="path to rubric JSON")
    parser.add_argument("--records", required=True, help="path to records CSV or JSON")
    parser.add_argument(
        "--name-field",
        default="name",
        help="field to display as the record label (default: name)",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        with open(args.rubric, "r", encoding="utf-8") as handle:
            rubric = Rubric(json.load(handle))
        records = load_records(args.records)
    except FileNotFoundError as exc:
        sys.stderr.write("file not found: %s\n" % exc.filename)
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write("invalid JSON: %s\n" % exc)
        return 2
    except RubricError as exc:
        sys.stderr.write("rubric error: %s\n" % exc)
        return 2

    if not records:
        sys.stderr.write("no records found in %s\n" % args.records)
        return 2

    scored = score_all(rubric, records)
    output = (
        json.dumps({"rubric": rubric.name, "results": scored}, indent=2, default=str)
        if args.format == "json"
        else to_markdown(rubric, scored, args.name_field)
    )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
        sys.stderr.write("wrote %s\n" % args.out)
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
