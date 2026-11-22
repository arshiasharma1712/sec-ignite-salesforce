"""Lead Prioritization Dashboard - Streamlit dashboard.

Run with:  streamlit run app.py

This file only draws things. All the number crunching and HTML lives in
dashboard_helpers.py, and the routing logic lives in the team's pipeline.
"""

import sys
import tempfile
from pathlib import Path

from datetime import datetime

import inspect

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from src import dashboard_helpers as H
from src.assistant_ui import clear_assistant_history, render_assistant

# Keep main's verified normalization/scoring/routing adapter as the single entry point.
from src.dashboard_adapter import run_pipeline
PIPELINE_NAME = "team pipeline"

DATA_DIR = HERE / "data"
# the team's CSVs, found by name (leads/reps + sample/scale); missing pairs give a plain "file not found" message
DATASETS = H.find_datasets(HERE) or {
    "Sample (100 leads)": ("leads_sample.csv", "reps_sample.csv"),
    "Scale (50,000 leads)": ("leads_scale.csv", "reps_scale.csv"),
}
DATASETS.setdefault("Sample (100 leads)", ("leads_sample.csv", "reps_sample.csv"))
DATASETS.setdefault("Scale (50,000 leads)", ("leads_scale.csv", "reps_scale.csv"))
PAGE_SIZES = [25, 50, 100]
CAND_PAGE = 10  # reps shown per page in the manager-action list
# the ☰ Settings menu: key -> starting value
SETTINGS_DEFAULTS = {"theme": "Light", "text_size": "Normal", "density": "Comfortable",
                     "hc": False, "motion": False, "grid_tables": False}
LEAD_EXPORT_FIELDS = ["lead_id", "company", "region", "language", "industry", "company_size",
                      "activity", "vip", "score", "priority", "assignment_status",
                      "rep_id", "rep_name", "reason"]

st.set_page_config(page_title="Lead Prioritization Dashboard", page_icon="☁️", layout="wide", initial_sidebar_state="collapsed")


# ---------------------------------------------------------------- state ----
LIVE_LABEL = "Live link"


def source_paths(label):
    """CSV paths and a fingerprint for bundled files or the manager's live links."""
    if label == LIVE_LABEL:
        if not st.session_state.get("live_dir"):
            st.session_state.live_dir = tempfile.mkdtemp(prefix="ignite_live_")
        folder = Path(st.session_state.live_dir)
        leads, reps = folder / "leads.csv", folder / "reps.csv"
        signature = (H.download_csv(st.session_state.get("live_leads_url"), leads, "lead_id"),
                     H.download_csv(st.session_state.get("live_reps_url"), reps, "rep_id"))
        return str(leads), str(reps), signature
    leads_file, reps_file = DATASETS[label]
    paths = [Path(leads_file) if Path(leads_file).is_absolute() else DATA_DIR / leads_file,
             Path(reps_file) if Path(reps_file).is_absolute() else DATA_DIR / reps_file]
    return str(paths[0]), str(paths[1]), H.file_signature(paths)


def run_dataset(label, keep_view=False):
    saved = H.save_manager_work((st.session_state.get("results") or {}).get("leads", [])) if keep_view else {}
    defaults = st.session_state.get("defaults") or {}
    filled_path = None
    try:
        with st.spinner(f"Cleaning, scoring and routing {label.lower()}..."):
            leads_path, reps_path, signature = source_paths(label)
            filled, counts = {}, {}
            if defaults:  # fill blanks in a temp copy; the original CSV is never changed
                leads_path, filled, counts = H.write_filled_csv(leads_path, defaults)
                filled_path = leads_path
            results = run_pipeline(leads_path, reps_path)
            if defaults:  # second pass: values the cleaner could not read also get the default
                patches, extra = H.unreadable_patches(results.get("leads", []), defaults)
                if patches:
                    second_path = H.write_patched_csv(leads_path, patches)
                    try:
                        results = run_pipeline(second_path, reps_path)
                    finally:
                        Path(second_path).unlink(missing_ok=True)
                    for lead_id, labels in extra.items():
                        filled.setdefault(lead_id, []).extend(labels)
                        for label in labels:
                            counts[label] = counts.get(label, 0) + 1
        for lead in results.get("leads", []):
            if lead.get("lead_id") in filled:
                lead["defaults_applied"] = filled[lead["lead_id"]]
        results["defaults_used"], results["defaults_filled"] = dict(defaults), counts
        for position, lead in enumerate(results.get("leads", [])):
            lead["_i"] = position  # lets a manager action find its lead again
        for position, rep in enumerate(results.get("reps", [])):
            rep["_i"] = position  # Rep_ID may be missing or duplicated; identify the row instead
        if keep_view:  # live refresh: keep the manager's work and the screen as it was
            st.session_state.kept_edits = H.reapply_manager_work(results, saved)
        else:
            for key in [k for k in st.session_state if k[:2] in ("q_", "r_", "p_")]:
                del st.session_state[key]  # old filter choices may not exist in the new data
        st.session_state.file_sig = signature
        st.session_state.refreshed_at = datetime.now().strftime("%H:%M:%S")
        st.session_state.results = results
        st.session_state.dataset = label
        st.session_state.error = None
        clear_assistant_history()
    except FileNotFoundError as error:
        st.session_state.error = f"Could not find {Path(error.filename or '').name}. Put the team's CSVs in the repo's data/ folder."
    except ValueError as error:
        st.session_state.error = str(error)
    except Exception as error:  # keep the demo alive and show what happened
        st.session_state.error = f"The pipeline failed: {error}"
    finally:
        if filled_path:
            Path(filled_path).unlink(missing_ok=True)


