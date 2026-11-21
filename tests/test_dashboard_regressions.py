"""Regression coverage for representative row identity and manager-edit capacity."""
import copy
import re
from pathlib import Path

import pytest

from src import dashboard_helpers as H


@pytest.fixture
def assigned_lead():
    reps = [
        dict(rep_id="R-N", name="North", region="North America", language="English",
             industry="Technology", seniority="Senior", current_capacity=3, max_capacity=25),
        dict(rep_id="R-E", name="Europe", region="Europe", language="English",
             industry="Technology", seniority="Senior", current_capacity=2, max_capacity=25),
    ]
    lead = dict(lead_id="L1", region="North America", language="English", industry="Technology",
                rep_id="R-N", rep_name="North", rep_seniority="Senior",
                assignment_status=H.STATUS_ASSIGNED, reason="", score=90, priority="Critical")
    return reps, lead


def assert_waiting(lead):
    assert lead["assignment_status"] == H.STATUS_REVIEW
    assert lead["reason"]
    assert not any(lead.get(key) for key in ("rep_id", "rep_name", "rep_seniority", "manual"))


@pytest.mark.parametrize("field,value", [
    ("region", "Europe"), ("language", "German"), ("industry", "Healthcare"),
])
def test_remove_edits_releases_assignment_once_and_supports_later_undo(assigned_lead, field, value):
    reps, lead = assigned_lead
    original = lead[field]
    reps[1][field] = value
    H.edit_value(reps, lead, field, value)
    assert_waiting(lead)
    assert [rep["current_capacity"] for rep in reps] == [2, 2]

    assert H.assign_manually(lead, reps[1])
    assert reps[1]["current_capacity"] == 3
    H.clear_overrides(reps, lead)
    assert lead[field] == original
    assert_waiting(lead)
    assert [rep["current_capacity"] for rep in reps] == [2, 2]
    assert "overrides" not in lead and "original_values" not in lead

    cleared = copy.deepcopy((reps, lead))
    H.clear_overrides(reps, lead)
    assert (reps, lead) == cleared

    assert H.assign_manually(lead, reps[0])
    H.undo_manual(reps, lead)
    assert_waiting(lead)
    assert [rep["current_capacity"] for rep in reps] == [2, 2]


def test_editing_a_manual_assignment_releases_it_once(assigned_lead):
    reps, lead = assigned_lead
    H.edit_value(reps, lead, "region", "Europe")
    assert H.assign_manually(lead, reps[1])
    H.edit_value(reps, lead, "language", "German")
    H.edit_value(reps, lead, "industry", "Healthcare")
    assert_waiting(lead)
    assert [rep["current_capacity"] for rep in reps] == [2, 2]
    H.clear_overrides(reps, lead)
    assert (lead["region"], lead["language"], lead["industry"]) == (
        "North America", "English", "Technology")
    assert_waiting(lead)
    assert [rep["current_capacity"] for rep in reps] == [2, 2]


def test_undo_after_edit_and_reassignment_cannot_restore_an_empty_assignment(assigned_lead):
    reps, lead = assigned_lead
    H.edit_value(reps, lead, "region", "Europe")
    assert H.assign_manually(lead, reps[1])
    H.undo_manual(reps, lead)
    assert_waiting(lead)
    assert [rep["current_capacity"] for rep in reps] == [2, 2]


def test_no_edits_leave_an_existing_assignment_untouched(assigned_lead):
    reps, lead = assigned_lead
    original = copy.deepcopy((reps, lead))
    H.clear_overrides(reps, lead)
    H.edit_value(reps, lead, "region", lead["region"])
    assert (reps, lead) == original


def test_assignment_candidates_exclude_duplicate_and_missing_ids(assigned_lead):
    reps, lead = assigned_lead
    reps.extend([dict(reps[0]), dict(reps[0], rep_id=""), dict(reps[0], rep_id=None)])
    assert [rep["rep_id"] for rep, _, _ in H.candidate_reps(reps, lead)] == ["R-E"]


