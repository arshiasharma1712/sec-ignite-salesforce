"""Lead scoring engine (rule-based, in-memory, no file I/O).

Public API
----------
score_lead(lead)            -> dict        score ONE lead
score_leads(leads)          -> list[dict]  score many leads (never crashes)
sort_for_routing(scored)    -> list[dict]  deterministic routing order

Input
-----
A lead is a dict (any Mapping, or an object with .to_dict()). Fields used for
scoring: VIP_Referral, Company_Size, Recent_Activity, Industry_Vertical. Values
may be raw/messy or already normalized, because this module re-parses
defensively and does not depend on Arush's cleaning module. Anything that is
not a record (None, a string, a number...) is handled safely, see below.

score_lead(lead) return format (always the same 9 keys)
-------------------------------------------------------
score               int   0-100 (VIP = 100)
priority            str   "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
is_vip              bool
size_points         int   points from company size   (0 for VIP: matrix bypassed)
activity_points     int   points from recent activity (0 for VIP)
industry_points     int   points from industry        (0 for VIP)
company_size_parsed int | None   employee count actually used (None = fallback)
fallbacks           list[str]    every fallback/assumption applied, for the
                                 dashboard's "why this score" column
invalid_record      bool  True only when the input was not a record at all

score_leads(leads) return format
--------------------------------
A list with the SAME length and order as the input (nothing is ever dropped).
Each item is a NEW dict = all original fields of the lead (Lead_ID, Region,
Language, Company_Name, ... untouched, so routing can use them) + the 9 keys
above. If an original field has the same name as one of the 9 keys, the
scoring value wins. Lead_ID, Region and Language are guaranteed to exist
(None if the lead did not have them) so routing never hits a KeyError. The
input records are never mutated. A non-record input yields a LOW / score 0 row
with invalid_record=True, the fallback "invalid_record:<TypeName>", and
`invalid_record_repr` (short text of the bad input) so it stays visible.
"""
from __future__ import annotations

import math
import numbers
import re
from typing import Any, Iterable, Mapping, Optional

# --------------------------------------------------------------------------
# Config: every business rule lives here so it is easy to defend / tweak.
# Baseline values come from the Scoring Logic Cheat Sheet.
# --------------------------------------------------------------------------
VIP_SCORE = 100

SIZE_TIERS = [            # (min_employees_inclusive, points)
    (1000, 50),           # Enterprise
    (100, 30),            # Mid-Market
    (1, 0),               # SMB
]
SIZE_MISSING_POINTS = 20  # fallback when blank / unparseable / invalid (<= 0)

ACTIVITY_POINTS = {       # keys are normalized: lowercase, single-spaced
    "requested live demo": 35,
    "contact sales": 35,
    "attended webinar": 25,
    "downloaded whitepaper": 15,
    "visited pricing page": 5,
}
ACTIVITY_DEFAULT = 0      # unmapped / missing ("Started Free Trial", "Unknown", NaN...)

INDUSTRY_POINTS = {
    "technology": 15,
    "healthcare": 10,
    "finance": 10,
    "manufacturing": 0,
    "retail": 0,
}
INDUSTRY_DEFAULT = 0

CRITICAL, HIGH, MEDIUM, LOW = "CRITICAL", "HIGH", "MEDIUM", "LOW"

TIERS = [                 # (min_score_inclusive, label), checked top-down
    (85, CRITICAL),
    (60, HIGH),
    (40, MEDIUM),
    (0, LOW),
]
TIER_RANK = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
UNRANKED = len(TIER_RANK)  # sort position for records with no usable priority/score

# --- Company-size range policy (e.g. "500-1000") ---------------------------
# The challenge does not say how to score a range, so the choice is explicit:
#   "lower"    (default) use the low end: only credit the size we are SURE the
#              company has; never hands out Enterprise points on a maybe.
#   "midpoint" use the average of the two ends.
#   "upper"    use the high end (most generous).
# Whatever is used is recorded in `fallbacks` as company_size_range_<policy>_used.
RANGE_POLICY = "lower"

# Counts above this are treated as invalid (data-entry error), not as a size.
# The data's largest value is exactly 10**10 and stays valid (Enterprise).
MAX_COMPANY_SIZE = 10**10
_MAX_SIZE_TEXT_LEN = 64    # longer text cannot be a sane employee count

_TRUE = {"true", "t", "yes", "y", "1", "1.0"}


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def _clean(v: Any) -> str:
    """lowercase, trim, collapse internal whitespace. Never raises: an object
    whose str() fails is treated as empty text."""
    try:
        return re.sub(r"\s+", " ", str(v)).strip().lower()
    except Exception:
        return ""


