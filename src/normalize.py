"""Normalization and missing-value policies (owner: Arush).

Contract:
    normalize_data(raw_leads, raw_reps) -> (leads, reps, warnings)

Input is the list[dict] of raw strings produced by data_loader.load_data.
Inputs are never modified.

Clean lead keys
    lead_id          original ID as supplied
    record_id        unique key for this row. Equals lead_id unless the ID
                     appears more than once, then "L-1057#1", "L-1057#2".
                     Use record_id wherever a unique key is needed.
    company_name     whitespace-collapsed string
    region           "North America" | "Europe" | "Asia-Pacific" | "Unknown"
    language         "English" | "Spanish" | "German" | "Unknown"
    industry         "Technology" | "Healthcare" | "Finance" | "Manufacturing"
                     | "Retail" | "Unknown"
    company_size     int >= 0, or None when missing or invalid (kept
                     numeric-or-None so scoring can award the +20 missing bonus)
    company_size_label  the number as text, or "Unknown" when company_size is
                     None (for display)
    recent_activity  canonical activity string, or "Unknown" (blank, N/A,
                     or unrecognized). "Unknown" scores +0.
    vip              bool
    vip_unknown      True when the raw value was Unknown/blank/unparseable
    flags            list of data-quality flag names for this record
    Lead_ID, Company_Name, Region, Language, Industry_Vertical, Company_Size,
    Recent_Activity, VIP_Referral
                     the same cleaned values under the original CSV column
                     names, because src/scoring.py reads those names

Clean rep keys
    rep_id, name, region, language, industry, seniority
    rep_id           original cleaned identity, including duplicates/blanks;
                     never replaced by a generated row key
    record_id        unique row key for traceability only, like lead record_id;
                     routing must use Rep_ID/rep_id to validate rep identity
    (seniority: "Junior" | "Senior" | "Manager" | "Unknown")
    Rep_ID, Name, Region, Language, Industry_Vertical_Expertise, Seniority_Level,
    Current_Capacity, Max_Capacity
                     the same cleaned values under the original CSV column
                     names, because src/routing.py reads those names
    current_capacity, max_capacity (ints; max_capacity falls back to 0)
    flags

"Unknown" means a value was supplied as unknown or could not be resolved.
Unknown region, language, or industry goes to Manager Review during routing.
Representatives with an Unknown matching field are retained but excluded from
routing. Unmapped values keep their quality flags and warnings.

Policies (see also the warnings list, which logs every non-trivial fix):
    * Case, surrounding whitespace, repeated spaces and . - _ separators are
      normalized silently. Those are formatting noise, not guesses.
    * Aliases come from explicit dictionaries below. Anything not in a
      dictionary becomes "Unknown" with a warning.
    * Fused regions ("NORTH   AMERICA Asia-Pacific", "ASIA   PACIFICEurope")
      are read as the trailing region, logged as mapped_suffix and flagged
      region_fused. The evidence is in the comment above FUSED_REGION_ALIASES.
      Set FUSED_REGION_POLICY = "unknown" to treat them as unreadable instead.
    * VIP: True and False parse normally. Unknown, blank or unparseable is
      treated as False (never a free Critical) and flagged vip_unknown.
    * Company_Size: "1,000" -> 1000 and "5k" -> 5000 (both unambiguous
      notation). A range ("500-1000") uses its lower end, matching scoring.py.
      A negative or text becomes None, which scoring treats as missing (+20).
      Overflow in k notation also becomes None with an invalid-size warning,
      so one unrepresentable value cannot abort the batch.
    * Rep capacity: a negative max whose absolute value falls in the data
      dictionary's range for that seniority (Junior 40-50, Senior 20-25,
      Manager 5-10) is treated as a sign typo and flipped. In the supplied scale
      file all 94 negative values fit their range exactly. Any other negative
      or non-numeric max becomes 0 (rep stays visible but can take nothing). A
      bad current becomes 0. current > max is clamped to max. Every fix is
      logged.
    * Duplicate Lead_IDs keep every row (they are different companies) and get
      distinct record_id values.
    * Duplicate/missing Rep_IDs are preserved so routing can exclude them.
      Separate record_id values identify the rows without inventing rep identities.
"""

import re

REGION_ALIASES = {
    "north america": "North America",
    "na": "North America",
    "north amer": "North America",
    "nort america": "North America",
    "europe": "Europe",
    "eur": "Europe",
    "europ": "Europe",
    "asia pacific": "Asia-Pacific",
    "apac": "Asia-Pacific",
    "asa pacific": "Asia-Pacific",
}

LANGUAGE_ALIASES = {
    "english": "English",
    "en": "English",
    "spanish": "Spanish",
    "es": "Spanish",
    "german": "German",
    "de": "German",
}

