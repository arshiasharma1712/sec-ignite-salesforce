# SEC Ignite 2026 — Salesforce Lead Prioritization

**The Right Lead, to the Right Rep, at the Right Time**

A Python-based lead prioritization and routing application developed for the **2026 SEC Ignite Salesforce Design Challenge**.

Our application transforms messy sales lead and representative CSV files into an organized, prioritized sales pipeline. It cleans incoming data, scores leads based on business rules, assigns them to eligible representatives, and provides an interactive manager dashboard built with Streamlit.

The solution focuses on **routing accuracy, scalability, transparency, and usability**, ensuring that every lead is accounted for.

## 1. Key Features

- **Data Cleaning and Validation:** Standardizes inconsistent CSV values, handles missing information, and validates required fields.
- **Lead Scoring:** Calculates numerical scores using company size, recent activity, industry, and VIP referral status.
- **Priority Classification:** Categorizes leads into Critical, High, Medium, and Low.
- **Rule-Based Routing:** Matches leads with representatives based on region, language, industry expertise, seniority, and capacity.
- **Fair Lead Distribution:** Uses round-robin assignment among eligible representatives.
- **Manager Review:** Preserves unassigned leads and displays the reason for manual review.
- **Interactive Dashboard:** Displays prioritized leads, assignment results, representative utilization, and operational metrics.
- **Large-Scale Processing:** Supports datasets containing up to 50,000 leads and 1,600 representatives in the provided challenge workloads.
- **Automated Testing:** Validates scoring, routing, normalization, capacity constraints, and edge cases.

## 2. System Architecture

The application uses a modular, rule-based processing pipeline.

```text
              CSV Input Files
                     |
                     v
          Data Loading & Validation
                     |
                     v
           Data Normalization
                     |
                     v
              Lead Scoring
                     |
                     v
            Priority Sorting
                     |
                     v
            Rule-Based Routing
                     |
              +------+------+
              |             |
              v             v
           Assigned     Manager Review
              |             |
              +------+------+
                     |
                     v
             Streamlit Dashboard
                     |
                     v
          Lead & Capacity Monitoring
```

### Core Components

| File | Responsibility |
|---|---|
| `src/data_loader.py` | Loads CSV files and validates required columns |
| `src/normalize.py` | Cleans and standardizes lead and representative data |
| `src/scoring.py` | Calculates scores and priority classifications |
| `src/routing.py` | Matches leads to eligible representatives |
| `src/pipeline.py` | Coordinates data processing |
| `src/dashboard_adapter.py` | Connects pipeline results to the dashboard |
| `src/dashboard_helpers.py` | Provides dashboard display and interaction helpers |
| `app.py` | Main Streamlit dashboard application |

The separation of components makes the application easier to maintain, test, and extend.

## 3. Installation and Setup

### Prerequisites

- Python 3.12 or a compatible Python version
- Git
- pip

### Step 1 — Clone the Repository

```bash
git clone https://github.com/Apickle47/sec-ignite-salesforce.git
cd sec-ignite-salesforce
```

Repository access is required because the project is hosted in a private GitHub repository.

### Step 2 — Create a Virtual Environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3 — Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### Step 4 — Run the Dashboard

```bash
python -m streamlit run app.py
```

Open the local URL displayed in the terminal, typically:

`http://localhost:8501`

## 4. Data Loading and Normalization

The application processes two types of input files:

- **Leads CSV:** Contains lead information, including company details, region, language, industry, recent activity, and VIP referral status.
- **Representatives CSV:** Contains representative information, including region, language, industry expertise, seniority, and capacity.

### CSV Validation

The data loader:

- Matches column names without case sensitivity.
- Trims unnecessary whitespace from headers.
- Handles UTF-8 byte order marks.
- Skips empty rows.
- Handles incomplete rows and extra cells.
- Raises clear errors when required columns are missing.

### Data Cleaning

The normalization module prepares incoming records for scoring and routing.

It handles:

- Inconsistent capitalization and formatting.
- Recognized aliases for regions, languages, and industries.
- Missing or invalid company sizes.
- Inconsistent recent activity values.
- VIP referral normalization.
- Invalid representative capacity values.
- Missing or unknown routing information.

