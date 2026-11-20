"""Write cleaned CSVs from the normalizer so teammates can inspect or test against them.

Usage (from the repo root):  python scripts/export_cleaned.py
Teammates should still call normalize_data() directly when they can: CSV loses types
(company_size None becomes blank, flags are joined with "|").
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.data_loader import load_data  # noqa: E402
from src.normalize import normalize_data  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
LEAD_FIELDS = ["lead_id", "record_id", "company_name", "region", "language", "industry",
               "company_size", "company_size_label", "recent_activity", "vip", "vip_unknown", "flags"]
REP_FIELDS = ["rep_id", "record_id", "name", "region", "language", "industry", "seniority",
              "current_capacity", "max_capacity", "flags"]


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        out = csv.DictWriter(handle, fieldnames=fields)
        out.writeheader()
        for row in rows:
            row = dict(row)
            row["flags"] = "|".join(row["flags"])
            if row.get("company_size", 0) is None:
                row["company_size"] = ""
            out.writerow({k: row.get(k, "") for k in fields})


for size in ("sample", "scale"):
    leads, reps = load_data(os.path.join(ROOT, "data", f"leads_{size}.csv"),
                            os.path.join(ROOT, "data", f"reps_{size}.csv"))
    clean_leads, clean_reps, warnings = normalize_data(leads, reps)
    os.makedirs(os.path.join(ROOT, "cleaned"), exist_ok=True)
    write(os.path.join(ROOT, "cleaned", f"leads_{size}_cleaned.csv"), LEAD_FIELDS, clean_leads)
    write(os.path.join(ROOT, "cleaned", f"reps_{size}_cleaned.csv"), REP_FIELDS, clean_reps)
    print(size, len(clean_leads), "leads", len(clean_reps), "reps", len(warnings), "warnings")
