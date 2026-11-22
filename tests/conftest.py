import pytest


@pytest.fixture
def assistant_results():
    """Small dashboard-shaped run, including distinct review causes and an excluded rep."""
    lead = dict(company="Acme", region="Europe", language="English", industry="Technology",
                company_size=1000, activity="Requested Live Demo", vip=False, score=100,
                priority="Critical", assignment_status="Assigned", rep_id="R-1", reason="")
    rep = dict(name="Alex", region="Europe", language="English", industry="Technology",
               seniority="Senior", current_capacity=1, max_capacity=3)
    return {
        "leads": [
            dict(lead, lead_id="L-1"),
            dict(lead, lead_id="L-2", industry="Unknown", vip=True, rep_id="",
                 assignment_status="Manager Review", reason="Missing or invalid routing fields"),
            dict(lead, lead_id="L-3", score=60, priority="High", company_size=100, activity="Attended Webinar",
                 industry="Finance", rep_id="", assignment_status="Manager Review", reason="All matching representatives at capacity"),
            dict(lead, lead_id="L-4", assignment_status="Handled", manual="handled", rep_id="",
                 reason="Marked as handled by a manager"),
        ],
        "reps": [dict(rep, rep_id="R-1"), dict(rep, rep_id="R-2", seniority="Manager", current_capacity=3),
                 dict(rep, rep_id="R-3", industry="Unknown", current_capacity=0, max_capacity=100)],
        "warnings": [], "metrics": {},
    }
