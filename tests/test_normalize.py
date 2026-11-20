import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_loader import SchemaError, load_data, load_leads, load_reps  # noqa: E402
from src.normalize import (  # noqa: E402
    normalize_data,
    parse_company_size,
    parse_vip,
    summarize_warnings,
)

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def lead(**over):
    base = {
        "Lead_ID": "L-1",
        "Company_Name": "Acme",
        "Region": "NA",
        "Language": "EN",
        "Industry_Vertical": "Technology",
        "Company_Size": "100",
        "Recent_Activity": "Contact Sales",
        "VIP_Referral": "False",
    }
    base.update(over)
    return base


def rep(**over):
    base = {
        "Rep_ID": "R-1",
        "Name": "Sam",
        "Region": "NA",
        "Language": "EN",
        "Industry_Vertical_Expertise": "Technology",
        "Seniority_Level": "Senior",
        "Current_Capacity": "0",
        "Max_Capacity": "5",
    }
    base.update(over)
    return base


def one_lead(**over):
    leads, _, warnings = normalize_data([lead(**over)], [])
    return leads[0], warnings


def one_rep(**over):
    _, reps, warnings = normalize_data([], [rep(**over)])
    return reps[0], warnings


# ---------- whitespace and casing ----------

@pytest.mark.parametrize(
    "raw",
    [" EUROPE ", "europe", "EUROPE", "Europe", "  eUrOpE\t"],
)
def test_region_whitespace_and_case(raw):
    assert one_lead(Region=raw)[0]["region"] == "Europe"


def test_internal_whitespace_and_separators_collapse():
    assert one_lead(Region="North  Amer")[0]["region"] == "North America"
    assert one_lead(Region="Asia.  Pacific")[0]["region"] == "Asia-Pacific"
    assert one_lead(Region="asia-pacific")[0]["region"] == "Asia-Pacific"


def test_trailing_and_leading_space_in_industry_and_activity():
    lead_row, warnings = one_lead(
        Industry_Vertical="Technology ",
        Recent_Activity="requested live demo ",
    )
    assert lead_row["industry"] == "Technology"
    assert lead_row["recent_activity"] == "Requested Live Demo"
    assert warnings == []  # formatting noise is fixed silently
    assert one_lead(Industry_Vertical=" Finance")[0]["industry"] == "Finance"
    assert (
        one_lead(Recent_Activity="Downloaded  Whitepaper")[0]["recent_activity"]
        == "Downloaded Whitepaper"
    )


# ---------- aliases and misspellings ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("NA", "North America"),
        ("Nort America", "North America"),
        ("North  Amer", "North America"),
        ("EUR", "Europe"),
        ("Europ", "Europe"),
        ("APAC", "Asia-Pacific"),
        ("Asa-Pacific", "Asia-Pacific"),
    ],
)
def test_region_aliases(raw, expected):
    assert one_lead(Region=raw)[0]["region"] == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("ES", "Spanish"), ("de", "German"), ("english", "English"), ("German", "German")],
)
def test_language_aliases(raw, expected):
    assert one_lead(Language=raw)[0]["language"] == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MGR", "Manager"),
        ("Mgr", "Manager"),
        ("sr", "Senior"),
        (" junior", "Junior"),
        ("Jr", "Junior"),
        ("JR", "Junior"),
    ],
)
def test_seniority_aliases(raw, expected):
    assert one_rep(Seniority_Level=raw)[0]["seniority"] == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("NORTH   AMERICA Asia-Pacific ", "Asia-Pacific"), ("ASIA   PACIFICEurope", "Europe")],
)
def test_fused_region_is_read_as_trailing_region_and_logged(raw, expected):
    row, warnings = one_lead(Region=raw)
    assert row["region"] == expected
    assert "region_fused" in row["flags"]
    assert any(w["field"] == "region" and w["action"] == "mapped_suffix" for w in warnings)
    rep_row, _ = one_rep(Region=raw)
    assert rep_row["region"] == expected


