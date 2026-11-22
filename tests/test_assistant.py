from copy import deepcopy
from io import BytesIO
import json
from urllib import error

import pytest

from src import assistant as A


def text_response(text="Here is the explanation."):
    return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


def test_program_question_without_data_and_followup_history_are_bounded():
    seen = []
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(30)]
    def send(payload, key):
        seen.append(deepcopy(payload))
        assert key == "fake-key"
        return text_response()
    answer = A.answer_question("How are VIPs handled?", history, None, api_key="fake-key", transport=send)
    payload = seen[0]
    context = json.loads(payload["input"][0]["content"][0]["text"])
    assert not context["current_snapshot"]["loaded"]
    assert len(context["conversation_for_followups"]) == A.MAX_MESSAGES
    assert context["conversation_for_followups"][0]["content"] == "10"
    assert payload["store"] is False and payload["model"] == A.DEFAULT_MODEL
    assert "previous_interaction_id" not in payload
    assert "Scoring rules" in answer["sources"] and answer["answer"]
    assert len(history) == 30


def test_tool_roundtrip_preserves_opaque_steps_and_uses_live_data(assistant_results):
    assistant_results["reps"][0]["current_capacity"] = 2
    original = deepcopy(assistant_results)
    initial_steps = [
        {"type": "thought", "signature": "opaque-signature", "content": [{"type": "text", "text": "private thought"}]},
        {"type": "function_call", "id": "call-1", "name": "query_reps", "arguments": {"filters": {"eligible": True, "min_remaining": 1}}},
        {"type": "function_call", "id": "call-2", "name": "lookup_record", "arguments": {"entity": "lead", "identifier": "L-2"}},
    ]
    seen = []
    def send(payload, key):
        seen.append(deepcopy(payload))
        return {"steps": deepcopy(initial_steps)} if len(seen) == 1 else text_response("R-1 has one available slot.")
    answer = A.answer_question("Who has capacity? And why is L-2 in review?", [], assistant_results, "Sample",
                              api_key="fake", transport=send)
    assert len(seen) == 2
    assert seen[1]["input"][1:4] == initial_steps
    results = seen[1]["input"][4:]
    assert [step["call_id"] for step in results] == ["call-1", "call-2"]
    reps = json.loads(results[0]["result"][0]["text"])
    assert reps["total_matches"] == 1 and reps["rows"][0]["remaining"] == 1
    lead = json.loads(results[1]["result"][0]["text"])["rows"][0]
    assert lead["reason"] == "Missing or invalid routing fields" and lead["vip"]
    assert "Sample: representative query" in answer["sources"]
    assert "private thought" not in answer["answer"]
    assert assistant_results == original


def test_fresh_question_replaces_stale_snapshot_even_with_followup_text(assistant_results):
    seen = []
    def send(payload, key):
        seen.append(deepcopy(payload))
        return text_response()
    A.answer_question("How many?", [], assistant_results, api_key="fake", transport=send)
    assistant_results["leads"][1].update(assignment_status="Handled", manual="handled")
    A.answer_question("And now?", [{"role": "assistant", "content": "There were two in review."}],
                      assistant_results, api_key="fake", transport=send)
    counts = [json.loads(p["input"][0]["content"][0]["text"])["current_snapshot"]["manager_review"] for p in seen]
    assert counts == [2, 1] and all(len(p["input"]) == 1 for p in seen)


@pytest.mark.parametrize("name,arguments", [("assign_lead", {}), ("query_leads", {"limit": 50000})])
def test_bad_or_mutating_tools_return_errors_and_cannot_change_results(assistant_results, name, arguments):
    baseline = deepcopy(assistant_results)
    seen = []
    def send(payload, key):
        seen.append(deepcopy(payload))
        if len(seen) == 1:
            return {"steps": [{"type": "function_call", "id": "bad", "name": name, "arguments": arguments}]}
        assert "error" in json.loads(payload["input"][-1]["result"][0]["text"])
        return text_response("I can only answer questions using read-only lookups.")
    A.answer_question("Assign L-1", [], assistant_results, api_key="fake", transport=send)
    assert assistant_results == baseline


@pytest.mark.parametrize("changes,match", [({"api_key": ""}, "configured"), ({"model": "bad/model"}, "model"),
                                        ({"question": ""}, "question"), ({"question": "x" * 2001}, "question")])
