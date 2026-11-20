"""Routing contract and business-rule tests; no CSV or dashboard dependencies."""
from collections import Counter
from copy import deepcopy
from itertools import product
import platform
import time

import pytest

from src.routing import route_leads


def make_lead(lead_id="L-1", score=20, **changes):
    priority = "CRITICAL" if score >= 85 else "HIGH" if score >= 60 else "MEDIUM" if score >= 40 else "LOW"
    return {
        "Lead_ID": lead_id, "Region": "Europe", "Language": "English",
        "Industry_Vertical": "Technology", "score": score,
        "priority": priority, "is_vip": False, **changes,
    }


def make_rep(rep_id="R-1", seniority="Junior", capacity=10, current=0, **changes):
    return {
        "Rep_ID": rep_id, "Region": "Europe", "Language": "English",
        "Industry_Vertical_Expertise": "Technology", "Seniority_Level": seniority,
        "Current_Capacity": current, "Max_Capacity": capacity, **changes,
    }


def assert_invariants(result, leads, reps):
    outcomes = result["assignments"] + result["overflow"]
    assert len(outcomes) == len(leads)
    assert sorted(row["source_index"] for row in outcomes) == list(range(len(leads)))
    assert all(row["rep_id"] is None and row["reason"] for row in result["overflow"])
    assert all(row["assignment_status"] == "Manager Review" for row in result["overflow"])
    counts = Counter(row["rep_id"] for row in result["assignments"])
    excluded = {warning["source_index"] for warning in result["rep_warnings"]}
    for index, (before, after) in enumerate(zip(reps, result["updated_reps"])):
        if index in excluded:
            assert before == after
            continue
        assert after["Current_Capacity"] == before["Current_Capacity"] + counts[before["Rep_ID"]]
        assert after["Current_Capacity"] <= before["Max_Capacity"]
    by_id = {rep["Rep_ID"]: rep for i, rep in enumerate(reps) if i not in excluded}
    for row in result["assignments"]:
        assert row["assignment_status"] == "Assigned" and row["reason"] is None
        rep = by_id[row["rep_id"]]
        for lead_field, rep_field in [("Region", "Region"), ("Language", "Language"),
                                      ("Industry_Vertical", "Industry_Vertical_Expertise")]:
            assert row[lead_field].strip().casefold() == rep[rep_field].strip().casefold()
        if row["priority"] == "CRITICAL":
            assert rep["Seniority_Level"].strip().casefold() in {"senior", "manager"}
    metrics = result["metrics"]
    assert metrics["total_leads"] == len(leads)
    assert metrics["assigned_count"] == len(result["assignments"])
    assert metrics["manager_review_count"] == len(result["overflow"])
    assert metrics["review_counts_by_reason"] == dict(Counter(row["reason"] for row in result["overflow"]))
    assert metrics["excluded_rep_count"] == len(excluded)


def test_one_matching_rep_and_public_contract():
    leads = [make_lead(Company_Name="Acme", fallbacks=["vip_unknown_treated_as_false"])]
    reps = [make_rep()]
    result = route_leads(leads, reps)
    assert set(result) == {"assignments", "updated_reps", "overflow", "metrics", "rep_warnings"}
    assert result["assignments"][0] == {
        **leads[0], "source_index": 0, "rep_id": "R-1",
        "assignment_status": "Assigned", "reason": None,
    }
    assert result["metrics"]["assignment_rate"] == 1.0
    assert_invariants(result, leads, reps)


@pytest.mark.parametrize("lead_field,value", [
    ("Region", "North America"), ("Language", "Spanish"), ("Industry_Vertical", "Finance"),
])
def test_each_skill_must_match(lead_field, value):
    result = route_leads([make_lead(**{lead_field: value})], [make_rep()])
    assert result["overflow"][0]["reason"] == "No matching representative"