@pytest.mark.parametrize("identities", [["R-1", "R-1"], ["", None]])
def test_fused_rep_regions_keep_identity_and_trace_warnings_by_record_id(identities):
    _, rows, warnings = normalize_data([], [
        rep(Rep_ID=value, Region="ASIA   PACIFICEurope") for value in identities
    ])
    assert [row["Rep_ID"] for row in rows] == [value or "" for value in identities]
    assert len({row["record_id"] for row in rows}) == len(rows)
    assert all(row["Region"] == "Europe" and "region_fused" in row["flags"] for row in rows)
    assert [warning["id"] for warning in warnings if warning["action"] == "mapped_suffix"] == [
        row["record_id"] for row in rows
    ]


def test_fused_region_policy_can_be_switched_to_unknown(monkeypatch):
    import src.normalize as module

    monkeypatch.setattr(module, "FUSED_REGION_POLICY", "unknown")
    for raw in ["NORTH   AMERICA Asia-Pacific ", "ASIA   PACIFICEurope"]:
        row, warnings = one_lead(Region=raw)
        assert row["region"] == "Unknown"
        assert "region_unmapped" in row["flags"]
        assert any(w["field"] == "region" and w["action"] == "set_unknown" for w in warnings)


def test_unrelated_region_text_is_still_unknown():
    row, _ = one_lead(Region="Antarctica")
    assert row["region"] == "Unknown"


def test_unknown_language_and_seniority_become_none_with_warning():
    row, warnings = one_lead(Language="Klingon")
    assert row["language"] == "Unknown"
    assert any(w["field"] == "language" for w in warnings)
    rep_row, rep_warnings = one_rep(Seniority_Level="Intern")
    assert rep_row["seniority"] == "Unknown"
    assert any(w["field"] == "seniority_level" or w["field"] == "seniority" for w in rep_warnings)


# ---------- industry ----------

def test_unknown_industry_is_kept_as_unknown_not_none():
    row, warnings = one_lead(Industry_Vertical="Unknown")
    assert row["industry"] == "Unknown"
    assert warnings == []


def test_unrecognized_industry_becomes_none():
    row, warnings = one_lead(Industry_Vertical="Aerospace")
    assert row["industry"] == "Unknown"
    assert any(w["field"] == "industry" for w in warnings)


# ---------- company size ----------

@pytest.mark.parametrize(
    "raw,value,status",
    [
        ("1015", 1015, "ok"),
        ("1,000", 1000, "ok"),
        ("0", 0, "ok"),
        ("5k", 5000, "interpreted"),
        ("2.5K", 2500, "interpreted"),
        ("500-1000", 500, "interpreted"),
        ("1,000 to 2,000", 1000, "interpreted"),
        ("1000-500", 500, "interpreted"),
        ("-50", None, "invalid"),
        ("lots", None, "invalid"),
        ("", None, "missing"),
        ("None", None, "missing"),
        ("null", None, "missing"),
        ("N/A", None, "missing"),
    ],
)
def test_parse_company_size(raw, value, status):
    assert parse_company_size(raw) == (value, status)


def test_missing_size_is_none_and_flagged_without_noise():
    row, warnings = one_lead(Company_Size="None")
    assert row["company_size"] is None
    assert row["company_size_label"] == "Unknown"
    assert "size_missing" in row["flags"]
    assert warnings == []  # genuinely missing values are expected, not warnings


def test_invalid_size_logs_warning_and_does_not_crash():
    row, warnings = one_lead(Company_Size="-5")
    assert row["company_size"] is None
    assert any(w["field"] == "company_size" for w in warnings)


def test_5k_is_read_as_5000_and_logged():
    row, warnings = one_lead(Company_Size="5k")
    assert row["company_size"] == 5000
    assert any(w["action"] == "parsed" for w in warnings)


def test_huge_size_kept_but_flagged():
    row, _ = one_lead(Company_Size="10000000000")
    assert row["company_size"] == 10_000_000_000
    assert "size_outlier" in row["flags"]


# ---------- VIP ----------

@pytest.mark.parametrize(
    "raw,expected",
    [("True", (True, False)), ("false", (False, False)), (" TRUE ", (True, False)),
     ("Unknown", (False, True)), ("", (False, True)), ("maybe", (False, True))],
)
def test_parse_vip(raw, expected):
    assert parse_vip(raw) == expected


def test_unknown_vip_is_not_treated_as_true():
    row, warnings = one_lead(VIP_Referral="Unknown")
    assert row["vip"] is False
    assert row["vip_unknown"] is True
    assert any(w["field"] == "vip_referral" for w in warnings)