def _is_missing(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return _clean(v) in {"", "nan", "none", "null", "n/a", "na", "unknown", "<na>"}


def parse_vip(v: Any) -> bool:
    """True only for an explicit truthy value. 'Unknown'/blank/garbage -> False.
    (Conservative: we don't escalate to Critical on a guess.)"""
    if isinstance(v, bool):
        return v
    if _is_missing(v):
        return False
    return _clean(v) in _TRUE


_NUM = r"\d+(?:\.\d+)?"


def _to_number(token: str) -> Optional[float]:
    """'5k' -> 5000, '1,000' -> 1000, '2.5m' -> 2_500_000, '250.0' -> 250."""
    t = token.strip().lower().replace(",", "").replace("_", "")
    m = re.fullmatch(rf"({_NUM})\s*([km]?)\+?", t)
    if not m:
        return None
    n = float(m.group(1))
    n *= {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2)]
    return n


def _policy() -> str:
    """RANGE_POLICY, with any unrecognised value falling back to the safest."""
    return RANGE_POLICY if RANGE_POLICY in ("midpoint", "upper") else "lower"


def _pick_from_range(lo: float, hi: float) -> float:
    """Apply the range policy to the two ends of a size range."""
    lo, hi = min(lo, hi), max(lo, hi)          # tolerate "1000-500"
    policy = _policy()
    if policy == "midpoint":
        return (lo + hi) / 2
    if policy == "upper":
        return hi
    return lo


def parse_company_size_detail(v: Any) -> tuple[Optional[int], Optional[str]]:
    """Return (employee_count_or_None, note).

    note is None for a plain number, or "range_<policy>_used" when a range such
    as "500-1000" was converted using RANGE_POLICY. A None count means
    missing/invalid, which triggers the +20 fallback (never silently SMB).

    Handles ints/floats, "1,000", "5k", "10,000+", ranges ("500-1000").
    Invalid -> None: zero, negatives, NaN/inf, text, values above
    MAX_COMPANY_SIZE, over-long text, and anything that raises during
    conversion (OverflowError etc.). It never raises.
    """
    try:
        if _is_missing(v) or isinstance(v, bool):
            return None, None
        note = None
        if isinstance(v, numbers.Integral):      # exact int compare: no float overflow
            n: Optional[float] = int(v)
        elif isinstance(v, numbers.Real):
            n = float(v) if math.isfinite(v) else None
        else:
            s = _clean(v)
            if len(s) > _MAX_SIZE_TEXT_LEN:
                return None, None
            rng = re.fullmatch(r"([\d.,]+k?)\s*(?:-|–|to)\s*([\d.,]+k?)", s)
            if rng:
                lo, hi = _to_number(rng.group(1)), _to_number(rng.group(2))
                if lo is None or hi is None:
                    return None, None
                n = _pick_from_range(lo, hi)
                note = f"range_{_policy()}_used"
            else:
                n = _to_number(s)
        if n is None or n != n or n < 1 or n > MAX_COMPANY_SIZE:   # n != n is the NaN test
            return None, None
        return int(n), note
    except (OverflowError, ValueError, TypeError, ArithmeticError):
        return None, None


def parse_company_size(v: Any) -> Optional[int]:
    """Public wrapper: employee count (int) or None if missing/invalid."""
    return parse_company_size_detail(v)[0]


# --------------------------------------------------------------------------
# Component scorers
# --------------------------------------------------------------------------
def size_points(size: Optional[int]) -> int:
    if size is None:
        return SIZE_MISSING_POINTS
    for floor, pts in SIZE_TIERS:
        if size >= floor:
            return pts
    return SIZE_MISSING_POINTS


def activity_points(v: Any) -> int:
    if _is_missing(v):
        return ACTIVITY_DEFAULT
    return ACTIVITY_POINTS.get(_clean(v), ACTIVITY_DEFAULT)


def industry_points(v: Any) -> int:
    if _is_missing(v):
        return INDUSTRY_DEFAULT
    return INDUSTRY_POINTS.get(_clean(v), INDUSTRY_DEFAULT)


def tier_for(score: float) -> str:
    for floor, label in TIERS:
        if score >= floor:
            return label
    return LOW  # negative scores are impossible, but never fail


# --------------------------------------------------------------------------
# Record handling (non-dict inputs)
# --------------------------------------------------------------------------
PASSTHROUGH_KEYS = ("Lead_ID", "Region", "Language")  # routing needs these


def _as_record(lead: Any) -> Optional[Mapping]:
    """Return the lead as a Mapping, or None if it is not a record at all
    (None, str, int, list...). Objects with .to_dict() (e.g. a pandas row) are
    converted; no pandas import is needed."""
    if isinstance(lead, Mapping):
        return lead
    to_dict = getattr(lead, "to_dict", None)
    if callable(to_dict) and not isinstance(lead, (str, bytes)):
        try:
            d = to_dict()
            if isinstance(d, Mapping):
                return d
        except Exception:
            pass
    return None


def _result(score: int, priority: str, *, is_vip: bool = False, sp: int = 0,
            ap: int = 0, ip: int = 0, size: Optional[int] = None,
            fallbacks: Optional[list] = None, invalid: bool = False) -> dict:
    """The ONE place the 9-key result dict is built, so its shape never drifts."""
    return {
        "score": score, "priority": priority, "is_vip": is_vip,
        "size_points": sp, "activity_points": ap, "industry_points": ip,
        "company_size_parsed": size, "fallbacks": fallbacks or [],
        "invalid_record": invalid,
    }


