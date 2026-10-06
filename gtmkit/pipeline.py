"""Pipeline coverage and a weighted forecast that admits where its odds came from.

A pipeline review usually reports three numbers — coverage, a weighted
forecast, and a commit — and the arithmetic behind all three is trivial. The
problem is the stage probabilities. They were typed into a CRM picklist years
ago, nobody remembers by whom, and the forecast inherits a precision nobody
ever measured::

    python3 -m gtmkit.pipeline pipeline.csv --stages stages.json \\
        --target 1200000 --closed 95000 --period-end 2026-12-31 --as-of 2026-10-06

So every stage probability enters through the assumption ledger. A measured
stage-to-close rate is a fact with a named report behind it; anything else is
an assumption with a range, and a CRM default declared as a fact is refused.
Without ``--stages`` the module falls back to a placeholder model whose every
probability is a ranged assumption, and the output says so before anything
else.

What it reports beyond the totals:

* **The coverage your own probabilities require.** "2.2x coverage" means
  nothing until the reader knows this stage mix needs 2.6x.
* **The spread.** The weighted forecast is the mean of a lumpy distribution,
  and its standard deviation sits next to it.
* **Hygiene.** Close dates already past, dates that have been pushed, and
  deals nobody has touched, all relative to an explicit as-of date.
* **Concentration.** The share held by the largest deals, and what the
  forecast looks like if the largest one slips.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .evidence import EvidenceError, grade_evidence, validate_input
from .fmt import fmt_currency, fmt_pct, table
from .scoring import RubricError, load_records

__all__ = [
    "CATEGORIES",
    "DEFAULT_STALE_DAYS",
    "PipelineError",
    "StageModel",
    "analyze",
    "default_stage_model",
    "load_stage_model",
    "main",
    "to_markdown",
]

#: Forecast categories in the order a commit call is built up.
CATEGORIES = ("commit", "best_case", "pipeline")
_CATEGORY_LABELS = {
    "commit": "Commit",
    "best_case": "Best case",
    "pipeline": "Pipeline",
    "uncategorized": "Uncategorized",
    "omitted": "Omitted",
}
_CATEGORY_ALIASES = {
    "commit": "commit",
    "committed": "commit",
    "best_case": "best_case",
    "bestcase": "best_case",
    "upside": "best_case",
    "pipeline": "pipeline",
    "omitted": "omitted",
    "omit": "omitted",
}
_CLOSED_STAGES = frozenset(("closed", "closed_won", "closed_lost", "won", "lost"))

#: A CRM's built-in stage percentages are a setting someone chose, not a rate
#: anyone measured, so they cannot be declared as facts.
_CRM_DEFAULT_RE = re.compile(
    r"\b(default|picklist|pick[\s-]list|out[\s-]of[\s-]the[\s-]box)\b", re.IGNORECASE
)

#: A policy, not a measurement: a month with no logged touch on an open deal.
#: Wrong for motions with long, quiet legal or procurement stretches, which is
#: why --stale-days and the model's stale_after_days override it.
DEFAULT_STALE_DAYS = 30

#: Below about ten deals, one outcome moves the total by more than the
#: weighting suggests, so the output says to treat the commit view as the call.
#: The standard deviation printed beside the forecast is the real measure; this
#: threshold only decides when to say it in words.
_THIN_PIPELINE = 10

#: When one deal is a quarter of the pipeline, the forecast is mostly a bet on
#: that deal, and the weighted figure hides it by spreading the deal's outcome
#: across its probability.
_CONCENTRATED = 0.25

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Used only when no stage model is supplied. Every value is an assumption with
#: a wide range, and the source says plainly that nothing was measured, so the
#: evidence grade reads F and the output leads with that. The stage ids match
#: the deal-qualification rubric's, so one vocabulary serves both engines.
_DEFAULT_STAGES = (
    ("discovery", "Discovery", 0.10, 0.05, 0.20, "pipeline"),
    ("qualification", "Qualification", 0.20, 0.10, 0.30, "pipeline"),
    ("solution", "Solution", 0.35, 0.20, 0.50, "pipeline"),
    ("proposal", "Proposal", 0.55, 0.35, 0.70, "best_case"),
    ("negotiation", "Negotiation", 0.75, 0.55, 0.85, "best_case"),
    ("closing", "Closing", 0.90, 0.75, 0.95, "commit"),
)
_DEFAULT_SOURCE = (
    "gtmkit placeholder, not measured from any pipeline; replace it with your "
    "own stage-to-close history"
)


class PipelineError(ValueError):
    """Raised for pipelines or stage models that cannot support a forecast."""


def _norm(value: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower())


# -- the stage model ---------------------------------------------------------


class StageModel:
    """Ordered stages, each with a probability that is a ledger entry."""

    def __init__(
        self,
        name: str,
        currency: str,
        stages: List[Dict[str, Any]],
        stale_after_days: Optional[int] = None,
        is_default: bool = False,
        notes: Optional[List[str]] = None,
    ) -> None:
        self.name = name
        self.currency = currency
        self.stages = stages
        self.index = {stage["id"]: i for i, stage in enumerate(stages)}
        self.stale_after_days = stale_after_days
        self.is_default = is_default
        self.notes = list(notes or [])


def load_stage_model(raw: Mapping[str, Any]) -> StageModel:
    """Validate a stage model spec.

    Shape::

        {
          "name": "Stage-to-close, FY2026 history",
          "currency": "USD",
          "stale_after_days": 30,
          "stages": [
            {"id": "discovery", "label": "Discovery", "category": "pipeline",
             "probability": {"value": 0.08, "confidence": "fact",
                             "source": "Salesforce stage-history report ..."}}
          ]
        }

    ``category`` is used only for deals whose rows carry no forecast category.
    """
    if not isinstance(raw, Mapping):
        raise PipelineError("stage model must be a JSON object")
    raw_stages = raw.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise PipelineError(
            "stage model needs a non-empty 'stages' array, earliest stage first"
        )

    stages: List[Dict[str, Any]] = []
    notes: List[str] = []
    highest: Optional[Tuple[str, float]] = None
    for position, item in enumerate(raw_stages):
        if not isinstance(item, Mapping):
            raise PipelineError("stages[%d] must be an object" % position)
        stage_id = _norm(item.get("id") or "")
        if not stage_id:
            raise PipelineError("stages[%d] needs an 'id'" % position)
        if any(stage["id"] == stage_id for stage in stages):
            raise PipelineError("duplicate stage id %r" % stage_id)
        if stage_id in _CLOSED_STAGES:
            raise PipelineError(
                "stage %r is a closed stage. Closed-won revenue goes in "
                "--closed; closed-lost is not pipeline." % stage_id
            )

        category = item.get("category")
        if category is not None:
            category = _CATEGORY_ALIASES.get(_norm(category))
            if category not in CATEGORIES:
                raise PipelineError(
                    "stage %r has category %r; use one of %s"
                    % (stage_id, item.get("category"), ", ".join(CATEGORIES))
                )

        try:
            probability = validate_input("probability", item.get("probability"))
        except EvidenceError as exc:
            raise PipelineError("stage %r: %s" % (stage_id, exc)) from exc
        low, high = probability.range
        if not (0 < probability.value <= 1) or low < 0 or high > 1:
            raise PipelineError(
                "stage %r has probability %r (range %r to %r). Probabilities "
                "are decimals between 0 and 1: 35%% is 0.35, not 35."
                % (stage_id, probability.value, low, high)
            )
        if probability.confidence == "fact" and _CRM_DEFAULT_RE.search(
            probability.source
        ):
            raise PipelineError(
                "stage %r declares a CRM default probability as a measured "
                "fact (%r). A default is a setting someone typed into a "
                "picklist, not a conversion rate anyone measured. Mark it "
                "confidence 'assumption' with a low/high range, or replace it "
                "with your own stage-to-close history." % (stage_id, probability.source)
            )

        if highest is not None and probability.value < highest[1]:
            notes.append(
                "Stage %r has a lower probability (%s) than the earlier stage "
                "%r (%s). Usually an ordering mistake, or a holding stage that "
                "deals stall in."
                % (
                    stage_id,
                    fmt_pct(probability.value),
                    highest[0],
                    fmt_pct(highest[1]),
                )
            )
        if highest is None or probability.value > highest[1]:
            highest = (stage_id, probability.value)

        stages.append(
            {
                "id": stage_id,
                "label": str(item.get("label") or stage_id),
                "category": category,
                "probability": probability,
            }
        )

    stale = raw.get("stale_after_days")
    if stale is not None and (
        isinstance(stale, bool) or not isinstance(stale, int) or stale <= 0
    ):
        raise PipelineError("'stale_after_days' must be a positive whole number")

    return StageModel(
        name=str(raw.get("name") or "Stage model"),
        currency=str(raw.get("currency") or "USD").strip().upper(),
        stages=stages,
        stale_after_days=stale,
        notes=notes,
    )


def default_stage_model() -> StageModel:
    """The placeholder model: six stages, every probability a wide assumption."""
    model = load_stage_model(
        {
            "name": "gtmkit placeholder stages (not measured)",
            "stages": [
                {
                    "id": stage_id,
                    "label": label,
                    "category": category,
                    "probability": {
                        "value": value,
                        "confidence": "assumption",
                        "source": _DEFAULT_SOURCE,
                        "low": low,
                        "high": high,
                    },
                }
                for stage_id, label, value, low, high, category in _DEFAULT_STAGES
            ],
        }
    )
    model.is_default = True
    return model


# -- rows ----------------------------------------------------------------------


def _parse_date(value: Any) -> Optional[datetime.date]:
    """Parse a YYYY-MM-DD date, or return None when it cannot be read.

    The format is pinned because ``fromisoformat`` accepts more shapes on newer
    Pythons than on 3.9, and a file should parse the same on every version.
    US-style dates are refused rather than guessed: 03/04 is two different days.
    """
    text = "" if value is None else str(value).strip()
    if not _ISO_DATE_RE.match(text):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _require_date(value: Any, flag: str) -> datetime.date:
    parsed = _parse_date(value)
    if parsed is None:
        raise PipelineError(
            "%s must be a date written YYYY-MM-DD, got %r" % (flag, value)
        )
    return parsed


def _parse_amount(value: Any) -> Optional[float]:
    text = "" if value is None else str(value).strip()
    text = re.sub(r"[\s,$€£¥]", "", text)
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return amount if math.isfinite(amount) else None


def _parse_rows(
    rows: Sequence[Mapping[str, Any]], model: StageModel, name_field: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], set]:
    """Split rows into usable deals, excluded rows, and ignored values.

    A row missing something the totals need (amount, a known stage, a close
    date) is excluded with its reason. A row with an unreadable optional
    value keeps its place in the totals and loses only that check — excluding
    a large deal over a malformed activity date would move the forecast more
    than the bad date ever could.
    """
    deals: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    ignored: List[Dict[str, Any]] = []
    columns: set = set()
    name_key = _norm(name_field)

    for number, raw in enumerate(rows, start=1):
        row = {
            _norm(key): (value.strip() if isinstance(value, str) else value)
            for key, value in raw.items()
            if key is not None
        }
        columns.update(key for key, value in row.items() if value not in (None, ""))
        name = str(row.get(name_key) or "").strip() or "(row %d)" % number
        problems = []

        stage = _norm(row.get("stage") or "")
        if not stage:
            problems.append("no stage")
        elif stage in _CLOSED_STAGES:
            problems.append(
                "closed, so not open pipeline (pass closed-won revenue with --closed)"
            )
        elif stage not in model.index:
            problems.append(
                "stage %r is not in the stage model (%s)"
                % (row.get("stage"), ", ".join(model.index))
            )

        amount = _parse_amount(row.get("amount"))
        if amount is None:
            problems.append("amount %r is not a number" % (row.get("amount"),))
        elif amount <= 0:
            problems.append(
                "amount must be positive; a zero-amount deal is a placeholder "
                "that inflates the deal count"
            )

        close_date = _parse_date(row.get("close_date"))
        if close_date is None:
            problems.append(
                "close_date %r is not a YYYY-MM-DD date" % (row.get("close_date"),)
            )

        category = None
        category_source = None
        raw_category = row.get("forecast_category")
        if raw_category not in (None, ""):
            category = _CATEGORY_ALIASES.get(_norm(raw_category))
            if category is None:
                problems.append(
                    "forecast_category %r is not one of commit, best_case, "
                    "pipeline, omitted" % raw_category
                )
            category_source = "rep"

        if problems:
            excluded.append(
                {"row": number, "deal": name, "reason": "; ".join(problems)}
            )
            continue

        stage_info = model.stages[model.index[stage]]
        if category is None:
            category = stage_info["category"] or "uncategorized"
            category_source = "stage" if stage_info["category"] else None

        optional: Dict[str, Optional[datetime.date]] = {}
        for field in ("last_activity", "original_close_date"):
            value = row.get(field)
            optional[field] = _parse_date(value)
            if value not in (None, "") and optional[field] is None:
                ignored.append(
                    {
                        "row": number,
                        "deal": name,
                        "field": field,
                        "reason": "%r is not a YYYY-MM-DD date" % value,
                    }
                )

        push_count = None
        raw_pushes = row.get("push_count")
        if raw_pushes not in (None, ""):
            try:
                push_count = int(str(raw_pushes))
                if push_count < 0:
                    raise ValueError
            except ValueError:
                push_count = None
                ignored.append(
                    {
                        "row": number,
                        "deal": name,
                        "field": "push_count",
                        "reason": "%r is not a whole number" % raw_pushes,
                    }
                )

        probability = stage_info["probability"]
        low, high = probability.range
        deals.append(
            {
                "row": number,
                "name": name,
                "owner": row.get("owner") or None,
                "amount": amount,
                "stage": stage,
                "stage_label": stage_info["label"],
                "probability": probability.value,
                "probability_low": low,
                "probability_high": high,
                "confidence": probability.confidence,
                "close_date": close_date,
                "category": category,
                "category_source": category_source,
                "last_activity": optional["last_activity"],
                "original_close_date": optional["original_close_date"],
                "push_count": push_count,
            }
        )
    return deals, excluded, ignored, columns


# -- the analysis -------------------------------------------------------------


def _hygiene(
    deal: Mapping[str, Any], as_of: datetime.date, stale_days: int
) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    if deal["close_date"] < as_of:
        days = (as_of - deal["close_date"]).days
        flags.append(
            {
                "kind": "past_due",
                "days": days,
                "text": "close date passed %d day%s ago" % (days, _s(days)),
            }
        )
    original = deal["original_close_date"]
    if original is not None and deal["close_date"] > original:
        days = (deal["close_date"] - original).days
        flags.append(
            {
                "kind": "pushed",
                "days": days,
                "text": "pushed %d day%s from %s"
                % (days, _s(days), original.isoformat()),
            }
        )
    if deal["push_count"]:
        count = deal["push_count"]
        flags.append(
            {
                "kind": "push_count",
                "count": count,
                "text": "pushed %d time%s" % (count, _s(count)),
            }
        )
    last = deal["last_activity"]
    if last is not None and (as_of - last).days > stale_days:
        days = (as_of - last).days
        flags.append(
            {
                "kind": "stale",
                "days": days,
                "text": "no activity in %d days" % days,
            }
        )
    return flags


def _s(count: int) -> str:
    return "" if count == 1 else "s"


def analyze(
    records: Sequence[Mapping[str, Any]],
    model: Optional[StageModel] = None,
    as_of: Optional[datetime.date] = None,
    target: Optional[float] = None,
    closed: float = 0.0,
    period_end: Optional[datetime.date] = None,
    top: int = 3,
    stale_days: Optional[int] = None,
    name_field: str = "opportunity",
) -> Dict[str, Any]:
    """Coverage, weighted forecast, categories, hygiene, and concentration.

    ``records`` are rows with at least ``amount``, ``stage``, and
    ``close_date``; ``forecast_category``, ``owner``, ``last_activity``,
    ``original_close_date``, and ``push_count`` are used when present. Column
    names are matched case-insensitively with spaces as underscores, so a
    "Close Date" header works.
    """
    if not records:
        raise PipelineError("no rows to analyze")
    model = model or default_stage_model()
    as_of = as_of or datetime.date.today()
    if target is not None and target <= 0:
        raise PipelineError("--target must be positive")
    if closed < 0:
        raise PipelineError("--closed cannot be negative")
    if top < 1:
        raise PipelineError("--top must be at least 1")
    if stale_days is not None and stale_days <= 0:
        raise PipelineError("--stale-days must be positive")
    stale_days = stale_days or model.stale_after_days or DEFAULT_STALE_DAYS

    deals, excluded, ignored, columns = _parse_rows(records, model, name_field)
    if not deals:
        raise PipelineError(
            "none of the %d row(s) could be used. First problem: row %d (%s): %s"
            % (
                len(records),
                excluded[0]["row"],
                excluded[0]["deal"],
                excluded[0]["reason"],
            )
        )

    for deal in deals:
        deal["weighted"] = deal["amount"] * deal["probability"]
        deal["weighted_low"] = deal["amount"] * deal["probability_low"]
        deal["weighted_high"] = deal["amount"] * deal["probability_high"]
        deal["flags"] = _hygiene(deal, as_of, stale_days)

    in_period = []
    later = []
    omitted = []
    for deal in deals:
        if deal["category"] == "omitted":
            omitted.append(deal)
        elif period_end is not None and deal["close_date"] > period_end:
            later.append(deal)
        else:
            in_period.append(deal)

    pipeline_amount = sum(d["amount"] for d in in_period)
    weighted = sum(d["weighted"] for d in in_period)
    weighted_low = sum(d["weighted_low"] for d in in_period)
    weighted_high = sum(d["weighted_high"] for d in in_period)
    # Each deal treated as an independent win-or-lose draw at its stage
    # probability. Correlated deals (one budget freeze hits several) make the
    # real spread wider than this, never narrower.
    spread = math.sqrt(
        sum(
            d["amount"] ** 2 * d["probability"] * (1 - d["probability"])
            for d in in_period
        )
    )
    blended = weighted / pipeline_amount if pipeline_amount else None

    remaining = None if target is None else target - closed
    coverage = (
        pipeline_amount / remaining if remaining is not None and remaining > 0 else None
    )
    landing = closed + weighted

    ordered = sorted(in_period, key=lambda d: (-d["amount"], d["name"]))
    concentration = None
    if ordered:
        largest = ordered[0]
        top_deals = ordered[:top]
        running = 0.0
        to_half = 0
        for deal in ordered:
            running += deal["amount"]
            to_half += 1
            if running >= pipeline_amount / 2:
                break
        concentration = {
            "top": top,
            "top_deals": [
                {
                    "name": d["name"],
                    "amount": d["amount"],
                    "share": d["amount"] / pipeline_amount,
                }
                for d in top_deals
            ],
            "top_share": sum(d["amount"] for d in top_deals) / pipeline_amount,
            "top_weighted_share": (
                sum(d["weighted"] for d in top_deals) / weighted if weighted else None
            ),
            "largest": {
                "name": largest["name"],
                "amount": largest["amount"],
                "share": largest["amount"] / pipeline_amount,
            },
            "deals_to_half": to_half,
            "without_largest": {
                "weighted": weighted - largest["weighted"],
                "landing": landing - largest["weighted"],
                "coverage": (
                    (pipeline_amount - largest["amount"]) / remaining
                    if remaining is not None and remaining > 0
                    else None
                ),
            },
        }

    categories = []
    running_amount = closed
    for key in (*CATEGORIES, "uncategorized"):
        members = [d for d in in_period if d["category"] == key]
        if key == "uncategorized" and not members:
            continue
        amount = sum(d["amount"] for d in members)
        running_amount += amount
        needs_attention = [d for d in members if d["flags"]]
        categories.append(
            {
                "category": key,
                "label": _CATEGORY_LABELS[key],
                "deals": len(members),
                "amount": amount,
                "weighted": sum(d["weighted"] for d in members),
                "cumulative_with_closed": running_amount,
                "share_of_target": (running_amount / target) if target else None,
                "flagged_deals": len(needs_attention),
                "flagged_amount": sum(d["amount"] for d in needs_attention),
            }
        )

    stage_rows = []
    for stage in model.stages:
        members = [d for d in in_period if d["stage"] == stage["id"]]
        probability = stage["probability"]
        stage_rows.append(
            {
                "id": stage["id"],
                "label": stage["label"],
                "probability": probability.value,
                "low": probability.range[0],
                "high": probability.range[1],
                "confidence": probability.confidence,
                "source": probability.source,
                "deals": len(members),
                "amount": sum(d["amount"] for d in members),
                "weighted": sum(d["weighted"] for d in members),
            }
        )

    evidence = grade_evidence([(d["confidence"], d["weighted"]) for d in in_period])

    category_order = {key: i for i, key in enumerate((*CATEGORIES, "uncategorized"))}
    flagged = sorted(
        (d for d in deals if d["flags"]),
        key=lambda d: (category_order.get(d["category"], 9), -d["amount"], d["name"]),
    )

    result: Dict[str, Any] = {
        "model": model.name,
        "model_is_default": model.is_default,
        "currency": model.currency,
        "as_of": as_of.isoformat(),
        "period_end": period_end.isoformat() if period_end else None,
        "stale_after_days": stale_days,
        "target": target,
        "closed": closed,
        "remaining": remaining,
        "deals_in_period": len(in_period),
        "pipeline": pipeline_amount,
        "weighted": weighted,
        "weighted_low": weighted_low,
        "weighted_high": weighted_high,
        "spread": spread,
        "blended_probability": blended,
        "coverage": coverage,
        "required_coverage": (1 / blended) if blended else None,
        "landing": landing,
        "landing_low": closed + weighted_low,
        "landing_high": closed + weighted_high,
        "gap": (landing - target) if target is not None else None,
        "categories": categories,
        "category_sources": {
            source: sum(1 for d in in_period if d["category_source"] == source)
            for source in ("rep", "stage")
        },
        "concentration": concentration,
        "evidence": evidence,
        "stages": stage_rows,
        "hygiene": [_public(d) for d in flagged],
        "later": {
            "deals": len(later),
            "amount": sum(d["amount"] for d in later),
        },
        "omitted": {
            "deals": len(omitted),
            "amount": sum(d["amount"] for d in omitted),
        },
        "excluded_rows": excluded,
        "ignored_values": ignored,
        "deals": [_public(d) for d in deals],
    }
    result["notes"] = _notes(result, model, columns)
    return result


def _public(deal: Mapping[str, Any]) -> Dict[str, Any]:
    """A JSON-ready copy: dates as ISO strings."""
    out = dict(deal)
    for key in ("close_date", "last_activity", "original_close_date"):
        if out.get(key) is not None:
            out[key] = out[key].isoformat()
    return out


def _notes(result: Mapping[str, Any], model: StageModel, columns: set) -> List[str]:
    cur = result["currency"]
    notes: List[str] = []
    if model.is_default:
        notes.append(
            "No stage model was supplied, so these are gtmkit's placeholder "
            "probabilities: every one an assumption with a wide range, measured "
            "from nobody's pipeline. This is a scenario, not a forecast. Supply "
            "--stages built from your own stage-to-close history before the "
            "number goes in front of anyone."
        )
    elif result["evidence"]["share_assumption"] >= 0.999:
        notes.append(
            "Every stage probability in use is an assumption, so the weighted "
            "figure is a scenario, not a forecast. Say so where it is shown."
        )

    count = result["deals_in_period"]
    if count == 0:
        notes.append(
            "No open deal closes inside the period, so there is nothing to "
            "forecast from; the target rests entirely on revenue already closed."
        )
    elif count < _THIN_PIPELINE:
        notes.append(
            "Only %d deal%s in the period. With this few, single outcomes "
            "dominate: one standard deviation is %s, %s of the weighted figure. "
            "Treat the commit view as the call and the weighted number as a "
            "cross-check."
            % (
                count,
                _s(count),
                fmt_currency(result["spread"], cur),
                fmt_pct(result["spread"] / result["weighted"])
                if result["weighted"]
                else "n/a",
            )
        )
    concentration = result["concentration"]
    if concentration and concentration["largest"]["share"] >= _CONCENTRATED:
        notes.append(
            "%s is %s of the pipeline on its own. The forecast is mostly a bet "
            "on that deal; without it the weighted figure is %s."
            % (
                concentration["largest"]["name"],
                fmt_pct(concentration["largest"]["share"]),
                fmt_currency(concentration["without_largest"]["weighted"], cur),
            )
        )

    if result["target"] is None:
        notes.append("No --target, so coverage and the gap were not computed.")
    elif result["remaining"] is not None and result["remaining"] <= 0:
        notes.append(
            "Closed revenue already meets the target, so coverage is not "
            "meaningful; everything open is upside."
        )
    if result["period_end"] is None:
        notes.append(
            "No --period-end, so every open deal counts toward this period "
            "whatever its close date. That overstates in-period coverage."
        )
    elif result["period_end"] < result["as_of"]:
        notes.append(
            "The period ended %s, before the as-of date." % result["period_end"]
        )
    if "last_activity" not in columns:
        notes.append("No last_activity column, so stale deals were not checked.")
    if not ({"original_close_date", "push_count"} & columns):
        notes.append(
            "No original_close_date or push_count column, so pushed close dates "
            "were not checked; only dates already past were."
        )
    if "probability" in columns:
        notes.append(
            "The file's probability column was ignored. Per-deal CRM "
            "probabilities are usually the picklist default for the stage, "
            "typed in once; the stage model is where a probability has to say "
            "where it came from."
        )
    notes.extend(model.notes)

    sources = result["category_sources"]
    if "forecast_category" in columns and sources["stage"]:
        notes.append(
            "%d deal%s had no forecast_category and took the stage model's "
            "category instead." % (sources["stage"], _s(sources["stage"]))
        )
    points = [
        r["label"] for r in result["stages"] if r["deals"] and r["low"] == r["high"]
    ]
    if points:
        notes.append(
            "The forecast range comes only from the low/high stated on each "
            "probability, and %s state%s a point value. A measured rate carries "
            "sampling error too, which the range does not show."
            % (", ".join(points), "s" if len(points) == 1 else "")
        )

    later = result["later"]
    if later["deals"]:
        notes.append(
            "%d deal%s worth %s close after the period end and are left out of "
            "coverage and the forecast."
            % (later["deals"], _s(later["deals"]), fmt_currency(later["amount"], cur))
        )
    omitted = result["omitted"]
    if omitted["deals"]:
        notes.append(
            "%d deal%s worth %s are marked omitted by their owners and left out."
            % (
                omitted["deals"],
                _s(omitted["deals"]),
                fmt_currency(omitted["amount"], cur),
            )
        )
    if result["excluded_rows"]:
        notes.append(
            "%d row%s could not be used and are listed at the end. Every total "
            "above leaves them out."
            % (len(result["excluded_rows"]), _s(len(result["excluded_rows"])))
        )
    if result["ignored_values"]:
        notes.append(
            "%d value%s could not be read and were ignored (listed at the end); "
            "those deals stay in the totals but skip that check."
            % (len(result["ignored_values"]), _s(len(result["ignored_values"])))
        )
    return notes


# -- output --------------------------------------------------------------------


def _multiple(value: Optional[float]) -> str:
    return "n/a" if value is None else "%.1fx" % value


def to_markdown(result: Mapping[str, Any]) -> str:
    cur = result["currency"]
    lines: List[str] = ["# Pipeline review", ""]

    context = ["As of %s" % result["as_of"]]
    if result["period_end"]:
        context.append("period ends %s" % result["period_end"])
    context.append(
        "%d open deal%s in period"
        % (result["deals_in_period"], _s(result["deals_in_period"]))
    )
    context.append("stage model: %s" % result["model"])
    lines.append(" · ".join(context))
    lines.append("")

    lines.append("## Headline")
    lines.append("")
    rows = []
    if result["target"] is not None:
        rows.append(
            [
                "Target",
                "%s — %s closed, %s to go"
                % (
                    fmt_currency(result["target"], cur),
                    fmt_currency(result["closed"], cur),
                    fmt_currency(max(result["remaining"], 0), cur),
                ),
            ]
        )
    rows.append(
        [
            "Open pipeline in period",
            "%s across %d deal%s"
            % (
                fmt_currency(result["pipeline"], cur),
                result["deals_in_period"],
                _s(result["deals_in_period"]),
            ),
        ]
    )
    if result["coverage"] is not None:
        rows.append(["Coverage of what is left", _multiple(result["coverage"])])
    if result["required_coverage"] is not None and result["target"] is not None:
        rows.append(
            [
                "Coverage these probabilities need",
                "%s — at these probabilities, %s of pipeline dollars are "
                "expected to close"
                % (
                    _multiple(result["required_coverage"]),
                    fmt_pct(result["blended_probability"]),
                ),
            ]
        )
    rows.append(
        [
            "Weighted forecast",
            "%s (range %s to %s)"
            % (
                fmt_currency(result["weighted"], cur),
                fmt_currency(result["weighted_low"], cur),
                fmt_currency(result["weighted_high"], cur),
            ),
        ]
    )
    if result["target"] is not None:
        gap = result["gap"]
        rows.append(
            [
                "Expected landing",
                "%s — %s %s target (range %s to %s)"
                % (
                    fmt_currency(result["landing"], cur),
                    fmt_currency(abs(gap), cur),
                    "short of" if gap < 0 else "above",
                    fmt_currency(result["landing_low"], cur),
                    fmt_currency(result["landing_high"], cur),
                ),
            ]
        )
    rows.append(
        [
            "Spread",
            "±%s, one standard deviation of the weighted forecast"
            % fmt_currency(result["spread"], cur),
        ]
    )
    concentration = result["concentration"]
    if concentration:
        rows.append(
            [
                "Largest %d deal%s" % (concentration["top"], _s(concentration["top"])),
                "%s of pipeline, %s of the weighted forecast"
                % (
                    fmt_pct(concentration["top_share"]),
                    fmt_pct(concentration["top_weighted_share"]),
                ),
            ]
        )
    lines.append(table(["Metric", "Value"], rows))
    lines.append("")

    # The weak part goes first, the same order the value case uses: how much of
    # the forecast rests on probabilities anyone measured, and what is thin.
    evidence = result["evidence"]
    lines.append("## Evidence grade: %s" % evidence["grade"])
    lines.append("")
    lines.append(
        "Graded on the stage probabilities behind each dollar of the weighted "
        "forecast. %s" % evidence["headline"]
    )
    lines.append("")
    for note in result["notes"]:
        lines.append("- %s" % note)
    if result["notes"]:
        lines.append("")

    lines.append("## Forecast categories")
    lines.append("")
    category_rows = []
    for row in result["categories"]:
        category_rows.append(
            [
                row["label"],
                str(row["deals"]),
                fmt_currency(row["amount"], cur),
                fmt_currency(row["weighted"], cur),
                fmt_currency(row["cumulative_with_closed"], cur),
                fmt_pct(row["share_of_target"])
                if row["share_of_target"] is not None
                else "n/a",
            ]
        )
    lines.append(
        table(
            [
                "Category",
                "Deals",
                "Amount",
                "Weighted",
                "Closed + cumulative",
                "Of target",
            ],
            category_rows,
        )
    )
    lines.append("")
    sources = result["category_sources"]
    lines.append(
        "Categories: %d deal%s by the owner's forecast_category, %d by stage."
        % (sources["rep"], _s(sources["rep"]), sources["stage"])
    )
    commit = next(r for r in result["categories"] if r["category"] == "commit")
    if commit["flagged_deals"]:
        lines.append("")
        lines.append(
            "**%d commit deal%s worth %s carr%s a hygiene flag below.** A commit "
            "with a lapsed date or no recent activity is a forecast nobody has "
            "retested."
            % (
                commit["flagged_deals"],
                _s(commit["flagged_deals"]),
                fmt_currency(commit["flagged_amount"], cur),
                "ies" if commit["flagged_deals"] == 1 else "y",
            )
        )
    lines.append("")

    lines.append("## Needs a new date or a touch")
    lines.append("")
    if result["hygiene"]:
        hygiene_rows = [
            [
                d["name"],
                d["owner"] or "",
                fmt_currency(d["amount"], cur),
                d["stage_label"],
                d["close_date"],
                _CATEGORY_LABELS.get(d["category"], d["category"]),
                "; ".join(flag["text"] for flag in d["flags"]),
            ]
            for d in result["hygiene"]
        ]
        lines.append(
            table(
                ["Deal", "Owner", "Amount", "Stage", "Close", "Category", "Flags"],
                hygiene_rows,
            )
        )
        lines.append("")
        lines.append(
            "Stale means no logged activity in more than %d days. Commit deals "
            "are listed first." % result["stale_after_days"]
        )
    else:
        lines.append("No open deal has a past-due, pushed, or stale flag.")
    lines.append("")

    if concentration:
        lines.append("## Concentration")
        lines.append("")
        top_rows = [
            [d["name"], fmt_currency(d["amount"], cur), fmt_pct(d["share"])]
            for d in concentration["top_deals"]
        ]
        lines.append(table(["Deal", "Amount", "Share of pipeline"], top_rows))
        lines.append("")
        without = concentration["without_largest"]
        sentence = (
            "%d deal%s hold half the pipeline. If %s slips out of the period, "
            "the weighted forecast falls to %s"
            % (
                concentration["deals_to_half"],
                _s(concentration["deals_to_half"]),
                concentration["largest"]["name"],
                fmt_currency(without["weighted"], cur),
            )
        )
        if without["coverage"] is not None:
            sentence += " and coverage to %s" % _multiple(without["coverage"])
        lines.append(sentence + ".")
        lines.append("")

    lines.append("## Stage model")
    lines.append("")
    stage_rows = [
        [
            row["label"],
            fmt_pct(row["probability"]),
            "%s–%s" % (fmt_pct(row["low"]), fmt_pct(row["high"]))
            if row["low"] != row["high"]
            else "point",
            row["confidence"],
            str(row["deals"]),
            fmt_currency(row["amount"], cur),
            fmt_currency(row["weighted"], cur),
            row["source"],
        ]
        for row in result["stages"]
    ]
    lines.append(
        table(
            [
                "Stage",
                "Probability",
                "Range",
                "Confidence",
                "Deals",
                "Amount",
                "Weighted",
                "Source",
            ],
            stage_rows,
        )
    )
    lines.append("")

    if result["excluded_rows"]:
        lines.append("## Rows left out")
        lines.append("")
        lines.append(
            table(
                ["Row", "Deal", "Reason"],
                [
                    [str(r["row"]), r["deal"], r["reason"]]
                    for r in result["excluded_rows"]
                ],
            )
        )
        lines.append("")
    if result["ignored_values"]:
        lines.append("## Values ignored")
        lines.append("")
        lines.append(
            table(
                ["Row", "Deal", "Field", "Reason"],
                [
                    [str(r["row"]), r["deal"], r["field"], r["reason"]]
                    for r in result["ignored_values"]
                ],
            )
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by [gtm-skills](https://github.com/erickdronski/gtm-skills)._"
    )
    return "\n".join(lines)


# -- CLI -----------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m gtmkit.pipeline",
        description=(
            "Pipeline coverage, a weighted forecast with its spread, the "
            "commit view, and hygiene flags, from a pipeline export."
        ),
    )
    parser.add_argument("records", help="pipeline CSV or JSON, one row per open deal")
    parser.add_argument(
        "--stages",
        help="stage model JSON with sourced probabilities (default: a labelled "
        "placeholder model)",
    )
    parser.add_argument("--target", type=float, help="revenue target for the period")
    parser.add_argument(
        "--closed",
        type=float,
        default=0.0,
        help="revenue already closed-won in the period (default: 0)",
    )
    parser.add_argument("--period-end", help="last day of the period, YYYY-MM-DD")
    parser.add_argument(
        "--as-of", help="date of the review, YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        help="days without activity before a deal is stale (default: the "
        "model's stale_after_days, else %d)" % DEFAULT_STALE_DAYS,
    )
    parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="deals in the concentration view (default: 3)",
    )
    parser.add_argument(
        "--name-field",
        default="opportunity",
        help="column holding the deal name (default: opportunity)",
    )
    parser.add_argument("--currency", help="override the stage model's currency")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out", help="write to this file instead of stdout")
    args = parser.parse_args(argv)

    try:
        if args.stages:
            with open(args.stages, "r", encoding="utf-8") as handle:
                model = load_stage_model(json.load(handle))
        else:
            model = default_stage_model()
        if args.currency:
            model.currency = args.currency.strip().upper()
        records = load_records(args.records)
        result = analyze(
            records,
            model,
            as_of=_require_date(args.as_of, "--as-of") if args.as_of else None,
            target=args.target,
            closed=args.closed,
            period_end=(
                _require_date(args.period_end, "--period-end")
                if args.period_end
                else None
            ),
            top=args.top,
            stale_days=args.stale_days,
            name_field=args.name_field,
        )
    except FileNotFoundError as exc:
        sys.stderr.write("file not found: %s\n" % exc.filename)
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write("invalid JSON: %s\n" % exc)
        return 2
    except (PipelineError, RubricError) as exc:
        sys.stderr.write("pipeline error: %s\n" % exc)
        return 2

    output = (
        json.dumps(result, indent=2) if args.format == "json" else to_markdown(result)
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
