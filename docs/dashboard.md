# Dashboard integration

The dashboard combines Hamsini's clickable-row UI from `feature/dashboard-hamsini` (including the representative identity and capacity fixes from PR #19) with the Gemini assistant and verified pipeline on `main`. It addresses dashboard issue #4. PR #18 was closed without merging; this integration carries that UI forward while preserving the later routing and chatbot work.

## Manager workflow

- Run Sample or Scale, then use Overview, Lead Queue, Manager Review, and Rep Capacity to inspect the results.
- Click a colored lead row for score/routing explanations, or a representative row for capacity and assigned leads. Settings → Grid tables provides native Streamlit row selection if the browser blocks the colored-table click bridge.
- Enable Edit mode, open a lead, and save a region, language, or industry change. This releases its assignment once and sends it to Manager Review. Removing changes restores its original fields and also requires review; it does not restore an obsolete assignment.
- Representative details use the original row index, so blank or duplicate IDs still open the correct record. Such representatives cannot be selected for manual assignment.
- Open the collapsed sidebar for Ask Assistant. Chat reads the current session, including dialog actions. Successful runs and Reset clear chat; a failed run preserves the last results and conversation.
- Live CSV links remain available under Settings → Live link. Refreshes check for changes every 30 seconds and retain applicable manager work. The app never writes back to the source CSVs or links.
- Light is the native Streamlit default in `.streamlit/config.toml`; dashboard Settings controls Light/Dark appearance. Toolbar controls wrap when the chat sidebar leaves less space.

## Interfaces

`src.dashboard_adapter.run_pipeline(leads_path, reps_path)` remains the only pipeline entry point used by the app. Normalization, scoring, routing, source CSVs, and the assistant's provider/query interfaces are unchanged.

`src.dashboard_helpers.clear_overrides(reps, lead)` now takes the representative list to release capacity when restoring a lead's original matching fields. It mutates the in-memory lead and affected representative, clears stale manual assignment state, and sets Manager Review. The app and assistant-context regression tests use this signature.

Dialog state uses `_i` on each displayed lead and representative to identify its original result row. It is session metadata, not a new CSV field or routing input.

## Validation — November 21, 2026

Environment: macOS 27.2.1 arm64, Python 3.12.14, Streamlit 1.67.0, pytest 9.2.0.

- Full suite: **505 passed in 24.43 seconds**, using `python -m pytest -p no:cacheprovider -q` with bytecode writing disabled. Automated Gemini responses are mocked.
- Regression tests cover colored and grid-table representative selection with duplicate/blank IDs, pagination/filtering, field-edit/undo capacity accounting, chat counts after dialog edits, and live-link success/failure conversation behavior.
- Browser checks cover colored lead/rep detail pop-ups, manager handling, live-link controls, sidebar-open toolbar wrapping, light/dark themes, and Reset clearing results/chat. Live Gemini checks correctly explained Critical routing and reported the updated 9 assigned / 90 waiting / 1 handled counts after a dialog action.
- Synthetic routing test: 50,000 leads / 1,600 reps in **0.250714 seconds**; 43,300 assigned, 6,700 reviewed.
- Supplied scale CSVs: 50,000 leads / 1,600 reps, **1.405179 seconds total**, **0.369451 seconds routing only**; 40,665 assigned, 9,335 reviewed, 191 excluded reps. These are single local measurements, not timing guarantees.

Deployment still needs its own ignored Gemini credentials and a browser smoke check in the hosted environment. The colored-table bridge depends on Streamlit's DOM; the native grid option is the supported fallback. Browser checks here used the local desktop preview, not every browser or mobile device.
