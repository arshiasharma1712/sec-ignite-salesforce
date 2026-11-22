from copy import deepcopy
import json
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from src import assistant as A
from src import assistant_ui as UI
from src import dashboard_helpers as H

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def chat_app(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(st, "secrets", {})
    requests = []
    def send(payload, key):
        assert key == "test-key"
        requests.append(deepcopy(payload))
        return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "Test explanation."}]}]}
    monkeypatch.setattr(A, "_post_gemini", send)
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    assert not app.exception
    return app, requests


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def ask(app, question):
    app.chat_input(key="assistant_input").set_value(question).run()
    assert not app.exception


def test_sidebar_works_before_data_and_keeps_followup_history(chat_app):
    app, requests = chat_app
    assert app.sidebar.subheader[0].value == "Ask Assistant"
    assert not app.chat_input[0].disabled
    click(app, "Explain the program")
    assert len(app.session_state[UI.HISTORY_KEY]) == 2 and len(requests) == 1
    assert len(app.sidebar.chat_message) == 2
    ask(app, "And what about VIPs?")
    context = json.loads(requests[-1]["input"][0]["content"][0]["text"])
    assert len(context["conversation_for_followups"]) == 2
    assert not context["current_snapshot"]["loaded"]
    app.run()
    assert len(requests) == 2  # widget redraws must not resend a question
    click(app, "Clear chat")
    assert not app.session_state[UI.HISTORY_KEY] and not app.sidebar.chat_message


def test_navigation_retains_chat_manual_actions_are_fresh_and_runs_reset(chat_app):
    app, requests = chat_app
    click(app, "▶ Run Sample")
    ask(app, "Summarize this run")
    first = json.loads(requests[-1]["input"][0]["content"][0]["text"])["current_snapshot"]
    assert first["total_leads"] == 100
    for tab in ("Lead Queue", "Manager Review", "Rep Capacity", "Overview"):
        app.radio(key="tab").set_value(tab).run()
        assert not app.exception and len(app.session_state[UI.HISTORY_KEY]) == 2
    assert len(requests) == 1
    results = app.session_state["results"]
    review = next(lead for lead in results["leads"] if H.is_waiting(lead))
    H.mark_handled(review)
    ask(app, "How many need review now?")
    updated = json.loads(requests[-1]["input"][0]["content"][0]["text"])["current_snapshot"]
    assert updated["manager_review"] == first["manager_review"] - 1 and updated["handled"] == 1
    click(app, "▶ Run Scale")
    assert not app.session_state[UI.HISTORY_KEY]
    ask(app, "Summarize the scale run")
    scale = json.loads(requests[-1]["input"][0]["content"][0]["text"])["current_snapshot"]
    assert scale["total_leads"] == 50000 and scale["total_reps"] == 1600
    assert len(A._encode(requests[-1])) < 20000
    click(app, "↺ Reset")
    assert not app.session_state[UI.HISTORY_KEY] and "results" not in app.session_state


def test_error_retry_has_no_duplicate_question_and_dashboard_remains_usable(chat_app, monkeypatch):
    app, requests = chat_app
    original_send = A._post_gemini
    def fail(*args):
        raise A.AssistantError("Gemini's usage limit was reached. Retry shortly.")
    monkeypatch.setattr(A, "_post_gemini", fail)
    ask(app, "Why is L-1 in review?")
    assert len(app.session_state[UI.HISTORY_KEY]) == 1
    assert any("usage limit" in item.value for item in app.error)
    monkeypatch.setattr(A, "_post_gemini", original_send)
    click(app, "Retry question")
    assert len(app.session_state[UI.HISTORY_KEY]) == 2 and not app.error
    assert len(requests) == 1
    monkeypatch.setattr(A, "_post_gemini", fail)
    ask(app, "Another question")
    assert len(app.session_state[UI.HISTORY_KEY]) == 3
    monkeypatch.setattr(A, "_post_gemini", original_send)
    ask(app, "A replacement question")
    assert len(app.session_state[UI.HISTORY_KEY]) == 4
    assert app.session_state[UI.HISTORY_KEY][-2]["content"] == "A replacement question"
    click(app, "▶ Run Sample")
    assert len(app.session_state["results"]["leads"]) == 100 and not app.error


