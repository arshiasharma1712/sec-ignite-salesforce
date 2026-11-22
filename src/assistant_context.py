"""Bounded, read-only queries over the dashboard's existing result dictionary.

Counts cover every matching row; only displayed records/groups are capped.
No network, file writes, dynamic code execution, or pipeline mutations occur here.
"""
from collections import Counter
from copy import deepcopy
from numbers import Integral

from src.routing import route_leads
from src.scoring import score_lead

MAX_ROWS = 20
MAX_TEXT = 160
LEAD_FIELDS = ("lead_id", "company", "region", "language", "industry", "company_size",
               "activity", "vip", "score", "priority", "assignment_status", "rep_id", "rep_name", "rep_seniority", "reason")
REP_FIELDS = ("rep_id", "name", "region", "language", "industry", "seniority",
              "current_capacity", "max_capacity")
PRIORITY = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
RULES = {
    "scoring": "VIP referrals score 100/Critical. Otherwise add size points (1000+ employees: 50; "
               "100-999: 30; 0-99: 0; missing/invalid: 20), activity points (demo/contact sales: 35; "
               "webinar: 25; whitepaper: 15; pricing page: 5; other/missing: 0), and industry points "
               "(Technology: 15; Healthcare/Finance: 10; Manufacturing/Retail/Unknown: 0). "
               "Critical >=85; High 60-84; Medium 40-59; Low 0-39.",
    "routing": "Automatic routing requires known, matching region, language and industry. "
               "Unknown/missing/unresolved matching fields go to Manager Review, including VIPs. "
               "Critical leads go to Seniors with room first, then Managers, never Juniors. Other "
               "tiers use equal round-robin across eligible Junior/Senior/Manager reps. Maximum "
               "capacity is respected. Missing/duplicate rep IDs, unresolved skills/seniority and "
               "invalid capacities exclude a rep. Unknown is never a matching group or wildcard.",
    "ordering": "Priority, descending score, VIP first at equal score, lexicographic Lead_ID, "
                "then original row position. Representative queues are ordered by Rep_ID.",
    "normalization": "Explicit aliases normalize spelling/case/whitespace. The two recognized fused "
                     "region spellings use the trailing region under the current suffix policy. "
                     "Unknown VIP is treated as false and flagged; missing size/activity uses scoring "
                     "fallbacks and alone does not prevent assignment. Unknown routing fields do.",
    "dashboard": "Run Sample processes 100 leads; Run Scale processes 50,000 leads and 1,600 reps. "
                 "Each run starts from CSV baseline capacities. Reset clears outputs. Filters only "
                 "change the view. Lead IDs shown here are unique normalized row keys. Manager Review "
                 "contains unassigned leads and reasons; Handled means a manager handled it outside "
                 "the system. Manager defaults can fill missing values before a run. Explicit manual "
                 "assignments can override skill matching; distinguish them from automatic routing.",
    "evidence_limits": "Stored outcomes and current capacities are available, but historical queue "
                       "positions and capacity at the instant of assignment are not recorded. Do not "
                       "invent that audit trail. Current edits may differ from the inputs originally "
                       "scored. Chat cannot assign leads, edit data, run/reset the pipeline, or browse the web.",
}