def reset_all():
    """Clear outputs. The pipeline re-reads the CSVs on every run, so rep
    capacities always start back at their baseline (0) after a reset."""
    for key in list(st.session_state.keys()):
        if key not in SETTINGS_DEFAULTS and not key.startswith(("def", "live_")):  # keep settings, defaults and links
            del st.session_state[key]


def reset_settings():
    st.session_state.update(SETTINGS_DEFAULTS)


def pager(key, total_pages, page_size=None):
    """Prev / Next buttons. Page number lives in session_state[key]."""
    page = min(max(st.session_state.get(key, 1), 1), total_pages)
    st.session_state[key] = page

    def move(step):
        st.session_state[key] = min(max(st.session_state[key] + step, 1), total_pages)

    left, middle, right, _ = st.columns([1, 2.6, 1, 5])
    left.button("◀ Prev", key=f"{key}_prev", on_click=move, args=(-1,), disabled=page <= 1)
    middle.markdown(f'<div class="pager">Page {page} of {total_pages}' + (f' · {page_size} rows per page' if page_size else '') + '</div>', unsafe_allow_html=True)
    right.button("Next ▶", key=f"{key}_next", on_click=move, args=(1,), disabled=page >= total_pages)
    return page


def column_filters(prefix, columns):
    """One small text box per column. Type a word and only rows whose column contains it stay."""
    st.markdown('<div class="filter-hint">Filter by column: type a word under any column '
                '(e.g. <b>north</b> under Region) and press Enter.</div>', unsafe_allow_html=True)
    boxes = st.columns(len(columns))
    return {field: box.text_input(label, key=f"{prefix}_col_{field}", placeholder=f"{label}...")
            for box, (field, label) in zip(boxes, columns)}


def reset_page_when_filters_change(key, signature):
    if st.session_state.get(f"{key}_sig") != signature:
        st.session_state[f"{key}_sig"] = signature
        st.session_state[key] = 1



# ------------------------------------------------------ clicks and actions ----
TABS = ["Overview", "Lead Queue", "Manager Review", "Rep Capacity"]
FILTER_KEYS = ("q_search", "q_priority", "q_status")


def jump(tab, filters):
    """A KPI card button: clear the queue filters, set the ones for this card, and open the tab."""
    for key in [k for k in st.session_state if k in FILTER_KEYS or k.startswith("q_col_")]:
        del st.session_state[key]
    st.session_state["q_page"] = 1
    st.session_state.update(filters)
    st.session_state["tab"] = tab


def _poke():
    """Inside a pop-up, ask it to refresh the whole page (and close) after an action."""
    if st.session_state.get("_dlg"):
        st.session_state["_refresh"] = True


def do_assign(lead_index, rep_id):
    _poke()
    data = st.session_state.get("results") or {}
    lead = data["leads"][lead_index]
    matches = [r for r in data["reps"] if rep_id and r.get("rep_id") == rep_id]
    rep = matches[0] if len(matches) == 1 else None
    if rep and H.assign_manually(lead, rep):
        st.toast(f'{lead["lead_id"]} assigned to {rep["rep_id"]} · {rep.get("name")}')
    else:
        st.toast("That rep is full now. Pick another one.")


def do_handle(lead_index):
    _poke()
    lead = st.session_state["results"]["leads"][lead_index]
    H.mark_handled(lead)
    st.toast(f'{lead["lead_id"]} marked as handled')


def do_override(lead_index, field, widget_key):
    _poke()
    lead = st.session_state["results"]["leads"][lead_index]
    value = st.session_state.get(widget_key)
    if value:
        H.set_override(lead, field, value)
        st.toast(f'{lead["lead_id"]}: {field} set to {value} for this lead only')


def do_clear_override(lead_index):
    _poke()
    data = st.session_state["results"]
    H.clear_overrides(data["reps"], data["leads"][lead_index])
    st.toast("Fallback removed from this lead")


def toggle_edit_mode():
    st.session_state.edit_mode = not st.session_state.get("edit_mode", False)


