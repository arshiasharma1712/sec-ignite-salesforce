"""CSV loading and schema validation (owner: Arush).

Contract:
    load_data(leads_path, reps_path) -> (raw_leads, raw_reps)

Both results are list[dict]. Keys are the canonical header names from the data
dictionary (for example "Lead_ID"); values are the raw strings from the file,
untouched. Cleaning happens in normalize.py, never here.

Behavior:
    * Header names are matched case-insensitively after trimming whitespace, so
      " lead_id" and "LEAD_ID" both load as "Lead_ID".
    * A file with no data (zero bytes, or header only) returns [].
    * A file that has a header row but lacks a required column raises
      SchemaError with the missing names. Silently continuing would make every
      downstream record look broken.
    * A UTF-8 byte order mark is ignored.
    * Short rows are padded with "" and extra cells are ignored, so a ragged
      line cannot crash the pipeline.
"""

import csv

LEAD_COLUMNS = [
    "Lead_ID",
    "Company_Name",
    "Region",
    "Language",
    "Industry_Vertical",
    "Company_Size",
    "Recent_Activity",
    "VIP_Referral",
]

REP_COLUMNS = [
    "Rep_ID",
    "Name",
    "Region",
    "Language",
    "Industry_Vertical_Expertise",
    "Seniority_Level",
    "Current_Capacity",
    "Max_Capacity",
]


class SchemaError(ValueError):
    """Raised when a CSV is missing columns the pipeline cannot work without."""


def _read_csv(path, required, label):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return []  # zero-byte file

        by_lower = {name.strip().lower(): name for name in required}
        index_to_name = {}
        for i, cell in enumerate(header):
            canonical = by_lower.get(cell.strip().lower())
            if canonical and canonical not in index_to_name.values():
                index_to_name[i] = canonical

        missing = [name for name in required if name not in index_to_name.values()]
        if missing:
            raise SchemaError(
                f"{label} file {path!s} is missing required column(s): "
                + ", ".join(missing)
            )

        rows = []
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue  # blank line
            row = {name: "" for name in required}
            for i, name in index_to_name.items():
                if i < len(cells):
                    row[name] = cells[i]
            rows.append(row)
        return rows


def load_leads(path):
    return _read_csv(path, LEAD_COLUMNS, "Leads")


def load_reps(path):
    return _read_csv(path, REP_COLUMNS, "Reps")


def load_data(leads_path, reps_path):
    """Return (raw_leads, raw_reps) as lists of dicts of raw strings."""
    return load_leads(leads_path), load_reps(reps_path)