INDUSTRY_ALIASES = {
    "technology": "Technology",
    "healthcare": "Healthcare",
    "finance": "Finance",
    "manufacturing": "Manufacturing",
    "retail": "Retail",
    "unknown": "Unknown",
}

SENIORITY_ALIASES = {
    "junior": "Junior",
    "jr": "Junior",
    "senior": "Senior",
    "sr": "Senior",
    "manager": "Manager",
    "mgr": "Manager",
}

ACTIVITY_ALIASES = {
    "requested live demo": "Requested Live Demo",
    "contact sales": "Contact Sales",
    "attended webinar": "Attended Webinar",
    "downloaded whitepaper": "Downloaded Whitepaper",
    "visited pricing page": "Visited Pricing Page",
    "opened marketing email": "Opened Marketing Email",
    "subscribed to blog": "Subscribed to Blog",
    "started free trial": "Started Free Trial",
}

MISSING_TOKENS = {"", "none", "null", "n/a", "na", "nan", "unknown", "-"}
TRUE_TOKENS = {"true", "t", "yes", "y", "1"}
FALSE_TOKENS = {"false", "f", "no", "n", "0"}

_SIZE_PLAIN = re.compile(r"^\d+$")
_SIZE_COMMAS = re.compile(r"^\d{1,3}(,\d{3})+$")
_SIZE_K = re.compile(r"^(\d+(?:\.\d+)?)\s*k$", re.IGNORECASE)
_SIZE_RANGE = re.compile(r"^(\d[\d,]*)\s*(?:-|to)\s*(\d[\d,]*)$", re.IGNORECASE)
_INT = re.compile(r"^[+-]?\d+$")

# Typical Max_Capacity ranges from the data dictionary. Used only to repair
# negative values (see normalize_reps).
CAPACITY_RANGES = {"Junior": (40, 50), "Senior": (20, 25), "Manager": (5, 10)}

# Original CSV column name -> cleaned key. Added to every cleaned lead so the
# scoring and routing modules can read either spelling.
LEAD_COLUMN_ALIASES = {
    "Lead_ID": "lead_id",
    "Company_Name": "company_name",
    "Region": "region",
    "Language": "language",
    "Industry_Vertical": "industry",
    "Company_Size": "company_size",
    "Recent_Activity": "recent_activity",
    "VIP_Referral": "vip",
}

# Same idea for reps: src/routing.py reads the original CSV column names.
REP_COLUMN_ALIASES = {
    "Rep_ID": "rep_id",
    "Name": "name",
    "Region": "region",
    "Language": "language",
    "Industry_Vertical_Expertise": "industry",
    "Seniority_Level": "seniority",
    "Current_Capacity": "current_capacity",
    "Max_Capacity": "max_capacity",
}

# Fused regions. Two spellings in the data look like two region names glued
# together: "NORTH   AMERICA Asia-Pacific" and "ASIA   PACIFICEurope". Evidence
# for reading each as the region at the END of the string: in both the leads and
# the reps, every region has exactly five spellings, and only with these two
# counted as "Asia-Pacific" and "Europe" does each region reach five, each at
# the same frequency (about 6.6% of rows). The leading words look like injected
# noise. This is an inference from the data, not something the data dictionary
# states, so it is a switch: set FUSED_REGION_POLICY = "unknown" to stop guessing
# and send those rows to Manager Review instead.
FUSED_REGION_ALIASES = {
    "north america asia pacific": "Asia-Pacific",
    "asia pacificeurope": "Europe",
}
FUSED_REGION_POLICY = "suffix"  # "suffix" or "unknown"

OUTLIER_SIZE = 10_000_000
UNKNOWN = "Unknown"


def _text(value):
    """Raw cell to a whitespace-collapsed string (None -> '')."""
    return " ".join(str(value).split()) if value is not None else ""


def _key(value):
    """Lookup key: lowercase, separators to spaces, whitespace collapsed."""
    return " ".join(re.sub(r"[.\-_/]", " ", _text(value)).lower().split())


def _warn(warnings, entity, record_id, field, raw, action, message):
    warnings.append(
        {
            "entity": entity,
            "id": record_id,
            "field": field,
            "raw": raw,
            "action": action,
            "message": message,
        }
    )


def _alias(value, table, entity, record_id, field, warnings, flags):
    """Map a value through an alias table. Unmapped becomes "Unknown" and is logged."""
    key = _key(value)
    if key in table:
        return table[key]
    flags.append(f"{field}_unmapped")
    _warn(
        warnings,
        entity,
        record_id,
        field,
        value,
        "set_unknown",
        "blank value" if key == "" else "value not in alias table (not guessed)",
    )
    return UNKNOWN