def edit_panel(rows, key):
    """Edit mode: a sheet-like table where missing or defaulted region / language / industry cells can be typed over."""
    st.markdown('<div class="why-box"><h4>Edit mode is on</h4>Change a Region, Language or Industry cell that is missing or was '
                'defaulted, then press <b>Save changes</b>. Changes apply to that lead only, are marked with a pink * and are '
                'never written to the CSV. If the lead already had a rep, it goes back to Manager Review so you can pick the right one.</div>',
                unsafe_allow_html=True)
    here = [lead for lead in rows if H.editable_fields(lead)]
    if not here:
        st.caption("No missing or defaulted values on this page.")
        return
    reps_now = st.session_state["results"]["reps"]
    options = {k: sorted({str(r.get(k)) for r in reps_now if r.get(k) not in (None, "", "Unknown")}
                         | {str(l.get(k)) for l in here} - {"Unknown"}) + ["Unknown"] for k in H.SKILL_KEYS}
    frame = pd.DataFrame([{"Lead": l["lead_id"], "Company": l["company"], "Region": l["region"], "Language": l["language"],
                           "Industry": l["industry"], "Status": l["assignment_status"], "Rep": l.get("rep_id") or "-"} for l in here])
    version = st.session_state.get("edit_version", 0)
    edited = st.data_editor(frame, key=f"{key}_editor_{version}", hide_index=True, use_container_width=True,
                            disabled=["Lead", "Company", "Status", "Rep"],
                            column_config={k.capitalize(): st.column_config.SelectboxColumn(k.capitalize(), options=options[k])
                                           for k in H.SKILL_KEYS})
    st.caption(f"{len(here)} lead(s) on this page have a missing or defaulted value. Cells that are already fine stay locked.")
    if st.button("Save changes", type="primary", key=f"{key}_save_edits"):
        changes = H.changed_cells(here, edited.to_dict("records"))
        for lead, field, value in changes:
            H.edit_value(reps_now, lead, field, value)
        st.session_state.edit_version = version + 1
        st.toast(f"{len(changes)} value(s) changed" if changes else "Nothing to save")
        st.rerun()


def do_undo(lead_index):
    _poke()
    data = st.session_state["results"]
    H.undo_manual(data["reps"], data["leads"][lead_index])
    st.toast("Sent back to where the pipeline had it")


def lead_panel(rows, key, actions):
    """Pick one lead from the rows on this page and see its score, 'Why this rep?' and (optionally) manager actions."""
    if not rows:
        return
    options = [lead["_i"] for lead in rows]
    pick_key = f"{key}_pick"
    if st.session_state.get(pick_key) not in options:
        st.session_state.pop(pick_key, None)  # the page changed: the old choice is not here any more
    by_index = {lead["_i"]: lead for lead in rows}
    chosen = st.selectbox(
        "Open a lead", options, key=pick_key, help=H.help_text("lead"),
        format_func=lambda i: f'{by_index[i]["lead_id"]} · {by_index[i]["company"]} · '
                              f'{by_index[i]["priority"]} · score {by_index[i]["score"]} · {by_index[i]["assignment_status"]}')
    lead_body(by_index[chosen], key, actions)


def lead_body(lead, key, actions):
    """Everything about one lead: its summary, manager actions and the 'Why this rep?' box."""
    chosen = lead["_i"]
    all_reps = st.session_state["results"]["reps"]
    st.markdown(f'<div class="sub">{H.priority_badge(lead["priority"])} {H.status_badge(lead["assignment_status"])}'
                + (f' <span class="vip"{H.tip("VIP")}>VIP</span>' if lead.get("vip") else "")
                + f' &nbsp; <b>{H.esc(lead["lead_id"])}</b> · {H.esc(lead["company"])} · {H.esc(lead["region"])} / '
                  f'{H.esc(lead["language"])} / {H.esc(lead["industry"])}</div>', unsafe_allow_html=True)
    if actions:
        if lead.get("manual"):
            what = (f'Assigned by hand to <b>{H.esc(lead["rep_id"])} · {H.esc(lead["rep_name"])}</b>. This overrides the automatic routing.'
                    if lead["manual"] == "assigned" else "Marked as handled by a manager.")
            st.markdown(f'<div class="why-box"><h4>Manager action</h4>{what}</div>', unsafe_allow_html=True)
            st.button("↩ Undo, send back to review", key=f"{key}_undo_{chosen}", on_click=do_undo, args=(chosen,))
        elif H.is_waiting(lead):
            missing = H.unreadable_fields(lead)
            if missing or lead.get("overrides"):
                st.markdown('<div class="why-box"><h4>Fix the missing data for this lead</h4>Pick a value for each missing field. '
                            'It applies to this lead only, is marked with a pink * and is never written to the CSV.</div>',
                            unsafe_allow_html=True)
                for field in missing:
                    options = sorted({str(r.get(field)) for r in all_reps if r.get(field) not in (None, "", "Unknown")})
                    left, right = st.columns([4, 1])
                    wkey = f"{key}_fix_{field}_{chosen}"
                    left.selectbox(field.capitalize(), options, key=wkey, index=None, placeholder=f"Choose a {field}")
                    right.button("Apply", key=f"{wkey}_go", on_click=do_override, args=(chosen, field, wkey),
                                 use_container_width=True)
                if lead.get("overrides"):
                    st.button("✕ Remove my fixes from this lead", key=f"{key}_unfix_{chosen}", on_click=do_clear_override, args=(chosen,))
            everyone = H.candidate_reps(all_reps, lead)
            st.markdown('<div class="why-box"><h4>Manager action</h4>Every rep with room is listed, best match first. '
                        'Search by rep ID or name, or mark the lead as handled if you will deal with it outside the '
                        'system.</div>', unsafe_allow_html=True)
            query = st.text_input("Find a rep", placeholder="Type a rep ID or name, like R-499", key=f"{key}_repq_{chosen}")
            found = H.search_candidates(everyone, query)
            st.caption(f"{H.fmt_int(len(found))} of {H.fmt_int(len(everyone))} reps with room · most to least qualified "
                       "(skills match first, then the preferred level and the least busy rep)"
                       + (" · Critical leads can't go to Juniors" if lead["priority"] == "Critical" else ""))
            reset_page_when_filters_change(f"{key}_cand_page", (chosen, query))
            if not found:
                st.caption("No rep with room matches that search." if query else "No rep with free capacity is available for this lead.")
            else:
                cand_page = pager(f"{key}_cand_page", H.paginate(found, 1, CAND_PAGE)[2], CAND_PAGE)
                rows_here, _, _ = H.paginate(found, cand_page, CAND_PAGE)
                for offset, (rep, marks, _misses) in enumerate(rows_here, (cand_page - 1) * CAND_PAGE + 1):
                    left, right = st.columns([5, 1])
                    left.markdown(H.candidate_html(rep, marks, offset), unsafe_allow_html=True)
                    right.button("Assign", key=f"{key}_assign_{chosen}_{rep['rep_id']}", type="primary",
                                 on_click=do_assign, args=(chosen, rep["rep_id"]), use_container_width=True)
            st.button("✓ Mark as handled", key=f"{key}_handle_{chosen}", on_click=do_handle, args=(chosen,))
    st.markdown(H.score_html(lead) + H.why_html(lead), unsafe_allow_html=True)