def test_case_and_outer_whitespace_are_accepted_without_changing_fields():
    lead = make_lead(score=85, Region=" EUROPE ", Language="english", Industry_Vertical="TECHNOLOGY")
    rep = make_rep(seniority=" sENiOR ", Region="europe", Language=" English ")
    result = route_leads([lead], [rep])
    assert result["assignments"][0]["Region"] == " EUROPE "
    assert_invariants(result, [lead], [rep])


@pytest.mark.parametrize("score", [85, 100])
def test_critical_prefers_senior_then_manager_never_junior(score):
    reps = [make_rep("A-manager", "Manager", 1), make_rep("B-junior", "Junior", 10),
            make_rep("Z-senior", "Senior", 1)]
    leads = [make_lead(f"L-{i}", score, is_vip=score == 100) for i in range(3)]
    result = route_leads(leads, reps)
    assert [row["rep_id"] for row in result["assignments"]] == ["Z-senior", "A-manager"]
    assert result["overflow"][0]["reason"] == "Eligible representatives at capacity"
    assert_invariants(result, leads, reps)


@pytest.mark.parametrize("seniors", [[], [make_rep("S", "Senior", 2, 2)]])
def test_manager_used_when_seniors_absent_or_initially_full(seniors):
    result = route_leads([make_lead(score=85)], seniors + [make_rep("M", "Manager")])
    assert result["assignments"][0]["rep_id"] == "M"


def test_critical_with_juniors_only_has_distinct_reason():
    result = route_leads([make_lead(score=100, is_vip=True)], [make_rep()])
    assert result["overflow"][0]["reason"] == "No eligible Senior or Manager"


def test_critical_runs_before_low_and_combined_pool_uses_remaining_capacity():
    leads = [make_lead("A-low"), make_lead("Z-critical", 85)]
    reps = [make_rep("A-senior", "Senior", 1), make_rep("B-junior", "Junior", 1)]
    result = route_leads(leads, reps)
    assert [(row["Lead_ID"], row["rep_id"]) for row in result["assignments"]] == [
        ("Z-critical", "A-senior"), ("A-low", "B-junior"),
    ]
    assert_invariants(result, leads, reps)


def test_round_robin_wraparound_sorted_rep_ids_and_equal_seniorities():
    reps = [make_rep("C", "Manager"), make_rep("A", "Junior"), make_rep("B", "Senior")]
    leads = [make_lead(f"L-{i}", 60) for i in range(8)]
    result = route_leads(leads, reps)
    assert [row["rep_id"] for row in result["assignments"]] == ["A", "B", "C", "A", "B", "C", "A", "B"]
    permuted = route_leads(leads, list(reversed(reps)))
    assert permuted == {**result, "updated_reps": list(reversed(result["updated_reps"]))}
    assert_invariants(result, leads, reps)


def test_round_robin_skips_full_reps_and_respects_existing_load():
    reps = [make_rep("A", capacity=3, current=2), make_rep("B", capacity=3),
            make_rep("C", capacity=5, current=5)]
    leads = [make_lead(f"L-{i}") for i in range(6)]
    result = route_leads(leads, reps)
    assert [row["rep_id"] for row in result["assignments"]] == ["A", "B", "B", "B"]
    assert len(result["overflow"]) == 2
    assert_invariants(result, leads, reps)


@pytest.mark.parametrize("seniority", ["Senior", "Manager"])
def test_critical_round_robin_inside_seniority_pool(seniority):
    reps = [make_rep("B", seniority), make_rep("A", seniority)]
    result = route_leads([make_lead(str(i), 85) for i in range(5)], reps)
    assert [row["rep_id"] for row in result["assignments"]] == ["A", "B", "A", "B", "A"]


def test_skill_groups_rotate_independently():
    reps = [make_rep("A"), make_rep("B"), make_rep("C", Language="Spanish"), make_rep("D", Language="Spanish")]
    leads = [make_lead(str(i), Language="English" if i % 2 == 0 else "Spanish") for i in range(6)]
    result = route_leads(leads, reps)
    assert [row["rep_id"] for row in result["assignments"]] == ["A", "C", "B", "D", "A", "C"]
    assert_invariants(result, leads, reps)