# ---------- recent activity ----------

@pytest.mark.parametrize("raw", ["", "N/A", "Unknown", "  "])
def test_blank_activity_is_none_without_warning(raw):
    row, warnings = one_lead(Recent_Activity=raw)
    assert row["recent_activity"] == "Unknown"
    assert warnings == []


def test_unrecognized_activity_is_none_with_warning():
    row, warnings = one_lead(Recent_Activity="Waved at booth")
    assert row["recent_activity"] == "Unknown"
    assert any(w["field"] == "recent_activity" for w in warnings)


def test_unscored_known_activity_is_preserved():
    assert one_lead(Recent_Activity="Opened Marketing Email")[0]["recent_activity"] == "Opened Marketing Email"


# ---------- capacity ----------

def test_negative_max_in_seniority_range_is_sign_fixed():
    row, warnings = one_rep(Seniority_Level="Senior", Max_Capacity="-20")
    assert row["max_capacity"] == 20
    assert "max_capacity_sign_fixed" in row["flags"]
    assert any(w["action"] == "sign_fixed" for w in warnings)


@pytest.mark.parametrize(
    "seniority,raw,expected",
    [("Junior", "-45", 45), ("Manager", "-6", 6), ("Senior", "-25", 25)],
)
def test_sign_fix_respects_each_seniority_range(seniority, raw, expected):
    assert one_rep(Seniority_Level=seniority, Max_Capacity=raw)[0]["max_capacity"] == expected


@pytest.mark.parametrize(
    "seniority,raw",
    [("Senior", "-45"), ("Manager", "-20"), ("Junior", "-5"), ("Intern", "-20"), ("Senior", "-1")],
)
def test_negative_max_outside_range_falls_back_to_zero(seniority, raw):
    row, warnings = one_rep(Seniority_Level=seniority, Max_Capacity=raw)
    assert row["max_capacity"] == 0
    assert row["current_capacity"] == 0
    assert "max_capacity_invalid" in row["flags"]
    assert any(w["field"] == "max_capacity" and w["action"] == "set_zero" for w in warnings)


def test_non_numeric_capacity_does_not_crash():
    row, _ = one_rep(Max_Capacity="ten", Current_Capacity="x")
    assert (row["current_capacity"], row["max_capacity"]) == (0, 0)


def test_current_above_max_is_clamped():
    row, warnings = one_rep(Current_Capacity="9", Max_Capacity="5")
    assert (row["current_capacity"], row["max_capacity"]) == (5, 5)
    assert any(w["action"] == "clamped" for w in warnings)


def test_negative_current_becomes_zero():
    row, _ = one_rep(Current_Capacity="-3", Max_Capacity="5")
    assert row["current_capacity"] == 0


def test_valid_capacity_unchanged_and_no_warnings():
    row, warnings = one_rep(Current_Capacity="2", Max_Capacity="10")
    assert (row["current_capacity"], row["max_capacity"]) == (2, 10)
    assert warnings == []


# ---------- ids and shape ----------

def test_duplicate_lead_ids_are_kept_with_unique_record_ids():
    leads, _, warnings = normalize_data(
        [lead(Lead_ID="L-9", Company_Name="A"), lead(Lead_ID="L-9", Company_Name="B"), lead(Lead_ID="L-10")],
        [],
    )
    assert len(leads) == 3
    assert [l["record_id"] for l in leads] == ["L-9#1", "L-9#2", "L-10"]
    assert all(l["lead_id"] == raw for l, raw in zip(leads, ["L-9", "L-9", "L-10"]))
    assert len({l["record_id"] for l in leads}) == 3
    assert sum(w["action"] == "suffixed_id" for w in warnings) == 1


def test_missing_ids_get_generated_keys():
    leads, _, _ = normalize_data([lead(Lead_ID=""), lead(Lead_ID="")], [])
    assert len({l["record_id"] for l in leads}) == 2


