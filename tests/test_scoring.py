import math
import pytest
import src.scoring as scoring
from src.scoring import (
    score_lead, score_leads, sort_for_routing, parse_company_size, parse_vip,
    tier_for,
)


def lead(**kw):
    base = {"VIP_Referral": False, "Company_Size": 50,
            "Recent_Activity": None, "Industry_Vertical": "Retail"}
    base.update(kw)
    return base


# ---- VIP override --------------------------------------------------------
@pytest.mark.parametrize("v", [True, "True", "true", " TRUE ", "yes", 1])
def test_vip_forces_critical_100(v):
    r = score_lead(lead(VIP_Referral=v, Company_Size=1, Industry_Vertical="Retail"))
    assert (r["score"], r["priority"], r["is_vip"]) == (100, "CRITICAL", True)


def test_vip_bypasses_matrix_even_with_garbage_fields():
    r = score_lead({"VIP_Referral": True, "Company_Size": "???"})
    assert r["score"] == 100 and r["priority"] == "CRITICAL"


@pytest.mark.parametrize("v", ["Unknown", None, "", float("nan"), "False", False, "maybe"])
def test_non_vip_values(v):
    assert score_lead(lead(VIP_Referral=v))["is_vip"] is False


def test_unknown_vip_is_flagged():
    assert "vip_unknown_treated_as_false" in score_lead(lead(VIP_Referral="Unknown"))["fallbacks"]


# ---- Company size --------------------------------------------------------
@pytest.mark.parametrize("size,pts", [
    (1, 0), (99, 0), (100, 30), (999, 30), (1000, 50), (10**10, 50),
])
def test_size_boundaries(size, pts):
    assert score_lead(lead(Company_Size=size))["size_points"] == pts


@pytest.mark.parametrize("raw,expected", [
    ("1,000", 1000), ("5k", 5000), ("5K", 5000), ("500-1000", 500),
    ("250.0", 250), (" 75 ", 75), ("10,000+", 10000), (42, 42), (42.0, 42),
])
def test_size_parsing(raw, expected):
    assert parse_company_size(raw) == expected


@pytest.mark.parametrize("raw", [None, "", float("nan"), "Unknown", "abc", 0, -5, "-3",
                                 float("inf"), True])
def test_size_invalid_or_missing_returns_none(raw):
    assert parse_company_size(raw) is None


def test_missing_size_gets_20_not_zero():
    r = score_lead(lead(Company_Size=None))
    assert r["size_points"] == 20
    assert "company_size_missing_default_20" in r["fallbacks"]


def test_invalid_size_gets_20_and_flag():
    r = score_lead(lead(Company_Size="lots"))
    assert r["size_points"] == 20
    assert "company_size_invalid_default_20" in r["fallbacks"]


# ---- Activity ------------------------------------------------------------
@pytest.mark.parametrize("act,pts", [
    ("Requested Live Demo", 35), ("requested live demo ", 35), ("Contact Sales", 35),
    (" Contact Sales", 35), ("Attended Webinar", 25), ("Downloaded Whitepaper", 15),
    ("Downloaded  Whitepaper", 15), ("Visited Pricing Page", 5),
    ("Started Free Trial", 0), ("Opened Marketing Email", 0), ("Unknown", 0),
    (None, 0), (float("nan"), 0), ("", 0),
])
def test_activity_points(act, pts):
    assert score_lead(lead(Recent_Activity=act))["activity_points"] == pts


def test_unmapped_activity_flagged():
    assert "activity_unmapped_0" in score_lead(lead(Recent_Activity="Subscribed to Blog"))["fallbacks"]


# ---- Industry ------------------------------------------------------------
@pytest.mark.parametrize("ind,pts", [
    ("Technology", 15), ("Technology ", 15), (" finance", 10), ("HEALTHCARE", 10),
    ("Manufacturing", 0), ("Retail", 0), ("Unknown", 0), (None, 0), ("Biotech", 0),
])
def test_industry_points(ind, pts):
    assert score_lead(lead(Industry_Vertical=ind))["industry_points"] == pts


# ---- Tiers ---------------------------------------------------------------
@pytest.mark.parametrize("s,tier", [
    (0, "LOW"), (39, "LOW"), (40, "MEDIUM"), (59, "MEDIUM"),
    (60, "HIGH"), (84, "HIGH"), (85, "CRITICAL"), (100, "CRITICAL"),
])
def test_tier_boundaries(s, tier):
    assert tier_for(s) == tier


