# Manager assistant

The Streamlit sidebar answers questions about the program and the current run. It can explain scoring and routing before a dataset is loaded. After a run, it can summarize outcomes, count and group filtered leads or reps, look up an exact displayed ID, and explain stored review reasons or current capacity. Follow-up questions use the recent conversation. Answers show the local rules/data sources supplied to the model.

Examples:

- How does this program decide which rep receives a Critical lead?
- Why are unknown leads in Manager Review even when they are VIPs?
- How many European leads need review, grouped by reason?
- Explain the score and outcome for L-1057#1.
- Which eligible German-speaking reps still have capacity?
- What changed in the review counts after I handled that lead?

Questions cover the full loaded run. Dashboard filters only change the table view; specify filters in the question to narrow the answer. The assistant reads current session data, including manual assignments, handled leads, manager defaults, and field edits. It cannot assign leads, change fields/capacity, run/reset the pipeline, execute code, or browse the web. Unrelated questions are redirected to program topics.

## Configuration

Install the existing `requirements.txt` and launch `python -m streamlit run app.py` from the repository root. No additional SDK dependency is needed. Configure the server with:

| Setting | Required | Default |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes, for chat | None |
| `GEMINI_MODEL` | No | `gemini-4-hydrogen` |

Environment values take precedence over Streamlit secrets. Alternatively, create `.streamlit/secrets.toml` locally:

```toml
GEMINI_API_KEY = "replace-with-your-own-key"
GEMINI_MODEL = "gemini-4-hydrogen"
```

Keep the real key out of source code, chat messages, screenshots, and commits. The secrets file and `.env` are ignored by Git; the app does **not** automatically load `.env`. Streamlit-hosted deployments can set these same names in the deployment's Secrets settings. Restart the server after changing configuration. A key with access and quota for the chosen model is required.

Without a key, chat controls are disabled with a setup message; dataset runs and manager actions continue working. Authentication, quota, model/configuration, connection, and unreadable-response errors appear only in the assistant. Retry resends the failed question once without duplicating it. There is no automatic retry or silent fallback to invented answers.

## Data and API behavior

Requests send Google Gemini the manager's question, recent chat text, curated program rules, current aggregate counts, and selected details from local read-only lookups. They never include the entire dataset or an API key in prompt text. A lookup can send lead/company names, rep names, IDs, skills, scores, assignment/review details, or capacities. The sidebar discloses this data flow before use.