@pytest.mark.parametrize("raw_ids", [["R-1", " R-1 ", "R-2"], ["", None, "R-2"]])
def test_normalization_preserves_rep_identity_separately_from_record_key(raw_ids):
    _, cleaned, _ = normalize_data([], [rep(Rep_ID=value) for value in raw_ids])
    expected = [value.strip() if value is not None else "" for value in raw_ids]
    assert [row["rep_id"] for row in cleaned] == expected
    assert [row["Rep_ID"] for row in cleaned] == expected
    assert len({row["record_id"] for row in cleaned}) == len(raw_ids)
    assert all("duplicate_or_missing_id" in row["flags"] for row in cleaned[:2])
    assert "duplicate_or_missing_id" not in cleaned[2]["flags"]


@pytest.mark.parametrize("entity", ["lead", "rep"])
def test_generated_record_ids_do_not_collide_with_supplied_ids(entity):
    prefix = "L" if entity == "lead" else "R"
    missing_prefix = "MISSING-LEAD" if entity == "lead" else "MISSING-REP"
    ids = [f"{prefix}-1", f"{prefix}-1", f"{prefix}-1#1", "", f"{missing_prefix}-4"]
    if entity == "lead":
        rows, _, _ = normalize_data([lead(Lead_ID=value) for value in ids], [])
    else:
        _, rows, _ = normalize_data([], [rep(Rep_ID=value) for value in ids])
    assert len({row["record_id"] for row in rows}) == len(ids)
    assert rows[2]["record_id"] == ids[2]
    assert rows[4]["record_id"] == ids[4]
    assert [row[f"{entity}_id"] for row in rows] == ids


def test_inputs_are_not_mutated():
    raw_lead, raw_rep = lead(Region=" EUROPE "), rep(Max_Capacity="-1")
    before = (dict(raw_lead), dict(raw_rep))
    normalize_data([raw_lead], [raw_rep])
    assert (raw_lead, raw_rep) == before


def test_record_count_is_preserved():
    leads, reps, _ = normalize_data([lead(Lead_ID=f"L-{i}", Region="???") for i in range(25)],
                                    [rep(Rep_ID=f"R-{i}") for i in range(4)])
    assert (len(leads), len(reps)) == (25, 4)


def test_summarize_warnings_counts():
    _, _, warnings = normalize_data([lead(VIP_Referral="Unknown"), lead(Lead_ID="L-2", VIP_Referral="")], [])
    assert summarize_warnings(warnings)[("lead", "vip_referral", "set_false")] == 2


def test_none_and_empty_inputs():
    assert normalize_data([], []) == ([], [], [])
    assert normalize_data(None, None) == ([], [], [])


# ---------- loader ----------

def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


LEAD_HEADER = "Lead_ID,Company_Name,Region,Language,Industry_Vertical,Company_Size,Recent_Activity,VIP_Referral\n"
REP_HEADER = "Rep_ID,Name,Region,Language,Industry_Vertical_Expertise,Seniority_Level,Current_Capacity,Max_Capacity\n"


def test_empty_csv_zero_bytes(tmp_path):
    assert load_leads(write(tmp_path, "l.csv", "")) == []


def test_empty_csv_header_only(tmp_path):
    assert load_reps(write(tmp_path, "r.csv", REP_HEADER)) == []


def test_empty_csvs_flow_through_normalization(tmp_path):
    leads, reps = load_data(write(tmp_path, "l.csv", LEAD_HEADER), write(tmp_path, "r.csv", REP_HEADER))
    assert normalize_data(leads, reps) == ([], [], [])


def test_missing_required_column_raises_clear_error(tmp_path):
    path = write(tmp_path, "l.csv", "Lead_ID,Region\nL-1,NA\n")
    with pytest.raises(SchemaError) as err:
        load_leads(path)
    assert "Company_Size" in str(err.value)


def test_header_matching_ignores_case_whitespace_and_bom(tmp_path):
    header = "﻿ lead_id ,COMPANY_NAME,region,Language,Industry_Vertical,Company_Size,Recent_Activity,VIP_Referral\n"
    rows = load_leads(write(tmp_path, "l.csv", header + "L-1,Acme,NA,EN,Retail,5,,False\n"))
    assert rows[0]["Lead_ID"] == "L-1" and rows[0]["Region"] == "NA"


def test_ragged_rows_and_blank_lines_do_not_crash(tmp_path):
    text = LEAD_HEADER + "L-1,Acme,NA\n\nL-2,Beta,EUR,EN,Retail,5,,False,EXTRA\n,,,,,,,\n"
    rows = load_leads(write(tmp_path, "l.csv", text))
    assert [r["Lead_ID"] for r in rows] == ["L-1", "L-2"]
    assert rows[0]["VIP_Referral"] == ""


