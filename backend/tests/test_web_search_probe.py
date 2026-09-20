from __future__ import annotations

import pytest

from app.jobs.test_web_search import (
    ERROR,
    FAIL_RESPONSES,
    FAIL_TOOL,
    PASS,
    UNKNOWN,
    Attempt,
    collect_evidence,
    decide,
    model_list_url,
    responses_url,
)


def test_responses_url_tolerates_trailing_slash() -> None:
    assert responses_url("https://api.example.com/v1") == "https://api.example.com/v1/responses"
    assert responses_url("https://api.example.com/v1/") == "https://api.example.com/v1/responses"
    assert responses_url("https://api.example.com/v1/responses") == "https://api.example.com/v1/responses"


def test_model_list_url_uses_the_same_base() -> None:
    assert model_list_url("https://api.example.com/v1") == "https://api.example.com/v1/models"
    assert model_list_url("https://api.example.com/v1/models") == "https://api.example.com/v1/models"


def responses_payload(**kwargs) -> dict:
    payload = {
        "object": "response",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "过去 24 小时的 AI 新闻如下。"}],
            }
        ],
    }
    payload.update(kwargs)
    return payload


def test_web_search_call_is_evidence() -> None:
    payload = {
        "output": [
            {"type": "web_search_call", "status": "completed", "action": {"query": "AI news today"}},
            responses_payload()["output"][0],
        ]
    }
    evidence = collect_evidence(payload)
    assert evidence.calls
    assert "AI news today" in evidence.calls[0]
    assert evidence.found
    assert decide(Attempt(status_code=200, payload=payload, parsed=True), evidence)[0] == PASS


def test_url_citation_annotation_is_evidence() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "OpenAI 发布新模型。",
                        "annotations": [
                            {"type": "url_citation", "url": "https://openai.com/news/x", "title": "OpenAI News"}
                        ],
                    }
                ],
            }
        ]
    }
    evidence = collect_evidence(payload)
    assert evidence.citations == ["https://openai.com/news/x"]
    assert decide(Attempt(status_code=200, payload=payload, parsed=True), evidence)[0] == PASS


def test_the_echoed_tool_declaration_is_not_evidence() -> None:
    """The request echo shows the tool we asked for, not a search that ran."""
    payload = responses_payload()
    payload["tools"] = [{"type": "web_search"}]
    payload["tool_choice"] = "auto"
    evidence = collect_evidence(payload)
    assert not evidence.calls
    assert not evidence.citations
    assert decide(Attempt(status_code=200, payload=payload, parsed=True), evidence)[0] == UNKNOWN


def test_answer_without_traces_is_unknown_not_pass() -> None:
    payload = responses_payload()
    evidence = collect_evidence(payload)
    assert evidence.text
    assert not evidence.found
    verdict, detail = decide(Attempt(status_code=200, payload=payload, parsed=True), evidence)
    assert verdict == UNKNOWN
    assert "no search evidence" in detail or "proves a search ran" in detail


def test_404_means_the_responses_api_is_absent() -> None:
    attempt = Attempt(status_code=404, payload=None, parsed=False)
    assert decide(attempt, collect_evidence(None))[0] == FAIL_RESPONSES


def test_unsupported_tool_error_means_the_tool_is_absent() -> None:
    payload = {"error": {"message": "Unsupported tool type: web_search", "type": "invalid_request_error"}}
    attempt = Attempt(status_code=400, payload=payload, parsed=True)
    assert decide(attempt, collect_evidence(payload))[0] == FAIL_TOOL


def test_a_bad_model_is_not_blamed_on_the_tool() -> None:
    payload = {"error": {"message": "The model `nope` does not exist", "type": "invalid_request_error"}}
    attempt = Attempt(status_code=404, payload=payload, parsed=True)
    verdict, detail = decide(attempt, collect_evidence(payload))
    assert verdict == FAIL_RESPONSES
    assert "does not exist" in detail


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_are_reported_as_an_error(status: int) -> None:
    payload = {"error": {"message": "Invalid API key"}}
    verdict, detail = decide(Attempt(status_code=status, payload=payload, parsed=True), collect_evidence(payload))
    assert verdict == ERROR
    assert "API key" in detail


def test_transport_failure_is_reported_as_an_error() -> None:
    attempt = Attempt(status_code=None, transport_error="timed out after 60s")
    verdict, detail = decide(attempt, collect_evidence(None))
    assert verdict == ERROR
    assert "timed out" in detail


def test_non_json_success_is_unknown() -> None:
    attempt = Attempt(status_code=200, payload=None, raw_text="<html>hello</html>", parsed=False)
    verdict, _ = decide(attempt, collect_evidence(None))
    assert verdict == UNKNOWN


def test_chat_completions_shape_also_yields_text() -> None:
    payload = {"choices": [{"message": {"role": "assistant", "content": "联网不可用。"}}]}
    evidence = collect_evidence(payload)
    assert evidence.text == "联网不可用。"
    assert decide(Attempt(status_code=200, payload=payload, parsed=True), evidence)[0] == UNKNOWN