def test_max_non_vip_score_is_critical():
    r = score_lead(lead(Company_Size=5000, Recent_Activity="Contact Sales",
                        Industry_Vertical="Technology"))
    assert r["score"] == 100 and r["priority"] == "CRITICAL" and not r["is_vip"]


def test_worked_example():
    # Mid-market (30) + webinar (25) + healthcare (10) = 65 -> High
    r = score_lead(lead(Company_Size=500, Recent_Activity="Attended Webinar",
                        Industry_Vertical="Healthcare"))
    assert (r["score"], r["priority"]) == (65, "HIGH")


# ---- Resilience ----------------------------------------------------------
def test_empty_dict_does_not_crash():
    r = score_lead({})
    assert r["priority"] == "LOW" and r["score"] == 20


def test_batch_survives_bad_records():
    out = score_leads([lead(), {}, {"Company_Size": object()}, lead(VIP_Referral=True)])
    assert len(out) == 4 and out[3]["priority"] == "CRITICAL"


def test_original_fields_preserved():
    out = score_leads([{"Lead_ID": "L-1", "Company_Name": "X"}])
    assert out[0]["Lead_ID"] == "L-1" and out[0]["Company_Name"] == "X"


def test_duplicate_lead_ids_not_collapsed():
    out = score_leads([{"Lead_ID": "L-1"}, {"Lead_ID": "L-1"}])
    assert len(out) == 2


# ---- Ordering ------------------------------------------------------------
def test_sort_critical_first_then_score_then_id():
    rows = score_leads([
        {"Lead_ID": "B", "Company_Size": 5000, "Recent_Activity": "Contact Sales",
         "Industry_Vertical": "Technology"},          # 100 non-VIP
        {"Lead_ID": "A", "VIP_Referral": True},        # 100 VIP
        {"Lead_ID": "C", "Company_Size": 5, "Recent_Activity": None},  # low
        {"Lead_ID": "D", "Company_Size": 500, "Recent_Activity": "Attended Webinar"},  # 55
    ])
    assert [r["Lead_ID"] for r in sort_for_routing(rows)] == ["A", "B", "D", "C"]


# ---- Scale ---------------------------------------------------------------
def test_50k_scores_fast():
    import time
    rows = [lead(Company_Size="5k", Recent_Activity="requested live demo ")
            for _ in range(50_000)]
    t = time.perf_counter()
    score_leads(rows)
    assert time.perf_counter() - t < 5


# ===========================================================================
# Added: malformed records, ranges, huge numbers, industry fallbacks,
# output contract, boundaries, sorting robustness
# ===========================================================================
KEYS = {"score", "priority", "is_vip", "size_points", "activity_points",
        "industry_points", "company_size_parsed", "fallbacks", "invalid_record"}


# ---- malformed records ---------------------------------------------------
@pytest.mark.parametrize("bad", [None, "a string", 42, 3.14, [1, 2], (1,), object()])
def test_score_lead_non_record_is_safe(bad):
    r = score_lead(bad)
    assert r["invalid_record"] is True
    assert (r["score"], r["priority"]) == (0, "LOW")
    assert r["fallbacks"][0].startswith("invalid_record:")


def test_score_leads_keeps_position_and_never_drops_bad_records():
    good = {"Lead_ID": "L-1", "VIP_Referral": True}
    out = score_leads([None, good, "oops", 7, {}])
    assert len(out) == 5
    assert out[1]["Lead_ID"] == "L-1" and out[1]["priority"] == "CRITICAL"
    assert [o["invalid_record"] for o in out] == [True, False, True, True, False]
    assert out[0]["invalid_record_repr"] == "None"


def test_score_leads_handles_none_and_empty_input():
    assert score_leads(None) == [] and score_leads([]) == []


def test_score_leads_accepts_generator():
    assert len(score_leads(x for x in [{}, {}])) == 2


# ---- output contract (what routing relies on) ---------------------------
def test_score_lead_always_returns_same_keys():
    for rec in [{}, lead(), {"VIP_Referral": True}, None, "x"]:
        assert set(score_lead(rec)) == KEYS