def _object(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def _string(**extra):
    return {"type": "string", **extra}


def _tool(name, description, parameters):
    return {"type": "function", "name": name, "description": description, "parameters": parameters}


LEAD_FILTERS = {key: _string() for key in
                ("lead_id", "rep_id", "priority", "assignment_status", "region", "language", "industry", "search")}
LEAD_FILTERS.update(vip={"type": "boolean"}, min_score={"type": "integer", "minimum": 0, "maximum": 100})
REP_FILTERS = {key: _string() for key in ("rep_id", "seniority", "region", "language", "industry", "search")}
REP_FILTERS.update(eligible={"type": "boolean"}, min_remaining={"type": "integer", "minimum": 0})
LEAD_GROUPS = ("priority", "assignment_status", "region", "language", "industry", "reason", "vip", "rep_id")
REP_GROUPS = ("seniority", "region", "language", "industry", "eligible")
TOOL_DEFINITIONS = [
    _tool("get_program_rules", "Explain current scoring, routing, normalization and dashboard behavior.", _object({})),
    _tool("get_summary", "Get exact current totals and review reasons for the entire loaded dataset.", _object({})),
    _tool("query_leads", "Filter leads, count all matches, optionally group counts, and show up to 20 prioritized rows.",
          _object({"filters": _object(LEAD_FILTERS), "group_by": _string(enum=list(LEAD_GROUPS)),
                   "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}})),
    _tool("query_reps", "Filter current reps and capacity; eligible means valid for automatic routing. Counts cover all matches.",
          _object({"filters": _object(REP_FILTERS), "group_by": _string(enum=list(REP_GROUPS)),
                   "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}})),
    _tool("lookup_record", "Look up an exact displayed lead/rep ID. Duplicate IDs require a row_index from the returned choices.",
          _object({"entity": _string(enum=["lead", "rep"]), "identifier": _string(),
                   "row_index": {"type": "integer", "minimum": 0}}, ("entity", "identifier"))),
]


def _validate(value, schema):
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) - set(schema["properties"]):
            raise ValueError("Use only the documented query arguments.")
        if set(schema["required"]) - set(value):
            raise ValueError("A required query argument is missing.")
        for key, child in value.items():
            _validate(child, schema["properties"][key])
    elif kind == "string":
        if not isinstance(value, str) or len(value) > 200 or ("enum" in schema and value not in schema["enum"]):
            raise ValueError("Use a supported field/value and strings of at most 200 characters.")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError("This filter requires true or false.")
    elif kind == "integer":
        if type(value) is not int or value < schema.get("minimum", 0) or value > schema.get("maximum", 10**9):
            raise ValueError("This query number is outside its allowed range.")


def _number(value):
    return int(value) if isinstance(value, Integral) and not isinstance(value, bool) else 0


def _safe(value):
    if isinstance(value, str):
        return value[:MAX_TEXT] + ("… [truncated]" if len(value) > MAX_TEXT else "")
    if value is None or isinstance(value, (bool, int)):
        return value
    return _safe(str(value))


def _row(record, index, fields):
    row = {key: _safe(record.get(key)) for key in fields}
    row["row_index"] = index
    row["manual_action"] = _safe(record.get("manual"))
    row["edited_fields"] = [_safe(key) for key in sorted(record.get("overrides") or {})[:10]]
    row["defaults_applied"] = [_safe(key) for key in (record.get("defaults_applied") or [])[:10]]
    return row


def _matches(row, filters):
    for key, wanted in filters.items():
        if key == "search":
            if wanted.casefold() not in " ".join(str(value) for value in row.values()).casefold():
                return False
        elif key in ("min_score", "min_remaining"):
            if _number(row.get("score" if key == "min_score" else "remaining")) < wanted:
                return False
        elif key in ("vip", "eligible"):
            if row.get(key) is not wanted:
                return False
        elif key in ("lead_id", "rep_id"):
            if row.get(key) != wanted:
                return False
        elif str(row.get(key) or "").strip().casefold() != wanted.strip().casefold():
            return False
    return True


def _groups(rows, field):
    if field is None:
        return {}
    counts = Counter(str(row.get(field) if row.get(field) is not None else "Unknown") for row in rows)
    return {"group_by": field, "groups": [{"value": _safe(key), "count": count}
            for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:MAX_ROWS]],
            "total_groups": len(counts), "groups_truncated": len(counts) > MAX_ROWS}


class AssistantContext:
    """One question's view of current results. No cached baseline or global data."""

    def __init__(self, results=None, dataset_label=None):
        self.loaded = results is not None
        self.dataset = _safe(dataset_label or "Current run")
        self.leads = (results or {}).get("leads", [])
        self.reps = (results or {}).get("reps", [])
        self.defaults = (results or {}).get("defaults_used") or {}
        # Reuse the router's validators with zero leads; no assignment is made.
        mapped = [{"Rep_ID": rep.get("rep_id"), "Region": rep.get("region"),
                   "Language": rep.get("language"), "Industry_Vertical_Expertise": rep.get("industry"),
                   "Seniority_Level": rep.get("seniority"), "Current_Capacity": rep.get("current_capacity"),
                   "Max_Capacity": rep.get("max_capacity")} for rep in self.reps]
        self.excluded = {warning["source_index"]: warning["reason"]
                         for warning in route_leads([], mapped)["rep_warnings"]}

    def _rep(self, index, record):
        row = _row(record, index, REP_FIELDS)
        row.update(eligible=index not in self.excluded, exclusion_reason=self.excluded.get(index),
                   remaining=max(0, _number(record.get("max_capacity")) - _number(record.get("current_capacity"))))
        return row

    def _no_data(self):
        return {"loaded": False, "message": "Run Sample or Run Scale before asking about current results."}

    def get_program_rules(self):
        return {"rules": deepcopy(RULES), "sources": ["Scoring rules", "Routing contract", "Dashboard behavior"]}

    def get_summary(self):
        if not self.loaded:
            return self._no_data()
        statuses = Counter(row.get("assignment_status") for row in self.leads)
        reasons = [row for row in self.leads if row.get("assignment_status") == "Manager Review"]
        reps = [self._rep(i, row) for i, row in enumerate(self.reps)]
        return {"loaded": True, "dataset": self.dataset, "total_leads": len(self.leads),
                "assigned": statuses["Assigned"], "manager_review": statuses["Manager Review"],
                "handled": statuses["Handled"], "vip_count": sum(bool(row.get("vip")) for row in self.leads),
                "manual_assignments": sum(row.get("manual") == "assigned" for row in self.leads),
                "manager_defaults": {key: _safe(value) for key, value in self.defaults.items()},
                "assignment_rate": statuses["Assigned"] / len(self.leads) if self.leads else 0,
                "review_reasons": _groups(reasons, "reason"), "total_reps": len(reps),
                "excluded_reps": len(self.excluded),
                "capacity_used_all_reps": sum(_number(row.get("current_capacity")) for row in reps),
                "capacity_max_all_reps": sum(max(0, _number(row.get("max_capacity"))) for row in reps),
                "available_slots_eligible_reps": sum(row["remaining"] for row in reps if row["eligible"]),
                "sources": [f"{self.dataset}: current outcomes and capacities"]}

    def query_leads(self, filters=None, group_by=None, limit=MAX_ROWS):
        if not self.loaded:
            return self._no_data()
        matches = [(i, row) for i, row in enumerate(self.leads) if _matches(row, filters or {})]
        ordered = sorted(matches, key=lambda pair: (PRIORITY.get(pair[1].get("priority"), 4),
                         -_number(pair[1].get("score")), not pair[1].get("vip", False),
                         str(pair[1].get("lead_id") or ""), pair[0]))
        return {"dataset": self.dataset, "total_matches": len(matches), "truncated": len(matches) > limit,
                "rows": [_row(row, index, LEAD_FIELDS) for index, row in ordered[:limit]],
                **_groups([row for _, row in matches], group_by),
                "sources": [f"{self.dataset}: lead query"]}

    def query_reps(self, filters=None, group_by=None, limit=MAX_ROWS):
        if not self.loaded:
            return self._no_data()
        # Match full values before shortening strings for the provider.
        rows = [{**record, "row_index": index, "eligible": index not in self.excluded,
                 "remaining": max(0, _number(record.get("max_capacity")) - _number(record.get("current_capacity")))}
                for index, record in enumerate(self.reps)]
        rows = [row for row in rows if _matches(row, filters or {})]
        rows.sort(key=lambda row: (not row["eligible"], -row["remaining"], str(row.get("rep_id") or ""), row["row_index"]))
        return {"dataset": self.dataset, "total_matches": len(rows), "truncated": len(rows) > limit,
                "available_slots_eligible_reps": sum(row["remaining"] for row in rows if row["eligible"]),
                "rows": [self._rep(row["row_index"], row) for row in rows[:limit]], **_groups(rows, group_by),
                "sources": [f"{self.dataset}: representative query"]}

    def lookup_record(self, entity, identifier, row_index=None):
        if not self.loaded:
            return self._no_data()
        records = self.leads if entity == "lead" else self.reps
        key = "lead_id" if entity == "lead" else "rep_id"
        matches = [(index, row) for index, row in enumerate(records)
                   if row.get(key) == identifier and (row_index is None or row_index == index)]
        result = {"dataset": self.dataset, "total_matches": len(matches), "ambiguous": len(matches) > 1,
                  "truncated": len(matches) > MAX_ROWS,
                  "rows": [_row(row, i, LEAD_FIELDS) if entity == "lead" else self._rep(i, row)
                           for i, row in matches[:MAX_ROWS]],
                  "sources": [f"{self.dataset}: {entity} {_safe(identifier)}"]}
        if len(matches) == 1 and entity == "lead":
            row = matches[0][1]
            score = score_lead({"Company_Size": row.get("company_size"), "Recent_Activity": row.get("activity"),
                                "Industry_Vertical": row.get("industry"), "VIP_Referral": row.get("vip")})
            result["score_from_current_fields"] = score
            result["matches_stored_score"] = score["score"] == row.get("score")
            result["score_note"] = "Calculation uses current displayed fields; original scoring inputs and routing queue trace are not stored here."
        return result

    def call(self, name, arguments):
        definitions = {tool["name"]: tool for tool in TOOL_DEFINITIONS}
        if name not in definitions:
            return {"error": "Unknown tool. Only the listed read-only program/data queries are available."}
        try:
            _validate(arguments, definitions[name]["parameters"])
            return getattr(self, name)(**arguments)
        except ValueError as error:
            return {"error": str(error)}