# ------------------------------------------ click a row -> pop-up ----------
_dialog = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)
try:
    HAS_ROW_CLICK = _dialog is not None and "on_select" in inspect.signature(st.dataframe).parameters
except (TypeError, ValueError):
    HAS_ROW_CLICK = False
PRIORITY_DOT = {"Critical": "🔴 Critical", "High": "🟠 High", "Medium": "🟡 Medium", "Low": "⚪ Low"}


def lead_edit_box(lead, key):
    """Edit mode, inside the pop-up: change a lead's Region / Language / Industry. Never written to the CSV."""
    chosen = lead["_i"]
    reps_now = st.session_state["results"]["reps"]
    st.markdown('<div class="why-box"><h4>Edit mode is on</h4>Change this lead\'s Region, Language or Industry, then press '
                '<b>Save changes</b>. It applies to this lead only, is marked with a pink * and is never written to the CSV. '
                'If the lead already had a rep, it goes back to Manager Review so you can pick the right one.</div>',
                unsafe_allow_html=True)
    cols = st.columns(len(H.SKILL_KEYS))
    picked = {}
    for column, field in zip(cols, H.SKILL_KEYS):
        current = str(lead.get(field))
        options = sorted({str(r.get(field)) for r in reps_now if r.get(field) not in (None, "", "Unknown")}
                         | ({current} - {"Unknown"}))
        picked[field] = column.selectbox(field.capitalize(), options, key=f"{key}_ed_{field}_{chosen}",
                                         index=options.index(current) if current in options else None,
                                         placeholder=f"Choose a {field}")
    left, right = st.columns([1, 1])
    if left.button("Save changes", type="primary", key=f"{key}_ed_save_{chosen}", use_container_width=True):
        changes = [(f, v) for f, v in picked.items() if v and v != lead.get(f)]
        if not changes:
            st.toast("Nothing to change")
        else:
            for field, value in changes:
                H.edit_value(reps_now, lead, field, value)
            st.toast(f'{lead["lead_id"]}: {len(changes)} value(s) changed')
            st.rerun()
    if lead.get("overrides") and right.button("↩ Remove my changes", key=f"{key}_ed_undo_{chosen}", use_container_width=True):
        H.clear_overrides(reps_now, lead)
        st.toast("Changes removed from this lead")
        st.rerun()


if _dialog is not None:
    @_dialog("Lead details", width="large")
    def lead_dialog(lead_index, key, actions):
        st.session_state["_dlg"] = True
        if st.session_state.pop("_refresh", False):
            st.rerun()  # an action was taken: redraw the page behind the pop-up and close it
        lead = st.session_state["results"]["leads"][lead_index]
        if st.session_state.get("edit_mode"):
            lead_edit_box(lead, key)
        lead_body(lead, key, actions)

    @_dialog("Rep details", width="large")
    def rep_dialog(rep_index):
        data = st.session_state["results"]
        if not 0 <= rep_index < len(data["reps"]):
            st.caption("That rep is not in the current results.")
            return
        rep = data["reps"][rep_index]
        rep_id = rep.get("rep_id")
        unique_id = rep_id and sum(r.get("rep_id") == rep_id for r in data["reps"]) == 1
        assigned = [lead for lead in data["leads"]
                    if unique_id and lead.get("assignment_status") == H.STATUS_ASSIGNED
                    and lead.get("rep_id") == rep_id]
        st.markdown(H.rep_detail_html(rep, assigned), unsafe_allow_html=True)