def test_routing_fields_preserved_and_guaranteed():
    raw = {"Lead_ID": "L-9", "Region": "Europe", "Language": "German",
           "Company_Name": "Acme", "Industry_Vertical": "Finance"}
    out = score_leads([raw])[0]
    assert (out["Lead_ID"], out["Region"], out["Language"], out["Company_Name"]) == \
        ("L-9", "Europe", "German", "Acme")
    # missing routing fields still exist (None) so routing never hits KeyError
    bare = score_leads([{}, None])
    for row in bare:
        assert {"Lead_ID", "Region", "Language"} <= set(row)


def test_input_records_are_not_mutated():
    raw = {"Lead_ID": "L-1", "Company_Size": "5k"}
    snapshot = dict(raw)
    score_leads([raw])
    assert raw == snapshot


# ---- company-size ranges: explicit policy --------------------------------
def test_range_default_policy_is_lower_bound_and_recorded():
    r = score_lead(lead(Company_Size="500-1000"))
    assert r["company_size_parsed"] == 500 and r["size_points"] == 30
    assert "company_size_range_lower_used" in r["fallbacks"]


@pytest.mark.parametrize("policy,expected,pts", [
    ("lower", 500, 30), ("midpoint", 750, 30), ("upper", 1000, 50),
    ("nonsense", 500, 30),                       # unknown policy -> safest
])
def test_range_policies(monkeypatch, policy, expected, pts):
    monkeypatch.setattr(scoring, "RANGE_POLICY", policy)
    r = score_lead(lead(Company_Size="500-1000"))
    assert r["company_size_parsed"] == expected and r["size_points"] == pts


def test_reversed_and_bad_ranges():
    assert parse_company_size("1000-500") == 500
    assert parse_company_size("0-50") is None        # lower end invalid under "lower"
    assert parse_company_size("a-b") is None


# ---- huge / hostile numeric input ---------------------------------------
@pytest.mark.parametrize("raw", [
    10**400, "9" * 5000, float("1e308") * 10, float("inf"), 10**10 + 1,
    "1" * 400, "1e999",
])
def test_huge_sizes_do_not_crash_and_fall_back(raw):
    assert parse_company_size(raw) is None
    r = score_lead(lead(Company_Size=raw))
    assert r["size_points"] == 20 and "company_size_invalid_default_20" in r["fallbacks"]


def test_largest_dataset_value_still_enterprise():
    assert score_lead(lead(Company_Size="10000000000"))["size_points"] == 50


def test_object_with_broken_str_does_not_crash():
    class Bad:
        def __str__(self):
            raise RuntimeError("boom")
    r = score_lead(lead(Company_Size=Bad(), Recent_Activity=Bad(), Industry_Vertical=Bad()))
    assert r["priority"] == "LOW"


# ---- industry fallbacks --------------------------------------------------
def test_unmapped_industry_is_recorded():
    r = score_lead(lead(Industry_Vertical="Biotech"))
    assert r["industry_points"] == 0 and "industry_unmapped_0" in r["fallbacks"]


@pytest.mark.parametrize("v", [None, "", "Unknown", float("nan")])
def test_missing_industry_is_recorded(v):
    assert "industry_missing_0" in score_lead(lead(Industry_Vertical=v))["fallbacks"]


def test_mapped_industry_has_no_industry_flag():
    f = score_lead(lead(Industry_Vertical=" Technology "))["fallbacks"]
    assert not any(x.startswith("industry_") for x in f)


# ---- priority boundaries built from real inputs --------------------------
# Real leads engineered to land exactly on 39/40/59/60/84/85.
@pytest.mark.parametrize("size,act,ind,score,tier", [
    (None, "Visited Pricing Page", "Retail", 25, "LOW"),                 # sanity
    (50, "Attended Webinar", "Healthcare", 35, "LOW"),
    (500, "Visited Pricing Page", "Retail", 35, "LOW"),
    (5000, None, "Retail", 50, "MEDIUM"),
    (500, "Downloaded Whitepaper", "Healthcare", 55, "MEDIUM"),
    (500, "Attended Webinar", "Retail", 55, "MEDIUM"),
    (500, "Attended Webinar", "Healthcare", 65, "HIGH"),
    (5000, "Visited Pricing Page", "Retail", 55, "MEDIUM"),
    (5000, "Downloaded Whitepaper", "Retail", 65, "HIGH"),
    (5000, "Attended Webinar", "Retail", 75, "HIGH"),
    (5000, "Attended Webinar", "Healthcare", 85, "CRITICAL"),
    (5000, "Contact Sales", "Retail", 85, "CRITICAL"),
    (5000, "Contact Sales", "Technology", 100, "CRITICAL"),
])
def test_real_leads_land_in_expected_tier(size, act, ind, score, tier):
    r = score_lead(lead(Company_Size=size, Recent_Activity=act, Industry_Vertical=ind))
    assert (r["score"], r["priority"]) == (score, tier)


