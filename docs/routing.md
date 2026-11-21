# Routing contract and decisions

Ethan owns `src/routing.py` and `tests/test_routing.py` on `feature/routing`.
The routing proposal is recorded in [issue #1](https://github.com/Apickle47/sec-ignite-salesforce/issues/1#issuecomment-7050876459)
and [issue #3](https://github.com/Apickle47/sec-ignite-salesforce/issues/3#issuecomment-7050876790).
It targets the actual output of [scoring PR #6](https://github.com/Apickle47/sec-ignite-salesforce/pull/6).
Normalization and pipeline integration must use this contract or coordinate changes in those issues.

## Call and inputs

```python
from src.routing import route_leads

results = route_leads(scored_leads, reps)
```

Both arguments are lists of dictionaries. Routing uses the standard library only
and runs on Python 3.9+. It performs no file I/O and does not import scoring,
normalization, pandas, or Streamlit.

| Input | Required fields |
| --- | --- |
| Lead | `Region`, `Language`, `Industry_Vertical`, `score`, `priority`, `is_vip` |
| Representative | `Rep_ID`, `Region`, `Language`, `Industry_Vertical_Expertise`, `Seniority_Level`, `Current_Capacity`, `Max_Capacity` |

Lead IDs and other fields are preserved. Missing or duplicate lead IDs do not
drop or collapse records: the original zero-based `source_index` traces each
outcome back to its input row. Missing or duplicate representative IDs exclude
all affected representatives because assigning to an ambiguous identity would
make capacity accounting unreliable. Representative IDs are case-sensitive;
outer whitespace is ignored for duplicate detection and ordering. Assigned
`rep_id` retains the original `Rep_ID` value for joining to `updated_reps`.

Normalization preserves that identity in both `rep_id` and `Rep_ID`, including
duplicates and blank IDs. A separate `record_id` identifies each representative
row, as it does for leads; generated row keys are never substituted for routing
identities. Row keys cannot collide with supplied IDs or other generated keys.
Duplicate/missing identity rows carry `duplicate_or_missing_id` in `flags` and
remain visible, but routing excludes them. Normalization warnings use `record_id`
for row references; routing warnings retain `source_index` and the supplied
identity. The cleaned representative CSV export also includes `record_id`.
This contract correction is recorded in
[issue #3](https://github.com/Apickle47/sec-ignite-salesforce/issues/3#issuecomment-7051961836)
and [issue #1](https://github.com/Apickle47/sec-ignite-salesforce/issues/1#issuecomment-7051962149).

The normalizer must resolve aliases before routing. Comparisons trim outer
whitespace and ignore case, but do not guess misspellings, abbreviations, or
combined/ambiguous values. Canonical values are:

- Region: `North America`, `Europe`, `Asia-Pacific`.
- Language: `English`, `German`, `Spanish`.
- Industry: `Technology`, `Healthcare`, `Finance`, `Manufacturing`, `Retail`.
- Seniority: `Junior`, `Senior`, `Manager`.

For example, ` EUROPE ` matches `Europe`; `Europ`, `APAC`, `EN`, `sr`, and `MGR`
need upstream normalization. Unknown region, language, or industry never forms
a matching group, even when both lead and representative have the same unknown
value. Leads go to Manager Review with `Missing or invalid routing fields`;
representatives are retained and excluded with that warning. Validation happens
before skill matching and capacity checks, including for VIP leads. This restores
the original strict-routing proposal and supersedes the Unknown-industry matching
policy introduced in [PR #12](https://github.com/Apickle47/sec-ignite-salesforce/pull/12).

The normalizer's merged [fused-region policy in PR #10](https://github.com/Apickle47/sec-ignite-salesforce/pull/10)
maps the two recognized combined-region spellings to their trailing region,
logging `mapped_suffix` and flagging `region_fused`. Its `FUSED_REGION_POLICY`
switch can retain them as unknown instead. Routing itself still requires a
canonical region and does not interpret raw combined-region strings.

Scores must be integers from 0 through 100, excluding booleans. Priority must
be uppercase and consistent with the baseline tiers: CRITICAL >=85, HIGH
60-84, MEDIUM 40-59, LOW 0-39. `is_vip` must be a boolean; True requires
100/CRITICAL. Routing validates this metadata without recalculating company,
activity, or industry points. Scoring's `is_vip` is authoritative; routing does
not reparse raw `VIP_Referral`. Existing scoring fallbacks remain on outcomes.

Capacities must be integers, excluding booleans, and satisfy
`0 <= Current_Capacity <= Max_Capacity`. Numeric strings, floats, negatives,
missing values, and over-capacity rows are excluded with warnings. Zero maximum
capacity is valid but full. Excluded representatives remain in `updated_reps`
unchanged. A representative with several problems receives the first applicable
warning: invalid record, invalid ID, duplicate ID, invalid skills, invalid
seniority, then invalid capacity.

## Return value

| Key | Value |
| --- | --- |
| `assignments` | Assigned lead outcomes in routing order |
| `updated_reps` | Copies of all representatives in original order, with updated capacities |
| `overflow` | Manager Review lead outcomes in routing order |
| `metrics` | Counts, assignment rate, and review reason counts described below |
| `rep_warnings` | One dictionary per excluded representative: `source_index`, original `rep_id` (or None), and readable `reason` |

Each outcome preserves its input fields and adds or replaces these reserved keys:

| Key | Assigned | Manager Review |
| --- | --- | --- |
| `source_index` | Original zero-based lead position | Original zero-based lead position |
| `rep_id` | Selected representative's `Rep_ID` | `None` |
| `assignment_status` | `Assigned` | `Manager Review` |
| `reason` | `None` | Readable review reason |

`assignments` and `overflow` partition the input: every row appears exactly once.
Each list preserves its relative routing order; concatenating the two lists does
not reconstruct the globally interleaved queue. Malformed scored rows follow
valid scored rows in original input order. Non-dictionary records are represented
with `invalid_record=True` and a short `invalid_record_repr` rather than dropped.

Metrics are `total_leads`, `assigned_count`, `manager_review_count`,
`assignment_rate` (fraction 0-1, zero for empty input), `review_counts_by_reason`
(mapping of the reason strings below to counts), and `excluded_rep_count`.

| Review reason | Meaning |
| --- | --- |
| `Invalid lead record` | Non-record input or scoring flagged `invalid_record` |
| `Invalid scoring metadata` | Missing, malformed, or contradictory score/priority/VIP metadata |
| `Missing or invalid routing fields` | At least one lead matching field is unresolved |
| `No matching representative` | No valid representative matches all three skills |
| `No eligible Senior or Manager` | A Critical lead matches only valid Juniors |
| `Eligible representatives at capacity` | Matching representatives of allowed seniority exist but are full |

Invalid/excluded representatives do not establish eligibility. For example,
matching only a representative with negative capacity produces `No matching
representative`; the separate representative warning explains the exclusion.

## Scheduling, fairness, and reset

Lead order matches scoring PR #6 for valid scored records: tier, descending
score, VIP first at equal score, lexicographic `Lead_ID`, then original input
position. Missing IDs sort as empty strings. Invalid scoring data goes to review
instead of using the scoring sort helper's permissive fallback ordering.

Representatives are indexed by normalized `(Region, Language, Industry)` and
ordered lexicographically by `Rep_ID` within each skill group. Critical leads
use round-robin Senior queues, then Manager queues when no matching Senior has
capacity, including when no Senior exists. Juniors never receive Critical leads.

After every Critical lead has been processed, combined queues are built from
remaining Junior, Senior, and Manager capacity. High, Medium, and Low leads
use equal round-robin across all three seniorities, with no additional hierarchy.
This balances new assignments among available peers; it does not equalize
pre-existing loads or utilization percentages. That is a deliberate team choice,
not a requirement imposed by the challenge.

Every successful assignment increments capacity exactly once. Full
representatives leave active queues immediately. Full but otherwise valid
representatives remain in the eligibility index to distinguish exhaustion from
skill or seniority mismatch. Time is O(L log L + R log R) including sorting,
with O(L + R) additional memory; there is no per-lead scan of all representatives.

`Current_Capacity` is the authoritative routing count. When a normalized
representative also has `current_capacity`, routing synchronizes that alias
after each assignment so either field reports the same load to the dashboard.
It copies the updated canonical value rather than incrementing both fields
independently. Excluded representatives remain unchanged.

Records are shallow-copied; routing never changes input dictionaries or nested
metadata. Preserved nested metadata should be treated as read-only. There is no
global/session state. Repeating the same baseline inputs reproduces outcomes
and capacities; explicitly passing `updated_reps` starts from those newer loads.
Dashboard Reset should discard results and reuse the original normalized
representatives. Clearing dashboard state remains the dashboard owner's work.

## Verification and measured performance

Install pytest in your development environment, then run from the repository root:

```sh
python -m pip install pytest
python -m pytest tests/test_routing.py -q
```

The suite covers strict matching, Critical seniority, round-robin and wraparound,
independent groups, initial load and overflow, invalid data/capacities, duplicate
identities, boundary scores, ordering, input preservation, and repeated/reset runs.
The 50,000-lead/1,600-representative test checks every assignment's eligibility,
seniority, capacity accounting, traceability, and outcome conservation. It prints
actual routing time without imposing a machine-dependent time limit.

Initial implementation measurements on November 20, 2026, before the merged
normalization integration fixes below:

- Python 3.9.6, pytest 8.4.2, macOS 26.6.2, arm64.
- Routing branch: **113 passed, 1 skipped**. The conditional scoring integration
  test skips until `src.scoring` is available.
- A separate temporary checkout combined this routing code/tests with scoring
  PR #6 at commit `3f8d1d5bf3086ccae97b0a52c1d8e3ce0fccb69f`: **265 passed**,
  including the real scoring compatibility test and all 151 scoring tests.
- Five sequential synthetic routing runs: **0.339442, 0.359432, 0.332718,
  0.345427, 0.332095 seconds**; median **0.339442 seconds**. Each run received
  the same baseline inputs and its invariants were verified after timing.
- Each run assigned **43,300** leads and sent **6,700** to Manager Review for
  exhausted capacity, with no excluded representatives (assignment rate 86.6%).

The deterministic fixture is `scale_inputs()` in the routing test module. It
spans all 45 skill combinations, cycles representative seniority and capacities
(Junior 50 / Senior 25 / Manager 10), includes initial loads 0-3, and cycles
scores 100/85/84/60/59/40/39/0. Every score-100 lead is a VIP.
Timing measures only `route_leads`, excluding fixture construction and assertions.

These are **synthetic routing-only measurements**, not a benchmark of the
supplied CSVs or complete application. No original challenge data has been changed.

### Historical merged-module regression verification

After the capacity alias and representative identity corrections on November 20,
2026, and integration of the merged policies from PRs #10 and #12, the complete
repository suite passed: **371 tests**, with no skips.
Eight focused regression cases failed before the fix and passed afterward.
Coverage now includes normalization -> scoring -> routing for duplicate/missing
representative IDs, row-key collisions, Critical and ordinary assignments,
capacity aliases, immutable inputs, continued runs, and reset/repeat runs.
Fused-region warnings also retain the correct row keys for duplicate/missing
representative identities after the merge.
Both supplied CSV pairs also run through the three modules in regression tests.

A separate single-run measurement on Python 3.9.6, pytest 8.4.2, macOS 27.2.1
arm64 produced:

| Supplied dataset | Assigned | Manager Review | Full backend time | Routing time |
| --- | --- | --- | --- | --- |
| 100 leads / 10 reps | 9 | 91 | 0.007307 s | 0.000718 s |
| 50,000 leads / 1,600 reps | 45,924 | 4,076 | 2.328497 s | 0.613991 s |

Full backend time covers load -> normalize -> score -> route, excluding
assertions and UI rendering. Assignment order, Manager Review reasons, and
canonical representative loads match main commit `17ca59e` for both datasets,
with **zero capacity-alias mismatches** and unique representative row keys.
The increased scale assignment count compared with the earlier 35,525 comes
from the team's merged fused-region and Unknown-industry policies. All rows are
preserved and all assignment eligibility,
seniority, capacity, and repeat-run invariants pass. This is a direct module
chain, not validation of a dashboard or production pipeline entrypoint; those
components and their benchmark tooling remain integration/dashboard work.

### Current strict unknown-field verification — November 21, 2026

Unknown industry is now rejected alongside Unknown region and language. Routing
tests cover case/whitespace variants, blank and unrecognized raw fields, excluded
representatives, VIPs, and missing-data reasons taking precedence over capacity.
The CSV-to-pipeline-to-dashboard regression cases verify that scoring-only
fallbacks still permit assignment and that review categories remain distinct.

- Routing suite: **142 passed in 2.86 s**.
- Complete repository suite: **421 passed in 14.60 s**, with no skips, including
  the supplied sample/scale pipeline tests and the dashboard run/reset test.
- Environment: Python 3.12.14, pytest 9.2.0, Streamlit 1.67.0,
  macOS 27.2.1 arm64, using an isolated temporary virtual environment.

A separate single-run measurement of the supplied data produced:

| Supplied dataset | Assigned | Manager Review | Pipeline wall time | Routing only |
| --- | --- | --- | --- | --- |
| 100 leads / 10 reps | 9 | 91 | 0.004390 s | 0.000509 s |
| 50,000 leads / 1,600 reps | 40,665 | 9,335 | 1.472399 s | 0.348421 s |

Pipeline wall time covers `src.pipeline.run_dataset`, including CSV loading,
normalization, scoring, routing, outcome assembly, and metrics. It excludes
verification assertions and dashboard rendering. Routing-only time comes from
the pipeline's `routing_only` measurement. These are observations, not limits.

The scale review queue contains **6,167 missing/invalid routing-field leads**
and **3,168 capacity-exhausted leads**; **191 representatives** are excluded for
unresolved skills. The sample review queue contains 14 missing/invalid-field
leads and 77 with no matching representative; three representatives are excluded.
The dashboard categories agree with these engine reasons. No assigned lead in
either dataset has Unknown region, language, or industry. Every lead remains
traceable, capacity accounting and aliases pass, and all four original CSV hashes
are unchanged. Fused-region normalization and scoring fallbacks retain their
existing behavior.