@pytest.mark.parametrize("handled", [False, True])
def test_remove_unassigned_edits_does_not_consume_capacity(assigned_lead, handled):
    reps, lead = assigned_lead
    H.edit_value(reps, lead, "region", "Europe")
    if handled:
        H.mark_handled(lead)
    H.clear_overrides(reps, lead)
    assert_waiting(lead)
    assert [rep["current_capacity"] for rep in reps] == [2, 2]


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    # Go through the real pipeline: duplicate and blank Rep_IDs remain visible
    # but are excluded from routing. Names let us distinguish their rows.
    (tmp_path / "leads_sample.csv").write_text(
        "Lead_ID,Company_Name,Region,Language,Industry_Vertical,Company_Size,Recent_Activity,VIP_Referral\n"
        "L1,Acme,North America,English,Technology,1000,Attended Webinar,False\n"
        "L2,Waiting,Asia-Pacific,German,Retail,10,,False\n", encoding="utf-8")
    reps = [
        ("R-N", "North", "North America"), ("R-E", "Europe", "Europe"),
        ("DUP", "Duplicate First", "Europe"), ("DUP", "Duplicate Second", "Europe"),
        ("", "Blank First", "Europe"), ("", "Blank Second", "Europe"),
    ] + [(f"Z-{i:02d}", f"Filler {i:02d}", "Asia-Pacific") for i in range(26)]
    (tmp_path / "reps_sample.csv").write_text(
        "Rep_ID,Name,Region,Language,Industry_Vertical_Expertise,Seniority_Level,Current_Capacity,Max_Capacity\n"
        + "".join(f"{rep_id},{name},{region},English,Technology,Senior,0,25\n"
                  for rep_id, name, region in reps), encoding="utf-8")
    monkeypatch.setenv("LEAD_DATA_DIR", str(tmp_path))
    app = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app), default_timeout=30).run()
    next(button for button in at.button if button.label == "▶ Run Sample").click().run()
    assert not at.exception
    assert len(at.session_state["results"]["reps"]) == 32
    return at


def open_rep(at, grid, row_index, visible_index=0):
    if grid:
        # AppTest exposes dataframe selection through session state.
        at.session_state[at.dataframe[0].key] = {
            "selection": {"rows": [visible_index], "columns": [], "cells": []}}
        at.run()
    else:
        at.button(key=f"rowopen_p_{row_index}").click().run()
    assert not at.exception
    return next(markdown.value for markdown in at.markdown
                if '<h4>Capacity</h4>' in markdown.value)


@pytest.mark.parametrize("grid", [False, True], ids=["colored", "grid"])
def test_rep_rows_with_duplicate_or_blank_ids_open_the_correct_record(dashboard, grid):
    at = dashboard
    original_ids = [rep["rep_id"] for rep in at.session_state["results"]["reps"]]
    at.toggle(key="grid_tables").set_value(grid).run()
    at.radio(key="tab").set_value("Rep Capacity").run()
    assert not at.exception
    at.selectbox(key="p_sort").set_value("Rep ID").run()
    at.button(key="p_page_next").click().run()
    assert not at.exception
    if grid:
        name = at.dataframe[0].value.iloc[0]["Name"]
        row_index = next(rep["_i"] for rep in at.session_state["results"]["reps"] if rep["name"] == name)
    else:
        opener = next(button for button in at.button if (button.key or "").startswith("rowopen_p_"))
        row_index = int(opener.key.rsplit("_", 1)[1])
        name = at.session_state["results"]["reps"][row_index]["name"]
    assert name in open_rep(at, grid, row_index)

    for name, row_index in [("Duplicate Second", 3), ("Blank Second", 5), ("North", 0)]:
        at.text_input(key="p_search").set_value(name).run()
        assert not at.exception
        if not grid:
            table = next(m.value for m in at.markdown if 'data-open="rowopen_p_' in m.value)
            assert re.findall(r'data-open="([^"]+)"', table) == [f"rowopen_p_{row_index}"]
        detail = open_rep(at, grid, row_index)
        assert name in detail
        if row_index == 0:
            assert "L1" in detail
        else:
            assert "No leads are assigned" in detail
            assert "L2" not in detail
    assert [rep["rep_id"] for rep in at.session_state["results"]["reps"]] == original_ids


def test_remove_changes_in_dialog_releases_capacity_and_updates_review(dashboard):
    at = dashboard
    at.button(key="edit_off").click().run()
    at.radio(key="tab").set_value("Lead Queue").run()
    at.button(key="rowopen_q_0").click().run()
    at.selectbox(key="q_ed_region_0").set_value("Europe")
    at.button(key="q_ed_save_0").click()
    # AppTest reruns the whole script; keep the dialog open for its inline action.
    at.button(key="rowopen_q_0").click().run()
    assert not at.exception
    assert_waiting(at.session_state["results"]["leads"][0])

    at.radio(key="tab").set_value("Manager Review").run()
    at.button(key="rowopen_r_0").click().run()
    assert not at.exception
    assert all(not (button.key or "").endswith(("_DUP", "_0_")) for button in at.button
               if (button.key or "").startswith("r_assign_"))
    at.button(key="r_assign_0_R-E").click().run()
    assert not at.exception
    assert at.session_state["results"]["leads"][0]["rep_id"] == "R-E"

    at.radio(key="tab").set_value("Lead Queue").run()
    at.button(key="rowopen_q_0").click().run()
    at.button(key="q_ed_undo_0").click()
    at.button(key="rowopen_q_0").click().run()
    assert not at.exception
    data = at.session_state["results"]
    assert_waiting(data["leads"][0])
    assert data["leads"][0]["region"] == "North America"
    assert sum(rep["current_capacity"] for rep in data["reps"]) == 0
    assert H.compute_kpis(data)["assigned"] == 0
