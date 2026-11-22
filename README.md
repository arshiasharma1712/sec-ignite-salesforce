# SEC Ignite Salesforce Challenge

Build an in-memory application that cleans sales lead and representative CSVs, scores leads, routes them to eligible representatives, and displays a manager dashboard.

## Start here

1. Read AGENTS.md and the challenge reference files in docs/.
2. Claim a task in Issues and agree on shared interfaces and the technology stack.
3. Clone this private repository using your own authorized GitHub account.
4. Create a feature branch for your issue. Each simultaneous agent needs its own clone or worktree.
5. Open a pull request describing changes, assumptions, and test results. The integration owner reviews and merges.

```sh
git clone https://github.com/Apickle47/sec-ignite-salesforce.git
cd sec-ignite-salesforce
git switch -c feature/your-task
```

## Project status

The Python pipeline and Streamlit dashboard support sample and scale runs, manager review, and capacity tracking.

## Run the dashboard

Python 3.12 is the tested environment. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Use **Run Sample**, **Run Scale**, or **Live link** to load results. **Reset** clears the run; the next run reads baseline capacities again.

The **Ask Assistant** sidebar explains the program and answers questions about current results using Google Gemini. It is optional: the dashboard works without an API key. Set `GEMINI_API_KEY` in the server environment or `.streamlit/secrets.toml` (ignored by Git). `GEMINI_MODEL` is optional; its default is `gemini-4-hydrogen`. See [assistant setup, behavior, and validation](docs/assistant.md) for configuration and examples.

```sh
python -m pytest -q
```

## Lead Scoring

The scoring module (`src/scoring.py`) calculates lead scores based
on company size, recent activity, and industry.

VIP referrals automatically receive 100 points and CRITICAL priority.

### Scoring Rules

| Category | Condition | Points |
|---|---|---|
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

- CRITICAL: 85–100
- HIGH: 60–84
- MEDIUM: 40–59
- LOW: 0–39

### Main Functions

- `score_lead()` - Scores one lead.
- `score_leads()` - Scores multiple leads and preserves original fields.
- `sort_for_routing()` - Sorts leads by priority, score, VIP status, and Lead ID.

### Testing

Run:

python -m pytest tests/test_scoring.py -v

Result: 151 tests passed locally.

## Deliverables

- Working software with local setup instructions.
- Automated tests for edge cases and routing rules.
- Ten-minute presentation including a live demonstration, followed by five minutes of Q&A.
- One or two system blueprint slides explaining data flow.
- Actual scale performance measurements.

Deadline in the supplied prompt is November 21, 2026 at 10 PM CST.

## Required dashboard

Run sample dataset, run scale dataset, reset state, prioritized lead results, visible Manager Review queue, operational KPIs, and representative capacity tracking.

## Judging weights

Core logic 25; scale/performance 20; resilience 15; dashboard 20; presentation/blueprint 20.

## Access

This repository is private. Teammates need collaborator access and each coding agent must use an account or integration authorized to access this repository. Connecting an agent does not automatically share conversation history. Record decisions in issues and repository files.