def test_order_priority_score_vip_lexicographic_id_and_original_position():
    leads = [make_lead("low", 0), make_lead("H", 60), make_lead("M", 59),
             make_lead("A", 100), make_lead("Z", 100, is_vip=True), make_lead("H2", 84),
             make_lead("L-2", 85), make_lead("L-10", 85), make_lead("L-10", 85)]
    result = route_leads(leads, [make_rep(seniority="Senior", capacity=20)])
    assert [row["source_index"] for row in result["assignments"]] == [4, 3, 7, 8, 6, 5, 1, 2, 0]


@pytest.mark.parametrize("field", ["Region", "Language", "Industry_Vertical"])
@pytest.mark.parametrize("value", [None, "", "Unknown", "n/a", 123, ["Europe"], float("nan")])
def test_unresolved_lead_fields_never_match_even_identical_rep_values(field, value):
    rep_field = "Industry_Vertical_Expertise" if field == "Industry_Vertical" else field
    result = route_leads([make_lead(**{field: value})], [make_rep(**{rep_field: value})])
    assert result["overflow"][0]["reason"] == "Missing or invalid routing fields"
    assert result["rep_warnings"][0]["reason"] == "Missing or invalid routing fields"


@pytest.mark.parametrize("field,value", [
    ("Region", "APAC"), ("Region", "ASIA   PACIFICEurope"), ("Region", "Europ"),
    ("Language", "EN"), ("Industry_Vertical", "Tech"),
])
def test_aliases_and_ambiguous_values_are_left_to_normalization(field, value):
    result = route_leads([make_lead(**{field: value})], [make_rep()])
    assert result["overflow"][0]["reason"] == "Missing or invalid routing fields"


@pytest.mark.parametrize("field", ["Region", "Language", "Industry_Vertical"])
def test_absent_routing_field_goes_to_review(field):
    lead = make_lead()
    del lead[field]
    assert route_leads([lead], [make_rep()])["overflow"][0]["reason"] == "Missing or invalid routing fields"


@pytest.mark.parametrize("current,maximum", [
    (-1, 10), (0, -1), (11, 10), (None, 10), (0, None), ("0", 10), (0, "10"),
    (0.0, 10), (0, 10.0), (False, 10), (0, True), (float("nan"), 10), (0, float("inf")),
])
def test_invalid_capacities_excluded_without_changing_rep(current, maximum):
    rep = make_rep(current=current, capacity=maximum)
    result = route_leads([make_lead()], [rep])
    assert not result["assignments"]
    assert result["updated_reps"][0] == rep
    assert result["rep_warnings"] == [{"source_index": 0, "rep_id": "R-1", "reason": "Invalid representative capacity"}]


@pytest.mark.parametrize("field", ["Current_Capacity", "Max_Capacity"])
def test_missing_capacity_is_invalid(field):
    rep = make_rep()
    del rep[field]
    result = route_leads([make_lead()], [rep])
    assert result["rep_warnings"][0]["reason"] == "Invalid representative capacity"


def test_zero_capacity_is_valid_but_full():
    result = route_leads([make_lead()], [make_rep(capacity=0)])
    assert result["rep_warnings"] == []
    assert result["overflow"][0]["reason"] == "Eligible representatives at capacity"


@pytest.mark.parametrize("seniority", [None, "", "Unknown", "sr", "MGR", 5])
def test_unresolved_seniority_excluded(seniority):
    result = route_leads([make_lead()], [make_rep(seniority=seniority)])
    assert result["rep_warnings"][0]["reason"] == "Missing or invalid seniority"


@pytest.mark.parametrize("identity", [None, "", "  ", 1])
def test_invalid_rep_id_excluded(identity):
    result = route_leads([make_lead()], [make_rep(identity)])
    assert result["rep_warnings"][0]["reason"] == "Missing or invalid Rep_ID"


