"""MEDDPICC qualification that keeps what is confirmed apart from what is believed.

Qualification frameworks fail in a specific, predictable way: they become a
field-filling exercise. Every box gets a value, the deal reads fully qualified,
and it slips three quarters running — because the boxes held what the rep
*believed*, and nothing in the process told that apart from what anyone had
*confirmed*. So every element in a deal spec carries two separate things: a
**level** from the rubric (how good the answer is) and a **status** (how we
know it)::

    python3 -m gtmkit.qualify deal.json

``confirmed``
    Checked against something a reviewer could open: the dated call, the
    email, the document. Requires a ``source``, held to the assumption
    ledger's rules plus this domain's own dialect of unfalsifiable —
    "multiple conversations" is rejected here the way "industry standard" is
    rejected everywhere else.
``stated``
    A named person in the account said so, and nothing corroborates it yet.
    Requires ``by``.
``assumed``
    The rep believes it. Scored, and labelled as what it is.
``unknown``
    Nobody has asked. Carries no level, and lowers coverage rather than the
    score, for the reason the ICP scorer gives: unknown is not the same as bad.

The score comes from :mod:`gtmkit.scoring` with the same rubric, so the two
tools can never disagree about a tier. What this module adds is the evidence
mix, a floor case, stage-aware failure patterns, and the one element whose
answer is most likely to move the forecast.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .evidence import MIN_SOURCE_CHARS, weasel_phrases
from .fmt import fmt_currency, fmt_pct, table
from .scoring import Rubric, RubricError, score_record

__all__ = [
    "DEFAULT_RUBRIC",
    "STATUSES",
    "QualificationRubric",
    "QualifyError",
    "load_rubric",
    "main",
    "qualify",
    "to_markdown",
]

#: How we know, strongest first. A reviewer scans for the weakest link, and the
#: next-action ranking goes looking for it.
STATUSES = ("confirmed", "stated", "assumed", "unknown")
_STATUS_RANK = {"unknown": 0, "assumed": 1, "stated": 2, "confirmed": 3}

#: The shipped rubric, located relative to the package so the same path works
#: from a clone and from an installed plugin, where gtmkit/ and skills/ ship
#: side by side.
DEFAULT_RUBRIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deal-qualification",
    "assets",
    "meddpicc-rubric.json",
)

_ELEMENT_KEYS = ("level", "status", "source", "by", "basis", "notes")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class QualifyError(ValueError):
    """Raised for deal specs or rubrics that cannot support an honest call."""


# -- what counts as confirmation ---------------------------------------------

#: Confirmation-shaped phrases that point at nothing. Checked on top of the
#: assumption ledger's own list, because deal notes have their own dialect of
#: unfalsifiable: "multiple conversations" is this domain's "research shows".
_VAGUE_CONFIRMATIONS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^(multiple|several|various|many|ongoing|prior|previous|recent|past)\s+"
        r"(calls?|conversations?|discussions?|meetings?|e-?mails?|touch\s*points?)"
        r"(\s+(with|from)\s+(the\s+)?[a-z ]+)?\.?$",
        r"^(calls?|conversations?|discussions?|meetings?|e-?mails?)"
        r"(\s+with\s+(the\s+)?(customer|client|prospect|buyer|account|team|them))?"
        r"\.?$",
        r"^(the\s+)?(customer|client|prospect|buyer|account|they|he|she)\s+"
        r"(said|says|told\s+us|confirmed|agreed|mentioned)"
        r"(\s+(so|it|this|that|yes))?\.?$",
        r"^(per\s+)?(the\s+)?(rep|ae|seller|account\s+executive)('?s)?\s+"
        r"(notes?|read|judge?ment|belief|opinion|sense)\.?$",
        r"^(crm|salesforce|hubspot)(\s+(notes?|record|field|entry))?\.?$",
        r"^(gut(\s+feel)?|intuition|common\s+sense|obvious(ly)?)\.?$",
        r"^(confirmed|verified|known|yes|true|agreed|verbal(ly)?"
        r"(\s+confirmation)?)\.?$",
    )
)

#: A date in any of the forms people actually write in deal notes.
_DATE_MENTION_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}"
    r"|\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*)\b",
    re.IGNORECASE,
)

#: Things a reviewer can open without asking the rep what they meant.
_ARTIFACT_RE = re.compile(
    r"\b(e-?mails?|recordings?|recorded|transcripts?|documents?|docs?|pdf|decks?"
    r"|slides?|memos?|spreadsheets?|contracts?|msa|sow|dpa|order\s+form|rfp|rfi"
    r"|questionnaires?|polic(y|ies)|org\s+chart|scorecards?|minutes|letters?"
    r"|purchase\s+order|mutual\s+(action|close)\s+plan|business\s+case"
    r"|requirements|signed|invites?|slack|teams\s+message)\b",
    re.IGNORECASE,
)

#: Words that name a role in the conversation rather than a person in it.
_ANONYMOUS = frozenset(
    (
        "customer",
        "the customer",
        "client",
        "the client",
        "prospect",
        "the prospect",
        "buyer",
        "the buyer",
        "account",
        "the account",
        "they",
        "them",
        "someone",
        "somebody",
        "everyone",
        "contact",
        "the contact",
        "team",
        "the team",
        "their team",
        "stakeholder",
        "stakeholders",
        "champion",
        "the champion",
        "rep",
        "the rep",
        "me",
        "i",
        "we",
        "us",
        "sales",
        "unknown",
        "n/a",
        "tbd",
    )
)


def _confirmation_problem(source: str) -> Optional[str]:
    """Say why a 'confirmed' source fails, or return None when it holds."""
    text = source.strip()
    if not text:
        return (
            "needs a 'source': the dated call, the email, or the document a "
            "reviewer could open"
        )
    if len(text) < MIN_SOURCE_CHARS:
        return "has a source too short to point at anything: %r" % text
    if weasel_phrases(text) or any(p.search(text) for p in _VAGUE_CONFIRMATIONS):
        return (
            "has a source that reads as an unfalsifiable claim: %r. Name the "
            "specific call (with its date), email, or document" % text
        )
    if not (_DATE_MENTION_RE.search(text) or _ARTIFACT_RE.search(text)):
        return (
            "has a source with no date and no document in it: %r. A "
            "conversation is checkable once you say which one — add the date "
            "of the call, or name the email or document" % text
        )
    return None


def _attribution_problem(by: str) -> Optional[str]:
    text = by.strip().rstrip(".").lower()
    if not text:
        return "needs 'by': the name and role of the person who said it"
    if text in _ANONYMOUS or len(text) < 2 or weasel_phrases(by):
        return (
            "is attributed to %r, which is not a person. Name who said it, "
            "e.g. 'Dana Ruiz, VP Support'" % by.strip()
        )
    return None


# -- the rubric --------------------------------------------------------------


def _norm(value: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower())


class QualificationRubric:
    """A scoring rubric plus the stage model qualification needs on top.

    Criteria, tiers, disqualifiers, and coverage are validated by
    :class:`gtmkit.scoring.Rubric`, so a rubric that scores under one tool
    scores identically under the other. This adds the ordered ``stages``, a
    ``confirm_by`` stage and an ``action`` per element, and ``paper_lead_days``.
    """

    def __init__(self, raw: Mapping[str, Any]) -> None:
        if not isinstance(raw, Mapping):
            raise QualifyError("rubric must be a JSON object")
        try:
            self.scoring = Rubric(raw)
        except RubricError as exc:
            raise QualifyError("rubric: %s" % exc) from exc
        self.name = self.scoring.name

        raw_stages = raw.get("stages")
        if not isinstance(raw_stages, list) or not raw_stages:
            raise QualifyError(
                "rubric needs a 'stages' array, earliest first. Without stages "
                "there is no telling a normal gap in discovery from the same "
                "gap at negotiation, and that difference is the whole point."
            )
        self.stages: List[Tuple[str, str]] = []
        self.stage_index: Dict[str, int] = {}
        for item in raw_stages:
            if not isinstance(item, Mapping) or not str(item.get("id") or "").strip():
                raise QualifyError("each stage needs an 'id', got %r" % (item,))
            stage_id = _norm(item["id"])
            if stage_id in self.stage_index:
                raise QualifyError("duplicate stage id %r" % stage_id)
            self.stage_index[stage_id] = len(self.stages)
            self.stages.append((stage_id, str(item.get("label") or stage_id)))

        raw_criteria = {
            str(item.get("id") or "").strip(): item
            for item in raw["criteria"]
            if isinstance(item, Mapping)
        }
        self.elements: Dict[str, Dict[str, Any]] = {}
        for criterion in self.scoring.criteria:
            if criterion.type != "categorical":
                raise QualifyError(
                    "criterion %r is %s; qualification needs categorical "
                    "levels, because a status ('confirmed', 'assumed') "
                    "describes a stated answer, not a measurement"
                    % (criterion.id, criterion.type)
                )
            extra = raw_criteria.get(criterion.id, {})
            confirm_by = extra.get("confirm_by")
            if confirm_by is not None:
                confirm_by = _norm(confirm_by)
                if confirm_by not in self.stage_index:
                    raise QualifyError(
                        "criterion %r has confirm_by %r, which is not one of "
                        "the stages: %s"
                        % (criterion.id, confirm_by, ", ".join(self.stage_index))
                    )
            # Best first. Ties keep rubric order, which keeps output stable.
            levels = sorted(criterion.map.items(), key=lambda kv: kv[1], reverse=True)
            self.elements[criterion.id] = {
                "criterion": criterion,
                "confirm_by": confirm_by,
                "action": str(extra.get("action") or "").strip() or None,
                "best": levels[0][0],
                "worst": levels[-1][0],
            }

        lead = raw.get("paper_lead_days")
        if lead is not None and (
            isinstance(lead, bool) or not isinstance(lead, int) or lead <= 0
        ):
            raise QualifyError("'paper_lead_days' must be a positive whole number")
        self.paper_lead_days: Optional[int] = lead

    def stage_label(self, stage_id: Optional[str]) -> str:
        if stage_id is None:
            return "n/a"
        return self.stages[self.stage_index[stage_id]][1]


def load_rubric(path: Optional[str] = None) -> QualificationRubric:
    """Load a qualification rubric, defaulting to the shipped MEDDPICC one."""
    target = path or DEFAULT_RUBRIC
    try:
        with open(target, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        if path is None:
            raise QualifyError(
                "the shipped MEDDPICC rubric was not found at %s. Pass --rubric "
                "with the path to skills/deal-qualification/assets/"
                "meddpicc-rubric.json" % target
            )
        raise QualifyError("no such rubric file: %s" % target)
    except json.JSONDecodeError as exc:
        raise QualifyError("%s is not valid JSON: %s" % (target, exc)) from exc
    return QualificationRubric(raw)


# -- the deal spec -----------------------------------------------------------


def _parse_date(value: Any, field: str) -> datetime.date:
    text = "" if value is None else str(value).strip()
    # fromisoformat accepts more shapes on newer Pythons than on 3.9; pinning
    # the format keeps a spec valid or invalid on every supported version.
    if not _ISO_DATE_RE.match(text):
        raise QualifyError(
            "'%s' must be a date written YYYY-MM-DD, got %r" % (field, value)
        )
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise QualifyError("'%s' is not a real date: %r" % (field, value))


def _parse_element(
    element_id: str, raw: Any, info: Mapping[str, Any]
) -> Dict[str, Any]:
    criterion = info["criterion"]
    entry: Dict[str, Any] = {
        "id": element_id,
        "label": criterion.label,
        "weight": criterion.weight,
        "status": "unknown",
        "level": None,
        "points": None,
        "source": None,
        "by": None,
        "basis": None,
        "notes": None,
        "recorded": raw is not None,
    }
    if raw is None:
        return entry
    if not isinstance(raw, Mapping):
        raise QualifyError(
            "element %r must be an object with at least a 'status'" % element_id
        )
    extra = sorted(set(raw) - set(_ELEMENT_KEYS))
    if extra:
        raise QualifyError(
            "element %r has unrecognized key(s): %s. Allowed: %s. A misspelled "
            "'source' would otherwise vanish without a trace."
            % (element_id, ", ".join(extra), ", ".join(_ELEMENT_KEYS))
        )

    status = str(raw.get("status") or "").strip().lower()
    if status not in STATUSES:
        raise QualifyError(
            "element %r needs a 'status' of %s (got %r). The status is how you "
            "know — the half of qualification a CRM field never records."
            % (element_id, ", ".join(STATUSES), raw.get("status"))
        )
    entry["status"] = status
    for key in ("source", "by", "basis", "notes"):
        if raw.get(key) is not None:
            entry[key] = str(raw[key]).strip()

    level = raw.get("level")
    if status == "unknown":
        if level not in (None, ""):
            raise QualifyError(
                "element %r is marked unknown but has level %r. If you believe "
                "a level, the status is 'assumed'; unknown means nobody has "
                "asked." % (element_id, level)
            )
        return entry

    key = str(level or "").strip().lower()
    if key not in criterion.map:
        key = _norm(key)
    if key not in criterion.map:
        raise QualifyError(
            "element %r has level %r; the rubric's levels are: %s"
            % (element_id, level, ", ".join(criterion.map))
        )
    entry["level"] = key
    entry["points"] = criterion.map[key]

    if status == "confirmed":
        problem = _confirmation_problem(entry["source"] or "")
        if problem:
            raise QualifyError(
                "element %r is marked confirmed but %s. If all you have is "
                "someone's word, mark it 'stated' and say who; if it is the "
                "rep's read, mark it 'assumed'." % (element_id, problem)
            )
    elif status == "stated":
        problem = _attribution_problem(entry["by"] or "")
        if problem:
            raise QualifyError(
                "element %r is marked stated but %s. If nobody in particular "
                "said it, it is assumed." % (element_id, problem)
            )
    return entry


# -- failure patterns ---------------------------------------------------------

#: The classic ways a forecast deal turns out not to be one. Each fires only
#: once the deal has reached the stage by which its element should have been
#: confirmed (the rubric's ``confirm_by``): an unknown paper process is normal
#: in discovery and a quarter-end slip forming at proposal.
_PATTERNS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "no_economic_buyer_access",
        "element": "economic_buyer",
        "title": "No access to the economic buyer",
        "bad_levels": ("unidentified", "identified_not_met"),
        "bad_statuses": ("unknown",),
        "why": (
            "Identification without access is the most over-credited state in "
            "pipeline review. Until someone has met the person who signs, the "
            "forecast rests on a guess about what that person wants."
        ),
        "wrong_if": (
            "the person you have met can sign at this amount without asking "
            "anyone. Check their signing limit against the deal size; if it "
            "holds, they are the economic buyer — record the meeting."
        ),
    },
    {
        "id": "champion_untested",
        "element": "champion",
        "title": "Champion unconfirmed or untested",
        "bad_levels": ("none", "coach_only", "willing_untested"),
        "bad_statuses": ("unknown", "assumed", "stated"),
        "why": (
            "A champion is proven by something costly they did for you. A "
            "friendly contact who has not been tested tends to fold at the "
            "approval gate, which is the worst place to find out."
        ),
        "wrong_if": (
            "they have already done something costly — shared internal numbers, "
            "set up a meeting upward, put their name on a recommendation. "
            "Record which, with the date, and mark it confirmed."
        ),
    },
    {
        "id": "decision_process_assumed",
        "element": "decision_process",
        "title": "Decision process assumed, not mapped with the buyer",
        "bad_levels": (),
        "bad_statuses": ("unknown", "assumed"),
        "why": (
            "Deals rarely die at the decision. They die in an approval step "
            "nobody mapped, and a process inferred from the last deal at this "
            "company misses whatever has changed since."
        ),
        "wrong_if": (
            "the buyer has walked you through the approval steps. Then it is "
            "stated or confirmed — record who said it, or where it is written."
        ),
    },
    {
        "id": "paper_process_late",
        "element": "paper_process",
        "title": "Paper process unknown this late",
        "bad_levels": ("not_started",),
        "bad_statuses": ("unknown", "assumed"),
        "clock": True,
        "why": (
            "Security review, legal, and vendor onboarding run on the buyer's "
            "calendar, not the seller's. Found late, they move the close date "
            "by weeks, and nothing else in the deal can buy that time back."
        ),
        "wrong_if": (
            "you are already on their vendor list with a current security "
            "review, or the purchase falls under a pre-approved path. Confirm "
            "it and record where."
        ),
    },
    {
        "id": "no_quantified_metric",
        "element": "metrics",
        "title": "No quantified metric the customer owns",
        "bad_levels": ("none", "seller_proposed"),
        "bad_statuses": ("unknown",),
        "why": (
            "A metric the seller proposed does not survive the buyer's internal "
            "review, and without a metric the buyer owns there is no business "
            "case for anyone to approve."
        ),
        "wrong_if": (
            "the buyer has restated the number in their own words or documents. "
            "Then the level is customer_stated or jointly_built — record where."
        ),
    },
    {
        "id": "competition_unknown",
        "element": "competition",
        "title": "Competition unknown",
        "bad_levels": ("not_established",),
        "bad_statuses": ("unknown",),
        "why": (
            "Without the alternative you do not know what you are being "
            "compared against, and the usual leader is doing nothing, which no "
            "battlecard covers."
        ),
        "wrong_if": (
            "the buyer has told you what else they are weighing, including "
            "doing nothing. Record it as known_from_buyer."
        ),
    },
)


def _check_patterns(
    rubric: QualificationRubric,
    elements: Mapping[str, Mapping[str, Any]],
    stage_index: int,
    days_to_close: Optional[int],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    fired: List[Dict[str, Any]] = []
    not_checked: List[str] = []
    stage_label = rubric.stages[stage_index][1]
    for pattern in _PATTERNS:
        info = rubric.elements.get(pattern["element"])
        if info is None:
            not_checked.append(
                "%s — the rubric has no %r element"
                % (pattern["title"], pattern["element"])
            )
            continue
        uses_clock = bool(pattern.get("clock")) and rubric.paper_lead_days is not None
        if info["confirm_by"] is None and not uses_clock:
            not_checked.append(
                "%s — the rubric gives %r no confirm_by stage"
                % (pattern["title"], pattern["element"])
            )
            continue

        element = elements[pattern["element"]]
        if not (
            element["status"] in pattern["bad_statuses"]
            or element["level"] in pattern["bad_levels"]
        ):
            continue

        notes = []
        due = info["confirm_by"]
        by_stage = due is not None and stage_index >= rubric.stage_index[due]
        if by_stage:
            notes.append(
                "Expected by %s; the deal is at %s."
                % (rubric.stage_label(due), stage_label)
            )
        by_clock = (
            uses_clock
            and days_to_close is not None
            and days_to_close <= rubric.paper_lead_days
        )
        if by_clock:
            notes.append(
                "The close date is %s, inside the %d-day paper lead time."
                % (_days_phrase(days_to_close), rubric.paper_lead_days)
            )
        if not (by_stage or by_clock):
            continue
        fired.append(
            {
                "id": pattern["id"],
                "element": pattern["element"],
                "title": pattern["title"],
                "when": " ".join(notes),
                "by_clock": by_clock,
                "why": pattern["why"],
                "wrong_if": pattern["wrong_if"],
            }
        )
    return fired, not_checked


def _days_phrase(days: int) -> str:
    if days > 0:
        return "%d day%s out" % (days, "" if days == 1 else "s")
    if days == 0:
        return "today"
    return "%d day%s past" % (-days, "" if days == -1 else "s")


# -- the call ----------------------------------------------------------------


def qualify(
    spec: Mapping[str, Any],
    rubric: Optional[QualificationRubric] = None,
    as_of: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Score one deal and say how much of the score anyone has confirmed.

    ``as_of`` overrides the spec's own ``as_of``; with neither, today is used
    and reported, so a rerun with the same date reproduces the output.
    """
    rubric = rubric or load_rubric()
    if not isinstance(spec, Mapping):
        raise QualifyError("deal spec must be a JSON object")

    name = str(spec.get("name") or "").strip()
    if not name:
        raise QualifyError("deal spec needs a 'name'")

    stage = _norm(spec.get("stage") or "")
    if stage not in rubric.stage_index:
        raise QualifyError(
            "deal 'stage' is %r; use one of the rubric's stages: %s. Map your "
            "CRM stage by what has to be true to enter it, not by its name."
            % (spec.get("stage"), ", ".join(rubric.stage_index))
        )
    stage_index = rubric.stage_index[stage]

    amount = spec.get("amount")
    if amount is not None and (
        isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0
    ):
        raise QualifyError("'amount' must be a positive number, got %r" % (amount,))
    currency = str(spec.get("currency") or "USD").strip().upper()

    if as_of is None:
        as_of = (
            _parse_date(spec["as_of"], "as_of")
            if spec.get("as_of") is not None
            else datetime.date.today()
        )
    close_date = (
        _parse_date(spec["close_date"], "close_date")
        if spec.get("close_date") is not None
        else None
    )
    days_to_close = (close_date - as_of).days if close_date else None

    raw_elements = spec.get("elements")
    if raw_elements is None:
        raw_elements = {}
    if not isinstance(raw_elements, Mapping):
        raise QualifyError("'elements' must be an object keyed by element id")
    unknown_ids = sorted(set(raw_elements) - set(rubric.elements))
    if unknown_ids:
        raise QualifyError(
            "'elements' has id(s) the rubric does not define: %s. The rubric's "
            "elements are: %s" % (", ".join(unknown_ids), ", ".join(rubric.elements))
        )

    elements = [
        _parse_element(element_id, raw_elements.get(element_id), info)
        for element_id, info in rubric.elements.items()
    ]
    by_id = {e["id"]: e for e in elements}

    # The believed view: every element with a level counts, whatever its
    # status. Unknown elements are left out of the record so the scoring
    # engine treats them as missing — lower coverage, not a lower score.
    record = {e["id"]: e["level"] for e in elements if e["status"] != "unknown"}
    believed = score_record(rubric.scoring, record)
    tier = believed["tier"]

    total_weight = rubric.scoring.total_weight
    shares = {
        status: sum(e["weight"] for e in elements if e["status"] == status)
        / total_weight
        for status in STATUSES
    }

    # The floor: everything not confirmed at its worst level at once. A stress
    # test, not a forecast — the same distinction the value-case floor makes.
    # Its tier ignores disqualifiers on purpose: an unconfirmed pain element
    # would otherwise make every such floor read "OUT" and say nothing.
    floor_record = {
        e["id"]: (
            e["level"]
            if e["status"] == "confirmed"
            else rubric.elements[e["id"]]["worst"]
        )
        for e in elements
    }
    floor = score_record(rubric.scoring, floor_record)

    patterns, not_checked = _check_patterns(rubric, by_id, stage_index, days_to_close)

    for element in elements:
        due = rubric.elements[element["id"]]["confirm_by"]
        element["confirm_by"] = due
        element["confirm_by_label"] = rubric.stage_label(due)
        element["stages_late"] = (
            stage_index - rubric.stage_index[due] if due is not None else None
        )

    result: Dict[str, Any] = {
        "name": name,
        "rubric": rubric.name,
        "amount": float(amount) if amount is not None else None,
        "currency": currency,
        "owner": spec.get("owner"),
        "stage": stage,
        "stage_label": rubric.stages[stage_index][1],
        "stage_number": stage_index + 1,
        "stage_count": len(rubric.stages),
        "as_of": as_of.isoformat(),
        "close_date": close_date.isoformat() if close_date else None,
        "days_to_close": days_to_close,
        "score": believed["fit"],
        "coverage": believed["coverage"],
        "min_coverage": rubric.scoring.min_coverage,
        "tier": tier,
        "scale": rubric.scoring.scale,
        "disqualified": believed["disqualified"],
        "disqualifier_reason": believed["disqualifier_reason"],
        "evidence": {
            "share_by_status": shares,
            "elements_by_status": {
                status: [e["label"] for e in elements if e["status"] == status]
                for status in STATUSES
            },
        },
        "floor": {
            "score": floor["fit"],
            "tier": rubric.scoring.tier(floor["fit"]),
            "would_disqualify": floor["disqualified"],
        },
        "elements": elements,
        "patterns": patterns,
        "patterns_not_checked": not_checked,
    }
    result["next_action"] = _next_action(rubric, record, result, by_id)
    result["notes"] = _notes(result)
    return result