def lead_frame(rows, show_status=True, show_reason=True):
    data = []
    for lead in rows:
        tags = ("  ★ VIP" if lead.get("vip") else "") + ("  (defaulted)" if (lead.get("defaults_applied") or lead.get("overrides")) else "")
        row = {"Priority": PRIORITY_DOT.get(lead.get("priority"), str(lead.get("priority"))),
               "Lead": f'{lead.get("lead_id")}{tags}', "Company": lead.get("company"),
               "Region": lead.get("region"), "Industry": lead.get("industry"), "Score": int(lead.get("score", 0))}
        if show_status:
            row["Status"] = lead.get("assignment_status")
        row["Rep"] = f'{lead["rep_id"]} {lead.get("rep_name") or ""}'.strip() if lead.get("rep_id") else "-"
        if show_reason:
            row["Reason"] = H.reason_text(lead)
        data.append(row)
    return pd.DataFrame(data)


def rep_frame(rows):
    return pd.DataFrame([{"Rep ID": r.get("rep_id"), "Name": r.get("name"), "Level": r.get("seniority"),
                          "Region": r.get("region"), "Language": r.get("language"), "Industry": r.get("industry"),
                          "Used": r.get("current_capacity", 0), "Capacity": r.get("max_capacity", 0),
                          "Full %": round(H.rep_utilization(r) * 100)} for r in rows])


def clickable_table(frame, items, key, opener):
    """A table where clicking a row calls opener(item). Row n of the frame is items[n]."""
    version = st.session_state.get(f"{key}_ver", 0)
    config = {}
    if "Score" in frame.columns:
        config["Score"] = st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")
    if "Full %" in frame.columns:
        config["Full %"] = st.column_config.ProgressColumn("Full %", min_value=0, max_value=100, format="%d%%")
    args = dict(key=f"{key}_tbl_{version}", hide_index=True, on_select="rerun", selection_mode="single-row",
                column_config=config, height=min(35 * len(frame) + 40, 600))
    try:
        event = st.dataframe(frame, use_container_width=True, **args)
    except TypeError:  # newer Streamlit: tables stretch by default
        event = st.dataframe(frame, **args)
    picked = event.selection.rows
    if picked and picked[0] < len(items):
        st.session_state[f"{key}_ver"] = version + 1  # next run: a fresh table, so the same row can be clicked again
        st.session_state.pop("_refresh", None)
        opener(items[picked[0]])


ROW_CLICK_JS = """<script>
(function () {
  var p = window.parent, d = p.document;
  if (p.__ignRowHandler) d.removeEventListener('click', p.__ignRowHandler, true);
  p.__ignRowHandler = function (e) {
    var tr = e.target && e.target.closest ? e.target.closest('tr[data-open]') : null;
    if (!tr) return;
    var btn = d.querySelector('.st-key-' + tr.getAttribute('data-open') + ' button');
    if (btn) btn.click();
  };
  d.addEventListener('click', p.__ignRowHandler, true);
})();
</script>"""


def row_openers(rows, prefix, kind, actions=False):
    """Makes the original colored table rows clickable: a click on a row presses that row's hidden button."""
    components.html(ROW_CLICK_JS, height=0)
    for row in rows:
        ident = row["_i"]
        if st.button("open", key=f"rowopen_{prefix}_{ident}"):
            st.session_state.pop("_refresh", None)
            if kind == "lead":
                lead_dialog(ident, prefix, actions)
            else:
                rep_dialog(ident)


def show_leads(rows, key, actions, **kwargs):
    if HAS_ROW_CLICK and rows:
        edit_hint = " and edit it" if st.session_state.get("edit_mode") else ""
        if st.session_state.get("grid_tables"):
            st.caption(f"👆 Click any row to open its details{edit_hint}.")
            clickable_table(lead_frame(rows, **kwargs), rows, key, lambda lead: lead_dialog(lead["_i"], key, actions))
            return
        st.caption(f"👆 Click any row to open its details{edit_hint}.")
        st.markdown(H.leads_table_html(rows, open_prefix=key, **kwargs), unsafe_allow_html=True)
        row_openers(rows, key, "lead", actions)
        return
    st.markdown(H.leads_table_html(rows, **kwargs), unsafe_allow_html=True)
    if not rows:
        return
    if actions:
        st.markdown("#### Act on a lead")
        lead_panel(rows, key, actions=True)
    else:
        with st.expander("Open a lead: score and why this rep"):
            lead_panel(rows, key, actions=False)