def test_every_duplicate_rep_id_is_excluded_even_with_outer_whitespace():
    reps = [make_rep("R-1"), make_rep(" R-1 "), make_rep("R-2")]
    result = route_leads([make_lead()], reps)
    assert result["assignments"][0]["rep_id"] == "R-2"
    assert [row["source_index"] for row in result["rep_warnings"]] == [0, 1]
    assert all(row["reason"] == "Duplicate Rep_ID" for row in result["rep_warnings"])
    assert_invariants(result, [make_lead()], reps)


@pytest.mark.parametrize("changes", [
    {"score": None}, {"score": "85"}, {"score": True}, {"score": 85.0}, {"score": -1},
    {"score": 101}, {"score": float("nan")}, {"score": float("inf")},
    {"priority": None}, {"priority": "low"}, {"priority": "CRITICAL"}, {"priority": []},
    {"is_vip": "False"}, {"is_vip": None}, {"is_vip": 0}, {"is_vip": True},
    {"score": 100, "priority": "LOW", "is_vip": True},
])
def test_bad_scoring_metadata_goes_to_review(changes):
    lead = {**make_lead(), **changes}
    result = route_leads([lead], [make_rep(seniority="Senior")])
    assert result["overflow"][0]["reason"] == "Invalid scoring metadata"
    assert result["updated_reps"][0]["Current_Capacity"] == 0


@pytest.mark.parametrize("field", ["score", "priority", "is_vip"])
def test_missing_scoring_field_goes_to_review(field):
    lead = make_lead()
    del lead[field]
    assert route_leads([lead], [make_rep()])["overflow"][0]["reason"] == "Invalid scoring metadata"


@pytest.mark.parametrize("score", [0, 39, 40, 59, 60, 84, 85, 100])
def test_valid_scoring_boundaries_route(score):
    assert len(route_leads([make_lead(score=score)], [make_rep(seniority="Senior")])["assignments"]) == 1


@pytest.mark.parametrize("bad", [None, "bad", 42, [], {"invalid_record": True}])
def test_malformed_lead_keeps_traceable_outcome(bad):
    result = route_leads([bad, make_lead()], [make_rep()])
    assert result["overflow"][0]["source_index"] == 0
    assert result["overflow"][0]["reason"] == "Invalid lead record"
    assert result["assignments"][0]["source_index"] == 1


def test_malformed_rep_is_preserved_and_does_not_abort_batch():
    result = route_leads([make_lead()], [None, make_rep()])
    assert result["rep_warnings"][0] == {"source_index": 0, "rep_id": None, "reason": "Invalid representative record"}
    assert result["updated_reps"][0]["invalid_record_repr"] == "None"
    assert len(result["assignments"]) == 1


def test_duplicate_and_missing_lead_ids_are_preserved():
    leads = [make_lead("same"), make_lead("same"), make_lead(None), make_lead()]
    del leads[-1]["Lead_ID"]
    reps = [make_rep(capacity=2)]
    result = route_leads(leads, reps)
    assert_invariants(result, leads, reps)
    assert [row["source_index"] for row in result["assignments"]] == [2, 3]
    assert [row["source_index"] for row in result["overflow"]] == [0, 1]


def test_inputs_unchanged_results_independent_and_repeat_run_resets():
    leads = [make_lead("low", fallbacks=["vip_unknown_treated_as_false"]), make_lead("vip", 100, is_vip=True)]
    reps = [make_rep("S", "Senior", 2, 1), make_rep("J", "Junior", 2)]
    before = deepcopy((leads, reps))
    first = route_leads(leads, reps)
    second = route_leads(leads, reps)
    assert (leads, reps) == before
    assert first == second
    first["updated_reps"][0]["Current_Capacity"] = 999
    first["assignments"][0]["rep_id"] = "changed"
    assert route_leads(leads, reps) == second