def test_malformed_row_normalizes_without_crashing(tmp_path):
    text = LEAD_HEADER + 'L-1,"Acme, Inc",???,Klingon,Aerospace,"1,000",Waved,maybe\n'
    leads, _ = load_data(write(tmp_path, "l.csv", text), write(tmp_path, "r.csv", REP_HEADER))
    row = normalize_data(leads, [])[0][0]
    assert row["company_name"] == "Acme, Inc"
    assert row["company_size"] == 1000
    assert row["region"] == row["language"] == row["industry"] == "Unknown"


# ---------- real data (skipped if the CSVs are not in data/) ----------

def _have(*names):
    return all(os.path.exists(os.path.join(DATA, n)) for n in names)


@pytest.mark.skipif(not _have("leads_sample.csv", "reps_sample.csv"), reason="sample CSVs missing")
def test_sample_pair_loads_and_cleans():
    leads, reps = load_data(os.path.join(DATA, "leads_sample.csv"), os.path.join(DATA, "reps_sample.csv"))
    clean_leads, clean_reps, warnings = normalize_data(leads, reps)
    assert (len(clean_leads), len(clean_reps)) == (100, 10)
    assert len({l["record_id"] for l in clean_leads}) == 100
    assert {l["language"] for l in clean_leads} <= {"English", "Spanish", "German"}
    assert {l["region"] for l in clean_leads} <= {"North America", "Europe", "Asia-Pacific", "Unknown"}
    assert {r["seniority"] for r in clean_reps} <= {"Junior", "Senior", "Manager"}
    assert all(0 <= r["current_capacity"] <= r["max_capacity"] for r in clean_reps)
    r9 = next(r for r in clean_reps if r["rep_id"] == "R-9")
    assert r9["max_capacity"] == 20  # raw -20, Senior range 20-25
    assert any(w["entity"] == "rep" and w["id"] == "R-9" and w["action"] == "sign_fixed" for w in warnings)


@pytest.mark.skipif(not _have("leads_scale.csv", "reps_scale.csv"), reason="scale CSVs missing")
def test_scale_pair_loads_and_cleans_without_losing_records():
    leads, reps = load_data(os.path.join(DATA, "leads_scale.csv"), os.path.join(DATA, "reps_scale.csv"))
    clean_leads, clean_reps, _ = normalize_data(leads, reps)
    assert (len(clean_leads), len(clean_reps)) == (50000, 1600)
    assert len({l["record_id"] for l in clean_leads}) == 50000
    assert all(r["seniority"] != "Unknown" for r in clean_reps)
    assert all(r["max_capacity"] > 0 for r in clean_reps)  # all 94 negatives are repairable
    assert all(0 <= r["current_capacity"] <= r["max_capacity"] for r in clean_reps)


# ---------- compatibility with scoring.py ----------

def test_cleaned_leads_carry_original_column_names():
    row, _ = one_lead(VIP_Referral="True", Company_Size="1,000", Region=" EUROPE ")
    assert row["VIP_Referral"] is True and row["vip"] is True
    assert row["Company_Size"] == 1000 == row["company_size"]
    assert row["Region"] == "Europe" == row["region"]
    for original in ("Lead_ID", "Company_Name", "Language", "Industry_Vertical", "Recent_Activity"):
        assert original in row


def test_range_size_uses_lower_end_and_is_logged():
    row, warnings = one_lead(Company_Size="500-1000")
    assert row["company_size"] == 500
    assert "size_interpreted" in row["flags"]
    assert any(w["field"] == "company_size" for w in warnings)


def test_cleaned_reps_carry_original_column_names():
    row, _ = one_rep(Seniority_Level="MGR", Max_Capacity="6", Region="Europ")
    assert row["Seniority_Level"] == "Manager" == row["seniority"]
    assert row["Max_Capacity"] == 6 == row["max_capacity"]
    assert row["Region"] == "Europe" == row["region"]
    for original in ("Rep_ID", "Name", "Language", "Industry_Vertical_Expertise", "Current_Capacity"):
        assert original in row