def _trial(
    rubric: QualificationRubric, record: Mapping[str, Any], element_id: str, level: str
) -> Dict[str, Any]:
    trial = dict(record)
    trial[element_id] = level
    return score_record(rubric.scoring, trial)


def _action_text(rubric: QualificationRubric, element: Mapping[str, Any]) -> str:
    return rubric.elements[element["id"]]["action"] or (
        "Get %s answered by the buyer, and record how you know." % element["label"]
    )


def _status_reason(element: Mapping[str, Any], best: str) -> str:
    status = element["status"]
    if status == "unknown":
        return "nobody has asked yet"
    if status == "assumed":
        return "today it is the rep's assumption"
    if status == "stated":
        return "today it rests on the word of %s" % element["by"]
    return "it is confirmed, but at %s rather than %s" % (
        _human(element["level"]),
        _human(best),
    )


def _next_action(
    rubric: QualificationRubric,
    record: Mapping[str, Any],
    result: Mapping[str, Any],
    elements: Mapping[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Pick the one element whose answer is most likely to move the call.

    Ranked, in order: whether resolving it either way could change the tier
    at all; whether a failure pattern is firing on it; how many stages late
    it is; how little is known about it (unknown, then assumed, then stated);
    and how far its best and worst outcomes move the score. Weakest status
    ranks ahead of size because the less verified an answer is, the more
    likely the truth differs from what the forecast assumes. That would be
    wrong for a team whose reps' assumptions reliably survive confirmation —
    check how often they did in last quarter's won and lost deals.
    """
    tier = result["tier"]
    order = list(elements)

    if result["disqualified"]:
        rule = next(
            (
                r
                for r in rubric.scoring.disqualifiers
                if str(r["reason"]) == result["disqualifier_reason"]
            ),
            None,
        )
        element = elements.get(rule["field"]) if rule else None
        if element is not None and element["status"] == "confirmed":
            action = (
                "Disqualify it, and tell the buyer why: say this is not the "
                "right time and what would have to change for it to become "
                "one. Quiet neglect produces neither a clean pipeline nor a "
                "re-engagement."
            )
        elif element is not None:
            action = (
                "Confirm %s directly with the buyer. If it holds, disqualify; "
                "if it does not, record what you learned and rescore. %s"
                % (element["label"], _action_text(rubric, element))
            )
        else:  # pragma: no cover - a disqualifier always names a rubric field
            action = "Confirm the disqualifying answer before working the deal."
        return {
            "kind": "disqualify",
            "element": element["id"] if element else None,
            "label": element["label"] if element else None,
            "action": action,
            "reasons": [result["disqualifier_reason"]],
            "changes_forecast": True,
            "then": [],
        }

    if tier == "UNKNOWN":
        known = sum(e["weight"] for e in elements.values() if e["status"] != "unknown")
        needed = rubric.scoring.min_coverage * rubric.scoring.total_weight - known
        missing = sorted(
            (e for e in elements.values() if e["status"] == "unknown"),
            key=lambda e: (
                -e["weight"],
                -(e["stages_late"] if e["stages_late"] is not None else -99),
                order.index(e["id"]),
            ),
        )
        plan: List[Dict[str, Any]] = []
        gathered = 0.0
        for element in missing:
            if gathered >= needed - 1e-9:
                break
            plan.append(element)
            gathered += element["weight"]
        first = plan[0]
        return {
            "kind": "coverage",
            "element": first["id"],
            "label": first["label"],
            "action": _action_text(rubric, first),
            "reasons": [
                "only %s of the rubric has any answer and a deal is not tiered "
                "below %s; answering %s gets it there"
                % (
                    fmt_pct(result["coverage"]),
                    fmt_pct(rubric.scoring.min_coverage),
                    _join([e["label"] for e in plan]),
                ),
                "%s carries the most weight of what is missing" % first["label"],
            ],
            "changes_forecast": len(plan) == 1,
            "then": [e["label"] for e in plan[1:]],
        }

    fired = {p["element"]: p for p in result["patterns"]}
    candidates = []
    for element_id, element in elements.items():
        info = rubric.elements[element_id]
        if element["status"] == "confirmed" and element["level"] == info["best"]:
            continue  # settled: confirmed, and nothing better to find
        low_level = (
            element["level"] if element["status"] == "confirmed" else info["worst"]
        )
        low = _trial(rubric, record, element_id, low_level)
        high = _trial(rubric, record, element_id, info["best"])
        pattern = fired.get(element_id)
        lateness = None
        if element["stages_late"] is not None and (
            element["status"] != "confirmed" or pattern
        ):
            lateness = element["stages_late"]
        if pattern and pattern["by_clock"]:
            lateness = max(lateness if lateness is not None else 0, 0)
        changes = low["tier"] != tier or high["tier"] != tier
        candidates.append(
            {
                "element": element,
                "low": low,
                "high": high,
                "pattern": pattern,
                "lateness": lateness,
                "changes": changes,
                "key": (
                    not changes,
                    pattern is None,
                    -(lateness if lateness is not None else -99),
                    _STATUS_RANK[element["status"]],
                    -(high["fit"] - low["fit"]),
                    order.index(element_id),
                ),
            }
        )

    if not candidates:
        return {
            "kind": "none",
            "element": None,
            "label": None,
            "action": (
                "Every element is confirmed at its strongest level. What is "
                "left is execution: hold each date in the close plan."
            ),
            "reasons": [],
            "changes_forecast": False,
            "then": [],
        }

    candidates.sort(key=lambda c: c["key"])
    top = candidates[0]
    element = top["element"]
    best = rubric.elements[element["id"]]["best"]
    reasons: List[str] = []
    if top["changes"]:
        moves = []
        if top["low"]["tier"] != tier:
            moves.append("at its worst the deal drops to %s" % top["low"]["tier"])
        if top["high"]["tier"] != tier:
            moves.append("at its best it rises to %s" % top["high"]["tier"])
        reasons.append(" and ".join(moves))
    else:
        reasons.append(
            "no single open element can move the call on its own; this one has "
            "the most at stake"
        )
    if top["pattern"]:
        reasons.append("it is behind a failure pattern (%s)" % top["pattern"]["title"])
    if top["lateness"] is not None and top["lateness"] > 0:
        reasons.append(
            "it was due by %s, %d stage%s ago"
            % (
                rubric.stage_label(element["confirm_by"]),
                top["lateness"],
                "" if top["lateness"] == 1 else "s",
            )
        )
    elif top["lateness"] == 0:
        reasons.append("it is due at this stage")
    reasons.append(_status_reason(element, best))

    return {
        "kind": "confirm",
        "element": element["id"],
        "label": element["label"],
        "action": _action_text(rubric, element),
        "reasons": reasons,
        "changes_forecast": top["changes"],
        "score_if_worst": top["low"]["fit"],
        "tier_if_worst": top["low"]["tier"],
        "score_if_best": top["high"]["fit"],
        "tier_if_best": top["high"]["tier"],
        "then": [c["element"]["label"] for c in candidates[1:4]],
    }


def _notes(result: Mapping[str, Any]) -> List[str]:
    notes = []
    days = result["days_to_close"]
    if days is not None and days < 0:
        notes.append(
            "The close date %s is %s. A deal whose date has passed needs a new "
            "one agreed with the buyer before it is forecast in any period."
            % (result["close_date"], _days_phrase(days))
        )
    if result["close_date"] is None:
        notes.append(
            "No close_date, so the paper-process clock was not checked; only "
            "the stage gates were."
        )
    unrecorded = [e["label"] for e in result["elements"] if not e["recorded"]]
    if unrecorded:
        notes.append(
            "Not in the spec, so treated as unknown: %s." % ", ".join(unrecorded)
        )
    for item in result["patterns_not_checked"]:
        notes.append("Pattern not checked: %s." % item)
    return notes


# -- output ------------------------------------------------------------------


def _human(level: Optional[str]) -> str:
    return "—" if level is None else level.replace("_", " ")


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return "%s and %s" % (", ".join(items[:-1]), items[-1])


def _evidence_sentence(shares: Mapping[str, float]) -> str:
    parts = []
    if shares["stated"]:
        parts.append("%s rests on someone's word" % fmt_pct(shares["stated"]))
    if shares["assumed"]:
        parts.append("%s on the rep's assumption" % fmt_pct(shares["assumed"]))
    if shares["unknown"]:
        parts.append("%s has not been asked" % fmt_pct(shares["unknown"]))
    head = "%s of the rubric's weight is confirmed" % fmt_pct(shares["confirmed"])
    return "%s; %s." % (head, _join(parts)) if parts else head + "."


def _evidence_cell(element: Mapping[str, Any]) -> str:
    status = element["status"]
    if status == "confirmed":
        return element["source"] or ""
    if status == "stated":
        return "per %s" % element["by"]
    if status == "assumed":
        return element["basis"] or "rep's belief, no basis given"
    return "not asked" if element["recorded"] else "not recorded"


def _due_cell(element: Mapping[str, Any]) -> str:
    label = element["confirm_by_label"]
    late = element["stages_late"]
    if element["status"] == "confirmed" or late is None or late < 0:
        return label
    return "%s — %s" % (label, "overdue" if late > 0 else "due now")


def to_markdown(result: Mapping[str, Any]) -> str:
    cur = result["currency"]
    shares = result["evidence"]["share_by_status"]
    lines: List[str] = ["# %s" % result["name"], ""]

    facts = []
    if result["amount"] is not None:
        facts.append(fmt_currency(result["amount"], cur))
    facts.append(
        "%s (stage %d of %d)"
        % (result["stage_label"], result["stage_number"], result["stage_count"])
    )
    if result["close_date"]:
        facts.append(
            "close date %s, %s"
            % (result["close_date"], _days_phrase(result["days_to_close"]))
        )
    facts.append("as of %s" % result["as_of"])
    lines.append(" · ".join(facts))
    lines.append("")

    # The verdict leads with the gap between belief and evidence, because that
    # gap is the thing a pipeline review is otherwise built to hide.
    if result["disqualified"]:
        lines.append("## Verdict: OUT")
        lines.append("")
        lines.append("%s." % result["disqualifier_reason"].rstrip("."))
    elif result["tier"] == "UNKNOWN":
        lines.append("## Verdict: UNKNOWN — too little answered to call")
        lines.append("")
        lines.append(
            "Only %s of the rubric has any answer; a deal is tiered from %s. On "
            "what is known it scores %s. This is not a weak deal, it is an "
            "unexamined one. %s"
            % (
                fmt_pct(result["coverage"]),
                fmt_pct(result["min_coverage"]),
                fmt_pct(result["score"]),
                _evidence_sentence(shares),
            )
        )
    else:
        floor = result["floor"]
        lines.append(
            "## Verdict: %s on belief, %s at the floor"
            % (result["tier"], floor["tier"])
        )
        lines.append("")
        lines.append(
            "Scores %s across %s of the rubric — %s on what the team believes. "
            "%s If everything not confirmed came back at its worst, it would "
            "score %s (%s)."
            % (
                fmt_pct(result["score"]),
                fmt_pct(result["coverage"]),
                result["tier"],
                _evidence_sentence(shares),
                fmt_pct(floor["score"]),
                floor["tier"],
            )
        )
    lines.append("")

    action = result["next_action"]
    lines.append(
        "## Next action — %s"
        % (action["label"] if action["label"] else "nothing left to confirm")
    )
    lines.append("")
    lines.append("**%s**" % action["action"])
    if action["reasons"]:
        lines.append("")
        lines.append("Why this one: %s." % "; ".join(action["reasons"]))
    if action["then"]:
        lines.append("")
        lines.append("Then: %s." % ", ".join(action["then"]))
    lines.append("")

    patterns = result["patterns"]
    lines.append("## Failure patterns (%d)" % len(patterns))
    lines.append("")
    if patterns:
        for pattern in patterns:
            lines.append(
                "- **%s.** %s %s _What would make this wrong:_ %s"
                % (
                    pattern["title"],
                    pattern["when"],
                    pattern["why"],
                    pattern["wrong_if"],
                )
            )
    else:
        lines.append(
            "None of the classic patterns fires at %s. Gaps that are not yet "
            "due are listed below with the stage they are due by."
            % result["stage_label"]
        )
    lines.append("")

    lines.append("## Elements")
    lines.append("")
    rows = []
    for element in result["elements"]:
        rows.append(
            [
                element["label"],
                "%g" % element["weight"],
                _human(element["level"]),
                "%g/%g" % (element["points"], result["scale"])
                if element["level"]
                else "—",
                element["status"],
                _due_cell(element),
                _evidence_cell(element),
            ]
        )
    lines.append(
        table(
            [
                "Element",
                "Weight",
                "Level",
                "Points",
                "Status",
                "Confirm by",
                "Evidence",
            ],
            rows,
        )
    )
    lines.append("")

    noted = [e for e in result["elements"] if e["notes"]]
    if noted:
        for element in noted:
            lines.append("- **%s:** %s" % (element["label"], element["notes"]))
        lines.append("")

    lines.append("## Evidence mix")
    lines.append("")
    lines.append(
        "Coverage by how it is known, as a share of rubric weight. This sits "
        "beside the score rather than inside it: an assumed answer still "
        "scores, and this is where it shows."
    )
    lines.append("")
    mix_rows = [
        [
            status,
            fmt_pct(shares[status]),
            ", ".join(result["evidence"]["elements_by_status"][status]),
        ]
        for status in STATUSES
        if shares[status]
    ]
    lines.append(table(["Status", "Share of weight", "Elements"], mix_rows))
    lines.append("")

    if result["notes"]:
        lines.append("## Notes")
        lines.append("")
        for note in result["notes"]:
            lines.append("- %s" % note)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by [gtm-skills](https://github.com/erickdronski/gtm-skills) "
        "against the %s rubric._" % result["rubric"]
    )
    return "\n".join(lines)


# -- CLI -----------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m gtmkit.qualify",
        description=(
            "Score one deal against MEDDPICC, keeping what is confirmed apart "
            "from what is only believed, and name the next thing to confirm."
        ),
    )
    parser.add_argument("deal", help="path to the deal spec JSON")
    parser.add_argument(
        "--rubric", help="qualification rubric JSON (default: the shipped MEDDPICC one)"
    )
    parser.add_argument(
        "--as-of", help="date the call is made, YYYY-MM-DD (default: spec, then today)"
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out", help="write to this file instead of stdout")
    args = parser.parse_args(argv)

    try:
        rubric = load_rubric(args.rubric)
        with open(args.deal, "r", encoding="utf-8") as handle:
            spec = json.load(handle)
        as_of = _parse_date(args.as_of, "--as-of") if args.as_of else None
        result = qualify(spec, rubric, as_of)
    except FileNotFoundError:
        sys.stderr.write("no such deal spec: %s\n" % args.deal)
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write("%s is not valid JSON: %s\n" % (args.deal, exc))
        return 2
    except QualifyError as exc:
        sys.stderr.write("qualify error: %s\n" % exc)
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