def _region(value, entity, record_id, warnings, flags):
    """Region alias lookup, plus the fused-region policy (see FUSED_REGION_*)."""
    key = _key(value)
    if key not in REGION_ALIASES and FUSED_REGION_POLICY == "suffix" and key in FUSED_REGION_ALIASES:
        flags.append("region_fused")
        _warn(
            warnings,
            entity,
            record_id,
            "region",
            value,
            "mapped_suffix",
            f"two region names joined; read as the trailing one, {FUSED_REGION_ALIASES[key]}",
        )
        return FUSED_REGION_ALIASES[key]
    return _alias(value, REGION_ALIASES, entity, record_id, "region", warnings, flags)


def parse_company_size(raw):
    """Return (value, status). status: ok | missing | interpreted | invalid."""
    text = _text(raw)
    low = text.lower()
    if low in MISSING_TOKENS:
        return None, "missing"
    if _SIZE_PLAIN.match(text):
        return int(text), "ok"
    if _SIZE_COMMAS.match(text):
        return int(text.replace(",", "")), "ok"
    match = _SIZE_K.match(text)
    if match:
        try:
            return int(round(float(match.group(1)) * 1000)), "interpreted"
        except (OverflowError, ValueError):
            return None, "invalid"
    match = _SIZE_RANGE.match(text)
    if match:
        # Same policy as scoring.py (RANGE_POLICY = "lower"): credit only the
        # size we are sure of, never Enterprise points on a maybe.
        ends = [int(part.replace(",", "")) for part in match.groups()]
        return min(ends), "interpreted"
    return None, "invalid"


def parse_vip(raw):
    """Return (vip, unknown). Unknown or unparseable is (False, True)."""
    low = _text(raw).lower()
    if low in TRUE_TOKENS:
        return True, False
    if low in FALSE_TOKENS:
        return False, False
    return False, True


def _parse_int(raw):
    text = _text(raw)
    return int(text) if _INT.match(text) else None


def _unique_ids(ids, entity, warnings, fallback_prefix):
    """Unique row keys; generated keys cannot collide with supplied identities."""
    totals = {}
    for value in ids:
        totals[value] = totals.get(value, 0) + 1
    reserved = set(ids) - {""}
    seen = {}
    used = set()
    keys = []
    for position, value in enumerate(ids, start=1):
        if not value:
            key = f"{fallback_prefix}-{position}"
        elif totals[value] == 1:
            key = value
        else:
            seen[value] = seen.get(value, 0) + 1
            key = f"{value}#{seen[value]}"

        base, suffix = key, 1
        while key in used or (key in reserved and key != value):
            key = f"{base}#{suffix}"
            suffix += 1
        used.add(key)
        keys.append(key)

        if not value:
            _warn(warnings, entity, key, "id", value, "generated_id", "missing ID")
        elif totals[value] > 1 and seen[value] > 1:
            _warn(
                warnings,
                entity,
                key,
                "id",
                value,
                "suffixed_id",
                "duplicate ID shared by different records; kept both",
            )
    return keys


def normalize_leads(raw_leads, warnings):
    ids = [_text(r.get("Lead_ID")) for r in raw_leads]
    keys = _unique_ids(ids, "lead", warnings, "MISSING-LEAD")
    cleaned = []
    for raw, lead_id, record_id in zip(raw_leads, ids, keys):
        flags = []
        if record_id != lead_id:
            flags.append("duplicate_or_missing_id")

        size, status = parse_company_size(raw.get("Company_Size"))
        if status == "missing":
            flags.append("size_missing")
        elif status in ("interpreted", "invalid"):
            flags.append(f"size_{status}")
            _warn(
                warnings,
                "lead",
                record_id,
                "company_size",
                raw.get("Company_Size"),
                "parsed" if status == "interpreted" else "set_none",
                {
                    "interpreted": f"read as {size} (5k style or lower end of a range)",
                    "invalid": "not a usable number; treated as missing",
                }[status],
            )
        if size is not None and size > OUTLIER_SIZE:
            flags.append("size_outlier")
            _warn(
                warnings,
                "lead",
                record_id,
                "company_size",
                raw.get("Company_Size"),
                "kept",
                "implausibly large; kept as supplied",
            )

        vip, vip_unknown = parse_vip(raw.get("VIP_Referral"))
        if vip_unknown:
            flags.append("vip_unknown")
            _warn(
                warnings,
                "lead",
                record_id,
                "vip_referral",
                raw.get("VIP_Referral"),
                "set_false",
                "Unknown/blank VIP treated as False (conservative)",
            )

        activity_key = _key(raw.get("Recent_Activity"))
        if activity_key in ACTIVITY_ALIASES:
            activity = ACTIVITY_ALIASES[activity_key]
        else:
            activity = UNKNOWN
            if _text(raw.get("Recent_Activity")).lower() not in MISSING_TOKENS:
                flags.append("activity_unmapped")
                _warn(
                    warnings,
                    "lead",
                    record_id,
                    "recent_activity",
                    raw.get("Recent_Activity"),
                    "set_unknown",
                    "unrecognized activity; scores +0",
                )

        cleaned.append(
            {
                "lead_id": lead_id,
                "record_id": record_id,
                "company_name": _text(raw.get("Company_Name")),
                "region": _region(raw.get("Region"), "lead", record_id, warnings, flags),
                "language": _alias(raw.get("Language"), LANGUAGE_ALIASES, "lead", record_id, "language", warnings, flags),
                "industry": _alias(raw.get("Industry_Vertical"), INDUSTRY_ALIASES, "lead", record_id, "industry", warnings, flags),
                "company_size": size,
                "company_size_label": str(size) if size is not None else UNKNOWN,
                "recent_activity": activity,
                "vip": vip,
                "vip_unknown": vip_unknown,
                "flags": flags,
            }
        )
        # scoring.py (Arshia) reads the original CSV column names, so every
        # cleaned lead also carries them. Same values, one source of truth.
        row = cleaned[-1]
        for original, clean in LEAD_COLUMN_ALIASES.items():
            row[original] = row[clean]
    return cleaned