def show_reps(rows):
    if HAS_ROW_CLICK and rows:
        st.caption("👆 Click any row to see that rep's leads and capacity.")
        if st.session_state.get("grid_tables"):
            clickable_table(rep_frame(rows), rows, "p", lambda rep: rep_dialog(rep["_i"]))
            return
        st.markdown(H.reps_table_html(rows, open_prefix="p"), unsafe_allow_html=True)
        row_openers(rows, "p", "rep")
        return
    st.markdown(H.reps_table_html(rows), unsafe_allow_html=True)


@st.fragment(run_every=30)
def live_watch():
    """Refresh changed CSVs/links while retaining manager work; sources stay unchanged."""
    label = st.session_state.get("dataset")
    if not label:
        return
    try:
        now = source_paths(label)[2]
        problem = ""
    except ValueError:
        now, problem = None, "Could not refresh the live links; showing the last loaded results."
    if now is not None and st.session_state.get("file_sig") not in (None, now):
        st.session_state.refresh_dataset = label
        st.rerun()
    source = problem or ("Reading live CSV links" if label == LIVE_LABEL else "Reading the team CSV files")
    st.markdown(f'<div class="live"><b>●</b> {source} · checked {datetime.now().strftime("%H:%M:%S")} · '
                f'last loaded {st.session_state.get("refreshed_at", "-")}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------- header ----
for _key, _value in SETTINGS_DEFAULTS.items():  # starts in light mode with normal text
    st.session_state.setdefault(_key, _value)
if st.session_state.pop("clear_defaults", False):  # must happen before the default widgets exist
    for key in [k for k in st.session_state if k.startswith("def_")]:
        del st.session_state[key]
    st.session_state.defaults = {}
    st.session_state.rerun_dataset = st.session_state.get("dataset")
if st.session_state.get("refresh_dataset"):  # a CSV changed on disk: reload it, keep manager work
    run_dataset(st.session_state.pop("refresh_dataset"), keep_view=True)
    st.toast(f'CSV changed: dashboard refreshed ({st.session_state.get("kept_edits", 0)} manager edits kept)')
results = st.session_state.get("results")

st.markdown(H.hero_html(st.session_state.get("dataset"), PIPELINE_NAME), unsafe_allow_html=True)

c_sample, c_scale, c_reset, c_edit, c_edits, c_settings = st.container(key="run_controls").columns([1.2, 1.2, 1, 1.4, 1.6, .6])
if c_sample.button("▶ Run Sample", type="primary", use_container_width=True, help=H.help_text("Run Sample")):
    run_dataset("Sample (100 leads)")
    st.rerun()
if c_scale.button("▶ Run Scale", type="primary", use_container_width=True, help=H.help_text("Run Scale")):
    run_dataset("Scale (50,000 leads)")
    st.rerun()
if c_reset.button("↺ Reset", use_container_width=True, help=H.help_text("Reset")):
    reset_all()
    st.rerun()
_editing = bool(st.session_state.get("edit_mode"))
c_edit.button("✎ Edit mode: ON" if _editing else "✎ Edit mode", key="edit_on" if _editing else "edit_off",
              on_click=toggle_edit_mode, use_container_width=True,
              help="Turn edit mode on or off. In edit mode you can type new values into missing or defaulted cells.")
with c_edits.popover("✎ Manager edits", use_container_width=True):
    st.markdown("**Manager edits**")
    edit = st.radio("What would you like to do?", ["Enter default values", "Clear all defaults"],
                    index=None, key="def_choice")
    if edit == "Enter default values":
        st.caption("When a lead has a blank, N/A, Unknown or unreadable value in a field below, use this instead. "
                   "Leave a field on (no default) to keep the standard fallback.")
        for key, _column, label, choices in H.DEFAULT_FIELDS:
            if choices:
                st.selectbox(label, [H.NO_DEFAULT] + choices, key=f"def_{key}")
            else:
                st.text_input(label, key=f"def_{key}",
                              placeholder="e.g. 250" if key == "size" else "e.g. Unnamed company")
        if st.button("Save & apply", type="primary", key="def_save", use_container_width=True):
            chosen, problems = H.clean_defaults({k: st.session_state.get(f"def_{k}") for k, *_ in H.DEFAULT_FIELDS})
            if problems:
                st.error(" ".join(problems))
            else:
                st.session_state.defaults = chosen
                st.session_state.rerun_dataset = st.session_state.get("dataset")
                st.rerun()
    elif edit == "Clear all defaults":
        st.caption("Go back to the standard fallbacks for every blank value.")
        if st.button("Clear defaults", key="def_clear", use_container_width=True):
            st.session_state.clear_defaults = True
            st.rerun()
with c_settings.popover("☰", use_container_width=True):
    st.markdown("**Settings**")
    st.caption("Appearance")
    st.radio("Theme", ["Light", "Dark"], key="theme", horizontal=True)
    st.radio("Text size", list(H.TEXT_SIZES), key="text_size", horizontal=True)
    st.radio("Table density", H.DENSITIES, key="density", horizontal=True)
    st.caption("Accessibility")
    st.toggle("High contrast", key="hc", help="Stronger text and borders so everything is easier to read.")
    st.toggle("Grid tables (use if rows don't open)", key="grid_tables",
              help="Off: the original colored tables, click a row to open it. On: spreadsheet-style tables, also click a row.")
    st.toggle("Reduce motion", key="motion", help="Turns off hover animations and transitions.")
    st.button("Reset settings", key="settings_reset", use_container_width=True, on_click=reset_settings)
    with st.expander("Live link"):
        st.caption("Read a shared Google Sheet or CSV link. Changes are checked every 30 seconds; nothing is written back.")
        st.text_input("Leads link", key="live_leads_url", placeholder="https://docs.google.com/spreadsheets/d/...")
        st.text_input("Reps link", key="live_reps_url", placeholder="https://docs.google.com/spreadsheets/d/...")
        if st.button("▶ Run from link", type="primary", key="live_run", use_container_width=True):
            run_dataset(LIVE_LABEL)
            st.rerun()
st.markdown(H.build_css("dark" if st.session_state.theme == "Dark" else "light",
                        st.session_state.text_size, st.session_state.hc,
                        st.session_state.motion, st.session_state.density == "Compact"), unsafe_allow_html=True)

pending = st.session_state.pop("rerun_dataset", None)
if pending:  # defaults just changed: re-run what is on screen so the numbers match
    run_dataset(pending)
    st.rerun()

_active = st.session_state.get("defaults") or {}
if _active:
    _shown = results.get("defaults_filled") if results and results.get("defaults_used") == _active else None
    st.markdown(H.notice_html(_active, _shown), unsafe_allow_html=True)

if st.session_state.get("error"):
    st.error(st.session_state.error)

live_watch()
render_assistant()

if not results:
    st.markdown(H.empty_html(), unsafe_allow_html=True)
    st.stop()

# ----------------------------------------------------------------- data ----
leads = results.get("leads", [])
reps = results.get("reps", [])
kpis = H.compute_kpis(results)
review_leads = [lead for lead in leads if H.is_waiting(lead)]
handled_leads = [lead for lead in leads if lead.get("assignment_status") == H.STATUS_HANDLED]

st.session_state.setdefault("tab", TABS[0])
tab = st.radio("Section", TABS, key="tab", horizontal=True, label_visibility="collapsed",
               format_func=lambda name: f"Manager Review ({H.fmt_int(len(review_leads))})" if name == "Manager Review" else name)

# ------------------------------------------------------------- overview ----
if tab == "Overview":
    specs = H.kpi_specs(kpis)
    for row_start, row_end in ((0, 4), (4, len(specs))):
        for column, (index, spec) in zip(st.columns(4), enumerate(specs[row_start:row_end], row_start)):
            label, value, sub, tone, tip_key, action = spec
            column.markdown(H.kpi_card(label, value, sub, tone, tip_key), unsafe_allow_html=True)
            if action:
                column.button("View ›", key=f"kpi_{index}", on_click=jump, args=action, use_container_width=True)
    st.markdown(H.low_banner_html(reps), unsafe_allow_html=True)
    left, right = st.columns(2)
    left.markdown(H.priority_mix_html(leads), unsafe_allow_html=True)
    right.markdown(H.assignment_by_priority_html(leads), unsafe_allow_html=True)
    left, right = st.columns(2)
    left.markdown(H.review_reasons_html(leads), unsafe_allow_html=True)
    right.markdown(H.seniority_load_html(reps), unsafe_allow_html=True)
    warnings = results.get("warnings", [])
    if warnings:
        with st.expander(f"Data quality notes ({len(warnings)})"):
            st.caption("Messy values the cleaning step handled instead of failing.")
            for note in warnings:
                st.markdown(f"- {note}")

# ----------------------------------------------------------- lead queue ----
elif tab == "Lead Queue":
    f1, f2, f3, f4, f5 = st.columns([2.2, 1.4, 1.4, 1.5, 1])
    search = f1.text_input("Search all columns", placeholder="Anything: ID, company, rep, region...", key="q_search",
                           help=H.help_text("search"))
    priorities = f2.multiselect("Priority", H.PRIORITIES, key="q_priority", help=H.help_text("priority"))
    statuses = f3.multiselect("Status", [H.STATUS_ASSIGNED, H.STATUS_REVIEW, H.STATUS_HANDLED], key="q_status",
                              help=H.help_text("status"))
    order = f4.selectbox("Sort by", H.SORT_OPTIONS, key="q_sort", help=H.help_text("sort"))
    size = f5.selectbox("Rows per page", PAGE_SIZES, key="q_size", help=H.help_text("rows"))
    cols = column_filters("q", H.LEAD_COLUMNS)

    shown = H.sort_leads(H.filter_leads(leads, search, priorities, statuses, cols), order)
    reset_page_when_filters_change("q_page", (search, tuple(priorities), tuple(statuses),
                                              tuple(sorted(cols.items())), order, size))
    info, download = st.columns([5, 1.4])
    info.markdown(H.list_header_html("Lead Queue", len(shown), len(leads), order), unsafe_allow_html=True)
    download.download_button("⬇ Download CSV", H.to_csv_bytes(shown, LEAD_EXPORT_FIELDS),
                            file_name="lead_queue.csv", mime="text/csv", use_container_width=True)
    page = pager("q_page", H.paginate(shown, 1, size)[2], size)
    page_rows, _, _ = H.paginate(shown, page, size)
    show_leads(page_rows, "q", actions=False)

# ------------------------------------------------------- manager review ----
elif tab == "Manager Review":
    view = st.radio("Show", ["Waiting", "Handled"], key="r_view", horizontal=True,
                    format_func=lambda name: f"{name} ({H.fmt_int(len(review_leads) if name == 'Waiting' else len(handled_leads))})")
    pool = review_leads if view == "Waiting" else handled_leads
    if not pool:
        st.success("Nothing is waiting on a manager. Every lead was assigned or handled." if view == "Waiting"
                   else "Nothing has been marked as handled yet.")
    else:
        counts = H.review_breakdown(leads)
        if view == "Waiting" and counts:
            st.markdown('<div class="kpi-grid">' + "".join(
                H.kpi_card(name, H.fmt_int(n), "leads", "yellow", name) for name, n in
                sorted(counts.items(), key=lambda kv: -kv[1])) + "</div>", unsafe_allow_html=True)
        r1, r2, r3 = st.columns([2, 1.6, 1.6])
        r_search = r1.text_input("Search all columns", placeholder="Anything: ID, company, region, reason...",
                                 key="r_search", help=H.help_text("search"))
        r_priority = r2.multiselect("Priority", H.PRIORITIES, key="r_priority", help=H.help_text("priority"))
        r_reason = r3.multiselect("Reason type", sorted(counts), key="r_reason", help=H.help_text("reason"),
                                  format_func=lambda reason: "No matching rep / Data anomaly" if reason == "No matching rep" else reason)
        r_cols = column_filters("r", [c for c in H.LEAD_COLUMNS if c[0] != "rep"])
        r_rows = H.filter_leads(pool, r_search, r_priority, columns=r_cols)
        if r_reason and view == "Waiting":
            r_rows = [lead for lead in r_rows if H.review_category(lead.get("reason")) in r_reason]
        r_rows = H.sort_leads(r_rows)
        reset_page_when_filters_change("r_page", (view, r_search, tuple(r_priority), tuple(r_reason),
                                                  tuple(sorted(r_cols.items()))))
        st.caption(f"{H.fmt_int(len(r_rows))} leads {'waiting for a manager - critical first' if view == 'Waiting' else 'marked as handled'}")
        page = pager("r_page", H.paginate(r_rows, 1, 50)[2], 50)
        page_rows, _, _ = H.paginate(r_rows, page, 50)
        show_leads(page_rows, "r", actions=True, show_status=False)

# ------------------------------------------------------- rep capacity -----
else:
    total_slots = kpis["cap_total"]
    st.markdown('<div class="kpi-grid">'
                + H.kpi_card("Total slots", H.fmt_int(total_slots), f"{H.fmt_int(len(reps))} reps", "")
                + H.kpi_card("Used", H.fmt_int(kpis["cap_used"]), f'{kpis["utilization"] * 100:.0f}% utilized', "teal")
                + H.kpi_card("Remaining", H.fmt_int(total_slots - kpis["cap_used"]), "open slots", "logo")
                + H.kpi_card("Reps at max", H.fmt_int(kpis["reps_full"]), "cannot take more", "yellow")
                + "</div>", unsafe_allow_html=True)
    st.markdown(H.low_banner_html(reps), unsafe_allow_html=True)
    p1, p2, p3 = st.columns([2.2, 1.6, 1.4])
    p_search = p1.text_input("Search all columns", placeholder="Anything: rep ID, name, region...", key="p_search",
                             help=H.help_text("search"))
    p_level = p2.multiselect("Level", H.unique_values(reps, "seniority"), key="p_level", help=H.help_text("level"))
    p_sort = p3.selectbox("Sort by", ["Most utilized", "Least utilized", "Rep ID"], key="p_sort", help=H.help_text("sort"))
    p_cols = column_filters("p", H.REP_COLUMNS)
    min_util = st.slider("Only show reps at least this full (%)", 0, 100, 0, key="p_min", help=H.help_text("slider"))
    p_rows = H.sort_reps(H.filter_reps(reps, p_search, p_level, min_util, p_cols), p_sort)
    reset_page_when_filters_change("p_page", (p_search, tuple(p_level), tuple(sorted(p_cols.items())),
                                              p_sort, min_util))
    st.caption(f"{H.fmt_int(len(p_rows))} of {H.fmt_int(len(reps))} reps")
    page = pager("p_page", H.paginate(p_rows, 1, 25)[2], 25)
    page_rows, _, _ = H.paginate(p_rows, page, 25)
    show_reps(page_rows)