def test_chat_session_retention_limit_including_pending_failure(chat_app, monkeypatch):
    app, _ = chat_app
    app.session_state[UI.HISTORY_KEY] = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(20)]
    ask(app, "New question")
    history = app.session_state[UI.HISTORY_KEY]
    assert len(history) == 20 and history[0]["content"] == "2"
    def fail(*args):
        raise RuntimeError("private-provider-error")
    monkeypatch.setattr(A, "_post_gemini", fail)
    ask(app, "One more question")
    assert len(app.session_state[UI.HISTORY_KEY]) == 19
    assert "private-provider-error" not in app.error[0].value


def test_missing_key_does_not_block_sample_run(chat_app, monkeypatch):
    app, requests = chat_app
    monkeypatch.delenv("GEMINI_API_KEY")
    app.run()
    assert app.chat_input[0].disabled
    assert any("not configured" in info.value for info in app.info)
    click(app, "▶ Run Sample")
    assert len(app.session_state["results"]["leads"]) == 100 and not requests


def test_configuration_reads_environment_before_secrets(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"GEMINI_API_KEY": "secret-key", "GEMINI_MODEL": "test-model"})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert UI._setting("GEMINI_API_KEY") == "secret-key"
    monkeypatch.setenv("GEMINI_API_KEY", " environment-key ")
    assert UI._setting("GEMINI_API_KEY") == "environment-key"
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert UI._setting("GEMINI_MODEL", A.DEFAULT_MODEL) == "test-model"


def test_dialog_edit_updates_chat_counts_and_capacity(chat_app):
    app, requests = chat_app
    click(app, "▶ Run Sample")
    ask(app, "Summarize this run")
    before = json.loads(requests[-1]["input"][0]["content"][0]["text"])["current_snapshot"]
    lead = next(row for row in app.session_state["results"]["leads"]
                if row["assignment_status"] == "Assigned")
    index = lead["_i"]
    click(app, "✎ Edit mode")
    app.radio(key="tab").set_value("Lead Queue").run()
    app.text_input(key="q_search").set_value(lead["lead_id"]).run()
    app.button(key=f"rowopen_q_{index}").click().run()
    assert not app.exception and len(app.session_state[UI.HISTORY_KEY]) == 2
    region = "Europe" if lead["region"] != "Europe" else "North America"
    app.selectbox(key=f"q_ed_region_{index}").set_value(region)
    app.button(key=f"q_ed_save_{index}").click()
    app.button(key=f"rowopen_q_{index}").click().run()
    assert not app.exception
    ask(app, "What changed after the field edit?")
    after = json.loads(requests[-1]["input"][0]["content"][0]["text"])["current_snapshot"]
    assert after["assigned"] == before["assigned"] - 1
    assert after["manager_review"] == before["manager_review"] + 1
    assert after["capacity_used_all_reps"] == before["capacity_used_all_reps"] - 1
    assert len(app.session_state[UI.HISTORY_KEY]) == 4


def test_live_link_run_clears_chat_and_failed_refresh_retains_it(chat_app, monkeypatch, tmp_path):
    app, requests = chat_app
    downloads = []

    def download(url, target, id_column):
        downloads.append(url)
        filename = "leads_sample.csv" if id_column == "lead_id" else "reps_sample.csv"
        Path(target).write_bytes((APP.parent / "data" / filename).read_bytes())
        return filename

    monkeypatch.setattr(H, "download_csv", download)
    app.session_state["live_dir"] = str(tmp_path)
    app.text_input(key="live_leads_url").set_value("https://example.test/leads.csv")
    app.text_input(key="live_reps_url").set_value("https://example.test/reps.csv")
    ask(app, "Explain the program")
    click(app, "▶ Run from link")
    assert app.session_state["dataset"] == "Live link"
    assert len(app.session_state["results"]["leads"]) == 100
    assert not app.session_state[UI.HISTORY_KEY]
    assert set(downloads) == {"https://example.test/leads.csv", "https://example.test/reps.csv"}
    ask(app, "Summarize the live run")
    history = deepcopy(app.session_state[UI.HISTORY_KEY])

    def fail(*args):
        raise ValueError("The CSV link could not be read.")

    monkeypatch.setattr(H, "download_csv", fail)
    click(app, "▶ Run from link")
    assert any("CSV link could not be read" in item.value for item in app.error)
    assert app.session_state[UI.HISTORY_KEY] == history
    assert len(app.session_state["results"]["leads"]) == 100
    assert len(requests) == 2


def test_invalid_or_missing_secrets_are_nonfatal(monkeypatch):
    class BadSecrets:
        def get(self, *args):
            raise RuntimeError("invalid secrets file contents must not appear")
    monkeypatch.setattr(st, "secrets", BadSecrets())
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert UI._setting("GEMINI_API_KEY") == ""