def normalize_reps(raw_reps, warnings):
    ids = [_text(r.get("Rep_ID")) for r in raw_reps]
    keys = _unique_ids(ids, "rep", warnings, "MISSING-REP")
    cleaned = []
    for raw, rep_id, record_id in zip(raw_reps, ids, keys):
        flags = []
        if record_id != rep_id:
            flags.append("duplicate_or_missing_id")

        seniority = _alias(raw.get("Seniority_Level"), SENIORITY_ALIASES, "rep", record_id, "seniority", warnings, flags)

        max_cap = _parse_int(raw.get("Max_Capacity"))
        if max_cap is not None and max_cap < 0:
            low, high = CAPACITY_RANGES.get(seniority, (None, None))
            if low is not None and low <= -max_cap <= high:
                flags.append("max_capacity_sign_fixed")
                _warn(
                    warnings,
                    "rep",
                    record_id,
                    "max_capacity",
                    raw.get("Max_Capacity"),
                    "sign_fixed",
                    f"negative max; its absolute value {-max_cap} fits the "
                    f"{seniority} range in the data dictionary, so the sign was "
                    "treated as a typo",
                )
                max_cap = -max_cap
        if max_cap is None or max_cap < 0:
            flags.append("max_capacity_invalid")
            _warn(
                warnings,
                "rep",
                record_id,
                "max_capacity",
                raw.get("Max_Capacity"),
                "set_zero",
                "negative or non-numeric max with no safe repair; rep kept with capacity 0",
            )
            max_cap = 0

        current = _parse_int(raw.get("Current_Capacity"))
        if current is None or current < 0:
            flags.append("current_capacity_invalid")
            _warn(
                warnings,
                "rep",
                record_id,
                "current_capacity",
                raw.get("Current_Capacity"),
                "set_zero",
                "negative or non-numeric current load; set to 0",
            )
            current = 0
        if current > max_cap:
            flags.append("current_over_max")
            _warn(
                warnings,
                "rep",
                record_id,
                "current_capacity",
                raw.get("Current_Capacity"),
                "clamped",
                f"current exceeded max; clamped to {max_cap}",
            )
            current = max_cap

        cleaned.append(
            {
                "rep_id": rep_id,
                "record_id": record_id,
                "name": _text(raw.get("Name")),
                "region": _region(raw.get("Region"), "rep", record_id, warnings, flags),
                "language": _alias(raw.get("Language"), LANGUAGE_ALIASES, "rep", record_id, "language", warnings, flags),
                "industry": _alias(raw.get("Industry_Vertical_Expertise"), INDUSTRY_ALIASES, "rep", record_id, "industry", warnings, flags),
                "seniority": seniority,
                "current_capacity": current,
                "max_capacity": max_cap,
                "flags": flags,
            }
        )
        # src/routing.py (Ethan) reads the original CSV column names.
        row = cleaned[-1]
        for original, clean in REP_COLUMN_ALIASES.items():
            row[original] = row[clean]
    return cleaned


def normalize_data(raw_leads, raw_reps):
    """Clean both datasets. Returns (leads, reps, warnings)."""
    warnings = []
    leads = normalize_leads(raw_leads or [], warnings)
    reps = normalize_reps(raw_reps or [], warnings)
    return leads, reps, warnings


def summarize_warnings(warnings):
    """Count warnings by (entity, field, action) for dashboards and the README."""
    counts = {}
    for item in warnings:
        key = (item["entity"], item["field"], item["action"])
        counts[key] = counts.get(key, 0) + 1
    return counts