def test_explicit_updated_capacity_input_continues_from_that_capacity():
    reps = [make_rep(capacity=1)]
    first = route_leads([make_lead()], reps)
    continued = route_leads([make_lead("next")], first["updated_reps"])
    assert continued["overflow"][0]["reason"] == "Eligible representatives at capacity"
    assert route_leads([make_lead()], reps) == first


def test_empty_inputs_and_no_reps():
    empty = route_leads([], [])
    assert empty["metrics"] == {
        "total_leads": 0, "assigned_count": 0, "manager_review_count": 0,
        "assignment_rate": 0.0, "review_counts_by_reason": {}, "excluded_rep_count": 0,
    }
    assert empty["assignments"] == empty["overflow"] == empty["updated_reps"] == empty["rep_warnings"] == []
    assert route_leads([], [make_rep()])["updated_reps"] == [make_rep()]
    result = route_leads([make_lead()], [])
    assert result["overflow"][0]["reason"] == "No matching representative"


def test_all_canonical_skills_are_supported():
    for region, language, industry in product(
        ["North America", "Europe", "Asia-Pacific"], ["English", "German", "Spanish"],
        ["Technology", "Healthcare", "Finance", "Manufacturing", "Retail"],
    ):
        lead = make_lead(Region=region, Language=language, Industry_Vertical=industry)
        rep = make_rep(Region=region, Language=language, Industry_Vertical_Expertise=industry)
        assert len(route_leads([lead], [rep])["assignments"]) == 1


def test_scoring_module_compatibility_when_available():
    scoring = pytest.importorskip("src.scoring", reason="Scoring PR #6 is not merged into this branch yet")
    leads = [
        {**make_lead("nonvip"), "Company_Size": 1000, "Recent_Activity": "Contact Sales", "VIP_Referral": False},
        {**make_lead("vip"), "Company_Size": 1, "VIP_Referral": True},
        {**make_lead("low"), "Company_Size": 1, "VIP_Referral": False},
    ]
    scored = scoring.score_leads(leads)
    result = route_leads(scored, [make_rep(seniority="Senior")])
    assert [row["Lead_ID"] for row in result["assignments"]] == [row["Lead_ID"] for row in scoring.sort_for_routing(scored)]
    assert len(result["assignments"]) == 3
    assert_invariants(result, scored, [make_rep(seniority="Senior")])


def scale_inputs():
    """Reproducible synthetic fixture, deliberately distinct from supplied CSVs."""
    skills = list(product(
        ["North America", "Europe", "Asia-Pacific"], ["English", "German", "Spanish"],
        ["Technology", "Healthcare", "Finance", "Manufacturing", "Retail"],
    ))
    reps = []
    for i in range(1600):
        region, language, industry = skills[i % len(skills)]
        seniority, maximum = [("Junior", 50), ("Senior", 25), ("Manager", 10)][(i // len(skills)) % 3]
        reps.append(make_rep(f"R-{i:04d}", seniority, maximum, i % 4,
                             Region=region, Language=language, Industry_Vertical_Expertise=industry))
    leads = []
    for i in range(50_000):
        region, language, industry = skills[i % len(skills)]
        score = [100, 85, 84, 60, 59, 40, 39, 0][i % 8]
        leads.append(make_lead(f"L-{i:05d}", score, is_vip=i % 8 == 0,
                               Region=region, Language=language, Industry_Vertical=industry))
    return leads, reps


def test_scale_50k_leads_1600_reps(capsys):
    leads, reps = scale_inputs()
    started = time.perf_counter()
    result = route_leads(leads, reps)
    elapsed = time.perf_counter() - started
    assert_invariants(result, leads, reps)
    assert result["assignments"] and result["overflow"]
    assert not result["rep_warnings"]
    # Report actual time, never assert a machine-dependent wall-clock threshold.
    with capsys.disabled():
        print(f"\nSynthetic routing: {elapsed:.6f}s; Python {platform.python_version()}; "
              f"{platform.platform()}; assigned={len(result['assignments'])}; "
              f"review={len(result['overflow'])}")