Invalid or unresolved information is handled using documented rules rather than silently discarding records.

For detailed assumptions, see `docs/data-assumptions.md`.

## 5. Lead Scoring and Prioritization

The scoring engine assigns a score based on company size, recent activity, and industry vertical.

### Scoring Rules

| Category | Condition | Points |
|---|---|---:|
| Company Size | 1,000+ employees | 50 |
| Company Size | 100–999 employees | 30 |
| Company Size | 1–99 employees | 0 |
| Company Size | Missing or invalid | 20 |
| Recent Activity | Requested Live Demo / Contact Sales | 35 |
| Recent Activity | Attended Webinar | 25 |
| Recent Activity | Downloaded Whitepaper | 15 |
| Recent Activity | Visited Pricing Page | 5 |
| Industry | Technology | 15 |
| Industry | Healthcare / Finance | 10 |
| Industry | Manufacturing / Retail | 0 |

### Priority Levels

| Score | Priority |
|---|---|
| 85–100 | Critical |
| 60–84 | High |
| 40–59 | Medium |
| 0–39 | Low |

### VIP Override

VIP referrals automatically receive a score of **100** and **Critical** priority, regardless of their other scoring attributes.

### Processing Order

Leads are prioritized using their classification, score, and VIP status before routing.

This ensures that higher-priority leads are considered first.

## 6. Rule-Based Routing

After scoring, the routing engine identifies eligible representatives based on five constraints.

### Matching Criteria

1. **Region:** The representative must match the lead's region.
2. **Language:** The representative must support the lead's language.
3. **Industry Expertise:** The representative must match the lead's industry.
4. **Seniority:** The representative must satisfy priority-based seniority requirements.
5. **Capacity:** The representative must have available capacity.

### Critical Lead Routing

Critical leads follow a specific seniority hierarchy:

1. Eligible Senior representatives are considered first.
2. If eligible Seniors are at capacity, eligible Managers are considered.
3. Critical leads are never automatically assigned to Junior representatives.

### Round-Robin Assignment

When multiple eligible representatives are available, the system uses round-robin assignment to distribute leads fairly.

Representative capacities are updated as assignments occur.

### Capacity Enforcement

Each representative has a maximum lead capacity.

The routing engine prevents assignments that would exceed this limit.

## 7. Manager Review and Fallback Handling

Not every lead can be assigned automatically.

When routing is unsuccessful, the lead is preserved in a dedicated **Manager Review** queue.

Possible review reasons include:

- No representative satisfies the matching requirements.
- Eligible representatives have reached maximum capacity.
- Required routing information remains invalid or unresolved.

The dashboard displays the reason for each unassigned lead so managers can determine the next action.

**No lead is silently discarded during routing.**

## 8. Interactive Streamlit Dashboard

The dashboard provides a centralized interface for viewing lead assignments and representative workloads.

### Dataset Controls

- **Run Sample:** Processes the provided sample dataset.
- **Run Scale:** Processes the provided large-scale dataset.
- **Reset:** Clears pipeline outputs and allows a fresh run using baseline capacities.

### Lead Queue

The lead queue displays:

- Lead ID
- Company name
- Priority
- Lead score
- Region and industry
- Assignment status
- Assigned representative
- Review reason, when applicable

Users can search, filter, sort, and inspect lead information.

### Manager Review Queue

The Manager Review interface provides:

- Unassigned lead counts
- Priority-ordered review results
- Recorded reasons for review
- Filtering and search
- Individual lead details

### Representative Capacity Tracking

The dashboard also displays representative workload information to help managers identify capacity constraints and assignment distribution.

### Additional Dashboard Features

- Interactive tables
- Pagination
- Lead details
- Editable lead information
- CSV export
- Operational KPI summaries

See `docs/dashboard.md` for additional dashboard documentation.

## 9. Scalability and Performance

The application supports the two datasets provided for the challenge.

| Dataset | Leads | Representatives |
|---|---:|---:|
| Sample | 100 | 10 |
| Scale | 50,000 | 1,600 |

### Large-Scale Pipeline Results