def _short_repr(x: Any) -> str:
    try:
        return repr(x)[:200]
    except Exception:
        return "<unrepresentable>"


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def score_lead(lead: Any) -> dict:
    """Score one lead; returns the 9-key dict described in the module docstring.
    Never raises: a non-record input returns LOW / 0 with invalid_record=True."""
    rec = _as_record(lead)
    if rec is None:
        return _result(0, LOW, invalid=True,
                       fallbacks=[f"invalid_record:{type(lead).__name__}"])
    get = rec.get
    fallbacks: list[str] = []

    raw_vip = get("VIP_Referral")
    is_vip = parse_vip(raw_vip)
    if not is_vip and _is_missing(raw_vip) and not isinstance(raw_vip, bool):
        fallbacks.append("vip_unknown_treated_as_false")

    size_raw = get("Company_Size")
    size, size_note = parse_company_size_detail(size_raw)

    if is_vip:   # VIP override: bypass the matrix entirely
        return _result(VIP_SCORE, CRITICAL, is_vip=True, size=size,
                       fallbacks=fallbacks)

    if size is None:
        fallbacks.append(
            "company_size_missing_default_20" if _is_missing(size_raw)
            else "company_size_invalid_default_20")
    elif size_note:                      # a range was converted: say how
        fallbacks.append(f"company_size_{size_note}")
    sp = size_points(size)

    act_raw = get("Recent_Activity")
    ap = activity_points(act_raw)
    if _is_missing(act_raw):
        fallbacks.append("activity_missing_0")
    elif _clean(act_raw) not in ACTIVITY_POINTS:
        fallbacks.append("activity_unmapped_0")

    ind_raw = get("Industry_Vertical")
    ip = industry_points(ind_raw)
    if _is_missing(ind_raw):
        fallbacks.append("industry_missing_0")
    elif _clean(ind_raw) not in INDUSTRY_POINTS:   # e.g. "Biotech"
        fallbacks.append("industry_unmapped_0")

    total = sp + ap + ip
    return _result(total, tier_for(total), sp=sp, ap=ap, ip=ip, size=size,
                   fallbacks=fallbacks)


def score_leads(leads: Iterable[Any]) -> list[dict]:
    """Score many leads. Output has the same length/order as the input; each
    item is a new dict = original fields + the 9 scoring keys (see module
    docstring). One bad record can never abort the batch or be dropped."""
    if leads is None:
        return []
    if hasattr(leads, "to_dict") and hasattr(leads, "columns"):  # DataFrame
        leads = leads.to_dict("records")
    out: list[dict] = []
    for lead in leads:
        rec = _as_record(lead)
        try:
            res = score_lead(lead)
        except Exception as exc:  # last-resort safety net
            res = _result(0, LOW, fallbacks=[f"scoring_error:{type(exc).__name__}"])
        if rec is None:
            base = {"invalid_record_repr": _short_repr(lead)}
        else:
            base = dict(rec)     # copy: the caller's record is never mutated
        for key in PASSTHROUGH_KEYS:
            base.setdefault(key, None)
        out.append({**base, **res})
    return out


def _safe_score(v: Any) -> Optional[float]:
    """Numeric score or None (bool, NaN, inf, text, overflow all -> None)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except Exception:
        return None
    return f if math.isfinite(f) else None


def _sort_key(item: tuple) -> tuple:
    idx, rec = item
    if not isinstance(rec, Mapping):          # not a record: after everything
        return (UNRANKED + 1, 0.0, 1, "", idx)
    is_vip = parse_vip(rec.get("is_vip"))
    score = _safe_score(rec.get("score"))
    if score is None and is_vip:
        score = float(VIP_SCORE)
    priority = _clean(rec.get("priority")).upper()
    if priority in TIER_RANK:
        rank = TIER_RANK[priority]
    elif score is not None:                   # bad/missing priority: derive it
        rank = TIER_RANK[tier_for(score)]
    else:                                     # nothing usable: after LOW
        rank = UNRANKED
    try:
        lead_id = str(rec.get("Lead_ID") or "")
    except Exception:
        lead_id = ""
    return (rank, -(score if score is not None else 0.0),
            0 if is_vip else 1, lead_id, idx)


def sort_for_routing(scored: Iterable[Any]) -> list:
    """Routing order. Never raises; returns every item (none dropped).

    1. Tier: CRITICAL, HIGH, MEDIUM, LOW (Critical always first, per the
       challenge). A missing/invalid priority is derived from the score; if
       neither is usable the item goes after LOW. Non-record items go last.
    2. Score, highest first (missing/invalid score counts as 0; a VIP with no
       usable score counts as 100).
    3. VIP before non-VIP at equal score. This tie-break is deliberate: a
       non-VIP lead can also reach 100 (50 + 35 + 15), so VIPs are NOT first
       "automatically"; they lead the CRITICAL tier only because of this rule.
    4. Lead_ID ascending, then original input position (so duplicate Lead_IDs
       still sort deterministically).
    """
    if scored is None:
        return []
    items = list(enumerate(scored))
    items.sort(key=_sort_key)
    return [rec for _, rec in items]