@pytest.mark.parametrize("s,tier", [
    (38, "LOW"), (39, "LOW"), (40, "MEDIUM"), (41, "MEDIUM"),
    (58, "MEDIUM"), (59, "MEDIUM"), (60, "HIGH"), (61, "HIGH"),
    (83, "HIGH"), (84, "HIGH"), (85, "CRITICAL"), (86, "CRITICAL"),
])
def test_priority_boundaries_all(s, tier):
    assert tier_for(s) == tier


def test_priorities_are_uppercase_everywhere():
    rows = score_leads([lead(), {"VIP_Referral": True}, None, {}])
    assert {r["priority"] for r in rows} <= {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    assert set(scoring.TIER_RANK) == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


# ---- sorting robustness --------------------------------------------------
def test_sort_critical_always_first_even_if_score_lower_than_others():
    rows = [
        {"Lead_ID": "H", "priority": "HIGH", "score": 84},
        {"Lead_ID": "C", "priority": "CRITICAL", "score": 85},
    ]
    assert [r["Lead_ID"] for r in sort_for_routing(rows)] == ["C", "H"]


def test_sort_vip_before_nonvip_at_equal_score_100():
    rows = score_leads([
        {"Lead_ID": "A-nonvip", "Company_Size": 5000, "Recent_Activity": "Contact Sales",
         "Industry_Vertical": "Technology"},
        {"Lead_ID": "Z-vip", "VIP_Referral": True},
    ])
    assert rows[0]["score"] == rows[1]["score"] == 100      # the tie is real
    assert [r["Lead_ID"] for r in sort_for_routing(rows)] == ["Z-vip", "A-nonvip"]


def test_sort_never_crashes_on_junk():
    junk = [None, "x", 5, {}, {"priority": None, "score": None},
            {"priority": "nope", "score": "abc"}, {"score": float("nan")},
            {"priority": "HIGH", "score": 10**400}, {"priority": ["list"]},
            {"Lead_ID": object(), "priority": "LOW", "score": 1}]
    out = sort_for_routing(junk)
    assert len(out) == len(junk)


def test_sort_missing_priority_derived_from_score():
    rows = [{"Lead_ID": "low", "score": 10}, {"Lead_ID": "crit", "score": 90},
            {"Lead_ID": "mid", "score": 50}]
    assert [r["Lead_ID"] for r in sort_for_routing(rows)] == ["crit", "mid", "low"]


def test_sort_lowercase_priority_and_string_score_tolerated():
    rows = [{"Lead_ID": "b", "priority": "high", "score": "70"},
            {"Lead_ID": "a", "priority": "critical", "score": "90"}]
    assert [r["Lead_ID"] for r in sort_for_routing(rows)] == ["a", "b"]


def test_sort_unusable_records_go_last_and_keep_order():
    rows = [None, {"Lead_ID": "ok", "priority": "LOW", "score": 0}, "bad", {}]
    out = sort_for_routing(rows)
    assert out[0]["Lead_ID"] == "ok"
    assert out[1] == {} and out[2] is None and out[3] == "bad"


def test_sort_is_deterministic_with_duplicate_ids():
    rows = score_leads([{"Lead_ID": "L-1", "Company_Name": "first"},
                        {"Lead_ID": "L-1", "Company_Name": "second"}])
    assert sort_for_routing(rows) == sort_for_routing(list(rows))
    assert [r["Company_Name"] for r in sort_for_routing(rows)] == ["first", "second"]


def test_sort_does_not_mutate_or_drop():
    rows = score_leads([lead(), {"VIP_Referral": True}])
    before = list(rows)
    out = sort_for_routing(rows)
    assert rows == before and len(out) == 2


def test_sort_handles_none_input():
    assert sort_for_routing(None) == []