The following results were obtained during a previously verified run of the 50,000-lead dataset.

| Metric | Result |
|---|---:|
| Total Leads | 50,000 |
| Successfully Assigned | 45,924 |
| Manager Review | 4,076 |
| Assignment Rate | 91.85% |
| Manager Review Rate | 8.15% |
| Representative Warnings | 0 |

All 50,000 leads were accounted for.

The 4,076 leads in Manager Review were reported as unassigned because eligible representatives had reached maximum capacity.

### Execution Time

A previous complete pipeline execution processed the 50,000-lead dataset in approximately **2.49 seconds**.

Execution time may vary depending on hardware, Python version, and workload.

## 10. Automated Testing

The application uses **pytest** to validate individual components and integrated pipeline behavior.

### Run All Tests

```bash
python -m pytest -q
```

### Run Specific Tests

**Scoring:**

```bash
python -m pytest tests/test_scoring.py -v
```

**Routing:**

```bash
python -m pytest tests/test_routing.py -v
```

**Normalization:**

```bash
python -m pytest tests/test_normalize.py -v
```

**Pipeline:**

```bash
python -m pytest tests/test_pipeline.py -v
```

### Test Coverage Areas

- VIP override behavior
- Scoring boundaries
- Missing and invalid values
- Priority classification
- Region matching
- Language matching
- Industry matching
- Seniority restrictions
- Representative capacity limits
- Round-robin distribution
- Manager Review handling
- Duplicate and malformed records
- Pipeline integration
- Large-scale performance

The test suite covers both normal processing and edge cases.

## 11. Project Structure

```text
sec-ignite-salesforce/
|
|-- app.py
|-- README.md
|-- requirements.txt
|
|-- data/
|   |-- leads_sample.csv
|   |-- reps_sample.csv
|   |-- leads_scale.csv
|   |-- reps_scale.csv
|
|-- src/
|   |-- data_loader.py
|   |-- normalize.py
|   |-- scoring.py
|   |-- routing.py
|   |-- pipeline.py
|   |-- dashboard_adapter.py
|   |-- dashboard_helpers.py
|
|-- tests/
|   |-- test_scoring.py
|   |-- test_routing.py
|   |-- test_normalize.py
|   |-- test_pipeline.py
|   |-- ...
|
|-- docs/
|   |-- data-assumptions.md
|   |-- dashboard.md
|   |-- ...
```

## 12. Design Decisions and Tradeoffs

### Rule-Based Decision Making

The system uses explicit business rules for scoring and routing.

This makes decisions explainable, consistent, and testable.

### Accuracy Over Assignment Volume

Routing correctness takes priority over maximizing the assignment rate.

Leads without eligible representatives are sent to Manager Review rather than being assigned to incompatible representatives.

### In-Memory Processing

The prototype processes data in memory without requiring a database.

This reduces setup complexity and allows the application to handle the provided sample and scale datasets.

### Modular Architecture

Data loading, normalization, scoring, routing, and presentation are implemented as separate components.

This supports independent testing and easier maintenance.

### Transparent Fallbacks

Missing information, capacity limits, and unsuccessful routing decisions are handled through explicit rules and visible review outcomes.

## 13. Team Contributions

| Team Member | Responsibility |
|---|---|
| Arush | Data loading and normalization |
| Arshia | Lead scoring and prioritization |
| Ethan | Routing and capacity management |
| Hamsini | Streamlit dashboard |
| Nihitha | Pipeline integration and testing |

The team collaborated using GitHub branches, pull requests, and automated testing.

## 14. Challenge Deliverables

The project was developed for the **2026 SEC Ignite Salesforce Design Challenge**.

Deliverables include:

- Working lead prioritization and routing software
- Streamlit manager dashboard
- Setup and execution instructions
- Automated tests
- Performance and scalability results
- System architecture blueprint
- Closing presentation with a live demonstration

The challenge specifies a **10-minute presentation**, including the live demo, followed by **5 minutes of Q&A**.

---

**SEC Ignite 2026 — Salesforce Lead Prioritization**

*The Right Lead, to the Right Rep, at the Right Time*