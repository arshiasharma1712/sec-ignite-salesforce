# Data assumptions and fallback policies

This page lists every judgment call the cleaning, scoring and routing code makes where the challenge documents leave room. Counts are from `data/leads_scale.csv` (50,000 leads) and `data/reps_scale.csv` (1,600 reps). Every policy is logged as a warning, never applied silently, and no record is ever dropped.

## Cleaning (`src/data_loader.py`, `src/normalize.py`)

| Situation | Policy | Why |
|---|---|---|
| Mixed case, extra spaces, aliases (`NA`, `Nort America`, `Europ`, `Asa-Pacific`, `ES`, `Sr`, `mgr`) | Mapped through explicit alias tables to one canonical value | Matches the data dictionary requirement to resolve aliases and mixed casing |
| A value that cannot be read at all | Becomes `Unknown` and a warning is logged | Keeps the record, makes the gap visible, never crashes |
| Fused region values (`NORTH AMERICA Asia-Pacific`, `ASIA PACIFICEurope`) | Read as the trailing region (Asia-Pacific, Europe) and logged as `mapped_suffix`. About 6,800 warnings. | The values contain two regions, so a choice is required. A single deterministic rule is applied to leads and reps alike. This is an assumption. It can be changed to `Unknown` with one setting, `FUSED_REGION_POLICY` in `src/normalize.py`. |
| `Company_Size` blank, `null`, `None`, `N/A` | Treated as missing. Scoring applies the +20 fallback from the cheat sheet. | Cheat sheet fallback rule |
| `Company_Size` as `1,000`, `5k`, `500-1000` | Parsed to 1000, 5000, and 500 (lower bound of a range) | Explicit abbreviations are interpreted. Ranges use the conservative lower bound. |
| `VIP_Referral = Unknown` (2,505 leads) | Treated as not VIP, flagged as unknown VIP in the record | Only an explicit True triggers the Critical override |
| Negative `Max_Capacity` (94 reps) | Sign corrected only when the absolute value falls in the data dictionary range for that seniority (Junior 40 to 50, Senior 20 to 25, Manager 5 to 10). Otherwise set to 0, so the rep receives nothing. | Dictionary gives the valid ranges |
| `Current_Capacity` above `Max_Capacity` | Clamped to max | Never allow an over-capacity rep |
| Repeated `Lead_ID` (509 repeats) | Each row gets a unique `record_id` (`L-1057#1`, `L-1057#2`). The original `Lead_ID` is kept. | Every input row stays traceable |

## Scoring (`src/scoring.py`)

Follows the Scoring Logic Cheat Sheet exactly: VIP gives 100 and Critical, size points, activity points, industry points, tiers at 85, 60 and 40. Missing size gives +20. Unmapped or missing activity gives +0. Unknown industry gives +0.

The cheat sheet says to expect about 10% Critical, 20% High, 40% Medium, 30% Low. Our scale result is about 13.9%, 27.6%, 27.2%, 31.2%. The cheat sheet formula is unchanged. The Critical share is higher mainly because 1,587 leads (3.2%) are VIP.

## Routing (`src/routing.py`)

| Rule | Behavior |
|---|---|
| Matching | Strict match on Region, Language and Industry Vertical |
| Order | Critical first, then High, Medium, Low. Within a tier: higher score first, VIP, then `Lead_ID`. |
| Critical | Senior with capacity first, then Manager. Never Junior. |
| Other tiers | Any eligible rep (Junior, Senior or Manager) |
| Distribution | Round-robin queue per Region/Language/Industry group. After each assignment a rep moves to the back of the queue until full. |
| Capacity | A rep at `Max_Capacity` leaves the queue. A lead with no eligible rep left goes to Manager Review. |
| Manager Review reasons | `No matching representative`, `No eligible Senior or Manager`, `Eligible representatives at capacity`, `Missing or invalid routing fields`, plus invalid scoring metadata |

### Unknown routing fields

A lead with `Unknown`, missing, or unresolved Region, Language, or Industry Vertical goes to Manager Review with `Missing or invalid routing fields`. This check precedes matching and capacity checks, including for VIP leads. Representatives with unresolved matching fields remain visible but are excluded from assignment with a warning. Two Unknown values do not establish a skill match.

This restores the original routing proposal and replaces PR #12's Unknown-industry matching policy. Missing company size, activity, and VIP status retain their scoring fallbacks; those fields alone do not prevent routing. Fused-region normalization retains the suffix policy described above.

## Why the assignment rate changed during development

Earlier policies produced 35,525 assignments before fused-region resolution, then 40,665 after applying the suffix policy. PR #12 temporarily allowed Unknown industry to match Unknown expertise, increasing assignments to 45,924. Restoring strict industry validation returns the current supplied-scale result to 40,665 assigned (81.33%), with 6,167 leads reviewed for missing/invalid routing fields and 3,168 for exhausted capacity. All 50,000 leads remain traceable; 191 representatives with unresolved skills are retained but excluded. See `docs/routing.md` for measured timings and verification.