def test_invalid_configuration_or_question_never_sends(changes, match):
    def send(*args):
        pytest.fail("Network must not be called")
    args = dict(question="Explain routing", history=[], results=None, api_key="fake", transport=send)
    args.update(changes)
    with pytest.raises(A.AssistantError, match=match):
        A.answer_question(**args)


@pytest.mark.parametrize("response", [None, {}, {"steps": None}, {"steps": [None]},
    {"steps": [{"type": "model_output", "content": None}]}, {"steps": []},
    {"steps": [{"type": "thought", "content": [{"type": "text", "text": "Never display"}]}]},
    {"steps": [{"type": "function_call", "name": "get_summary"}]},
    {"steps": [{"type": "function_call", "id": str(i), "name": "get_summary", "arguments": {}} for i in range(5)]}])
def test_bad_or_empty_provider_response_is_safe(response):
    with pytest.raises(A.AssistantError):
        A.answer_question("Explain", [], None, api_key="fake", transport=lambda *_: response)


def test_lookup_loop_and_answer_length_are_bounded():
    calls = []
    def send(*args):
        calls.append(1)
        return {"steps": [{"type": "function_call", "id": str(len(calls)), "name": "get_summary", "arguments": {}}]}
    with pytest.raises(A.AssistantError, match="lookup limit"):
        A.answer_question("Explain", [], None, api_key="fake", transport=send)
    assert len(calls) == A.MAX_API_CALLS
    result = A.answer_question("Explain", [], None, api_key="fake", transport=lambda *_: text_response("x" * 10000))
    assert len(result["answer"]) < A.MAX_ANSWER + 100 and "shortened" in result["answer"]


def test_rest_headers_timeout_and_no_stored_interaction(monkeypatch):
    def urlopen(req, timeout):
        assert req.full_url == A.ENDPOINT and req.method == "POST"
        headers = {key.lower(): value for key, value in req.headers.items()}
        assert headers["x-goog-api-key"] == "fake"
        assert headers["api-revision"] == A.API_REVISION
        assert timeout == A.TIMEOUT_SECONDS
        assert json.loads(req.data)["store"] is False
        return BytesIO(json.dumps(text_response()).encode())
    monkeypatch.setattr(A.request, "urlopen", urlopen)
    assert A.answer_question("Explain", [], None, api_key="fake")["answer"]


@pytest.mark.parametrize("code,message", [(401, "access was denied"), (403, "access was denied"),
                                        (429, "usage limit"), (400, "rejected"), (404, "rejected"), (500, "unavailable")])
def test_http_errors_never_expose_provider_body_or_key(monkeypatch, code, message):
    def fail(*args, **kwargs):
        raise error.HTTPError(A.ENDPOINT, code, "sensitive-provider-details", {}, BytesIO(b"fake-secret"))
    monkeypatch.setattr(A.request, "urlopen", fail)
    with pytest.raises(A.AssistantError, match=message) as captured:
        A.answer_question("Explain", [], None, api_key="fake-secret")
    assert "fake-secret" not in str(captured.value) and "sensitive-provider" not in str(captured.value)


@pytest.mark.parametrize("problem", [TimeoutError("secret"), error.URLError("secret")])
def test_network_errors_are_recoverable(monkeypatch, problem):
    def fail(*args, **kwargs):
        raise problem
    monkeypatch.setattr(A.request, "urlopen", fail)
    with pytest.raises(A.AssistantError, match="connection"):
        A.answer_question("Explain", [], None, api_key="fake")


@pytest.mark.parametrize("body", [b"not json", b"[]", b"x" * (A.MAX_RESPONSE_BYTES + 1)])
def test_unreadable_or_oversized_http_response(monkeypatch, body):
    monkeypatch.setattr(A.request, "urlopen", lambda *args, **kwargs: BytesIO(body))
    with pytest.raises(A.AssistantError):
        A.answer_question("Explain", [], None, api_key="fake")


def test_request_size_limit_prevents_transport_call():
    def send(*args):
        pytest.fail("Oversized context must not be sent")
    history = [{"role": "assistant", "content": "💬" * A.MAX_ANSWER}] * A.MAX_MESSAGES
    with pytest.raises(A.AssistantError, match="too much context"):
        A.answer_question("Explain", history, None, api_key="fake", transport=send)