The implementation uses the [Gemini Interactions API](https://aistudio.google.com/docs/interactions-overview), [function calling](https://aistudio.google.com/docs/function-calling), and the configurable [Gemini 4 Hydrogen model](https://aistudio.google.com/docs/models/gemini-4-hydrogen). REST calls use the standard library, the `x-goog-api-key` header, and API revision `2026-05-20`. `store: false` disables stored interaction state; it is not a claim about Google's other service retention policies. No conversations are written to disk by this app.

Each manager question starts a fresh provider interaction using current session data. During that question, returned steps, including opaque thought/signature steps, are preserved for stateless tool continuation. Only final text is displayed; thought text is never shown. Previous conversational text supports follow-ups but is explicitly marked as potentially stale. Tool names and arguments are allowlisted and validated locally.

Limits:

| Resource | Bound |
| --- | --- |
| Session history | 10 completed turns / 20 messages; an unanswered question replaces the oldest turn as needed |
| Question / answer text | 2,000 / 6,000 characters (long answers are marked as shortened) |
| Returned rows / groups | 20 per lookup; exact total counts and truncation flags accompany examples |
| Record string fields | 160 characters, with a truncation marker |
| Outbound request body | 128,000 bytes, checked before each request |
| Provider response body | 2,000,000 bytes |
| Requests per question | At most 4, with at most 4 local lookups per response |
| HTTP timeout | 30 seconds for network operations |

Chat is retained across dashboard navigation and cleared on **Clear chat**, **Reset**, and every successful dataset run/refresh, including defaults-driven reruns. A failed run retains the last successful run and its chat. Manual edits retain the conversation; the next question obtains fresh counts and details. Chat state belongs to the current Streamlit session.

## Public interfaces and evidence limits

`src.assistant.answer_question(question, history, results, dataset_label=None, *, api_key, model=DEFAULT_MODEL, transport=None)` returns `{"answer": str, "sources": list[str]}`. History entries contain `role` (`user` or `assistant`) and `content`. Results use the existing `src.dashboard_adapter` dictionary. Errors raise `AssistantError` with a user-safe message. The optional transport takes `(payload, api_key)` and returns a parsed Interactions response, allowing tests without network calls. Inputs are unchanged.

`src.assistant_context.AssistantContext(results=None, dataset_label=None).call(name, arguments)` dispatches only these validated queries:

| Query | Arguments |
| --- | --- |
| `get_program_rules` | None |
| `get_summary` | None; all current outcomes, review reasons, capacity, excluded reps, manual assignment count, and defaults |
| `query_leads` | Optional `filters`, `group_by`, and `limit` (1–20); filters: exact `lead_id`/`rep_id`, priority, assignment status, region, language, industry, text search, VIP, minimum score |
| `query_reps` | Optional `filters`, `group_by`, and `limit` (1–20); filters: exact `rep_id`, seniority, region, language, industry, text search, eligibility, minimum remaining capacity |
| `lookup_record` | `entity` (`lead`/`rep`), exact displayed `identifier`, optional zero-based dashboard `row_index` to disambiguate duplicate IDs |

Groupable lead fields are priority, assignment status, region, language, industry, reason, VIP, and rep ID; rep fields are seniority, region, language, industry, and eligibility. Tool schemas spell out exact names. Queries count the full matching set before bounding rows/groups. Representative eligibility reuses `route_leads([], reps)` validation, so unknown skills, invalid capacities, and missing/duplicate IDs are excluded consistently. Eligible does not mean the rep has free slots; remaining capacity is reported separately.

`src.assistant_ui.render_assistant()` renders the sidebar, and `clear_assistant_history()` clears its conversation/error state. Existing pipeline, normalization, scoring, and routing interfaces are unchanged.

The dashboard keeps outcomes and current capacities, not the original routing queue or capacity at each historical assignment. The assistant must not invent that audit trail. For a single lead lookup, `score_lead()` recomputes the score from **current displayed fields**, reports whether it matches the stored score, and labels the calculation accordingly. A manager edit may change those fields without changing the stored score. Duplicate IDs yield choices rather than an arbitrary record. Missing lookups and unavailable data are reported explicitly.

## Validation and measurements

On November 21, 2026, Python 3.12.14, Streamlit 1.67.0, pytest 9.2.0, macOS 27.2.1 arm64:

- Full suite: **488 passed in 19.76s** with `python -m pytest -p no:cacheprovider -q`.
- 67 new tests cover exact/filtered/grouped counts, strict eligibility, duplicate/missing IDs, current manual edits, score discrepancies, unchanged inputs, bounded context, stateless tool continuation, safe failures, retry, history retention, navigation, both datasets, and reset. All provider responses are mocked.
- Python 3.9 syntax parsing passes for the new assistant modules and app. The assistant uses stdlib REST; the full dashboard runtime was tested on Python 3.12, not 3.9.
- A separate supplied-data measurement processed **50,000 leads / 1,600 reps**: pipeline wall time **1.431682s**, routing only **0.328773s**. Results: **40,665 assigned**, **9,335 Manager Review**, **191 excluded reps**.
- Building assistant context, summary, one grouped review-lead query, and one grouped available-rep query took **0.069081s**. The mocked two-request answer loop took **0.147742s**. Request bodies were **7,257** and **26,638 bytes**, returning **20 leads / 20 reps**, with exact aggregate counts. These are single local measurements, not latency guarantees or live Gemini timings.

No Gemini key was configured, so live authentication/model access and answer quality remain to be verified. After configuration, ask a program-only question, run Sample, request a specific lead explanation and review breakdown, ask a follow-up after a manual action, and confirm Reset clears chat. Compare the response with the displayed outcome and counts. A hosted model can still produce an incorrect explanation; the dashboard's stored results are the authoritative record.
