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

### Unknown industry (assumption)

A lead with industry `Unknown` matches only reps whose expertise is `Unknown`. The challenge requires strict matching and does not say what to do with Unknown, so this is our documented choice. The alternative is to send every Unknown-industry lead to Manager Review. About 5,259 of 45,924 assignments depend on this choice. It is one line in `src/routing.py` (`_INDUSTRIES`).

### Unknown region or language

These never match anything. The lead goes to Manager Review.

## Why the assignment rate changed during development

Strictly matching only fully readable values gave 35,525 of 50,000 leads assigned (71.0%). Reading fused regions raised that to 40,665. Matching Unknown industry to Unknown expertise raised it to 45,924 (91.85%). Those two policies account for the entire increase. A higher rate comes from looser matching, not from a bug fix.
