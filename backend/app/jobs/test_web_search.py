"""Does the configured LLM endpoint really support Web Search?

    cd backend
    uv run python -m app.jobs.test_web_search

This is a diagnostic only. It never touches the database, the collectors, the
refresh pipeline or the scheduler. It reuses the project's existing LLM
configuration (``LLM_ENABLED`` / ``LLM_API_KEY`` / ``LLM_BASE_URL`` /
``LLM_MODEL``) and calls the OpenAI Responses style endpoint
``POST {LLM_BASE_URL}/responses`` with an explicit ``{"type": "web_search"}``
tool. The existing ``/chat/completions`` client is left alone.

An HTTP 200 is not evidence of search. The verdict only becomes "supported" when
the response proves a search actually ran: a ``web_search_call`` item, a
``url_citation`` annotation, or a source URL attached to the answer. A model that
answers a news question from memory - which is exactly what a hosted model
invites - is reported as UNKNOWN, never as PASS.

Exit status: 0 supported, 1 not supported or undecidable, 2 the request could not
be made at all (missing configuration, connection failure, timeout).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx

from app.config.env import load_dotenv
from app.services.llm.settings import LLMSettings, load_llm_settings

PASS = "PASS: Web Search supported"
FAIL_RESPONSES = "FAIL: Responses API not supported"
FAIL_TOOL = "FAIL: web_search tool not supported"
UNKNOWN = "UNKNOWN: request succeeded but no search evidence found"
ERROR = "ERROR: request could not be completed"

DEFAULT_TIMEOUT = 60.0
ANSWER_LIMIT = 4000
BODY_LIMIT = 600

WEB_SEARCH_TOOL: dict[str, str] = {"type": "web_search"}

DEFAULT_QUESTION = (
    "请使用 Web Search 搜索过去 24 小时最新的 3 条 AI 新闻。"
    "每条给出标题、发布时间、来源网站和原始 URL。不要依赖模型已有知识。"
)

# An error body only means "tool unsupported" when it says so. A 400 for a bad
# model name is a different problem and must not be reported as one.
UNSUPPORTED_TOOL_MARKERS = (
    "unsupported",
    "not supported",
    "unknown tool",
    "unrecognized tool",
    "invalid tool",
    "no such tool",
    "tool_not_found",
    "不支持",
)

# Statuses that mean "this path is not usable as an endpoint", as opposed to a
# transport or credential problem.
ENDPOINT_MISSING_STATUSES = (400, 404, 405, 415, 422)


def responses_url(base_url: str) -> str:
    """The Responses endpoint for ``base_url``, tolerating a trailing slash."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/responses"):
        return base
    return f"{base}/responses"


def iter_objects(node: Any) -> Iterator[dict]:
    """Every JSON object inside ``node``, in document order.

    The request echo is skipped: a ``{"type": "web_search"}`` seen in the echoed
    ``tools`` list is the tool we asked for, not proof the provider ran it.
    """
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in {"tools", "tool_choice"}:
                continue
            yield from iter_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_objects(item)


@dataclass
class Evidence:
    """What the response actually proves about Web Search."""

    status: str = ""
    calls: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    text: str = ""

    @property
    def found(self) -> bool:
        return bool(self.calls or self.citations)


def _citation_url(node: dict) -> str:
    nested = node.get("url_citation")
    if isinstance(nested, dict) and isinstance(nested.get("url"), str):
        return nested["url"]
    if isinstance(nested, str):
        return nested
    url = node.get("url")
    if isinstance(url, str):
        return url
    return "(no url)"


def _call_label(node: dict) -> str:
    kind = str(node.get("type") or "search")
    parts = [kind]
    status = node.get("status")
    if isinstance(status, str) and status:
        parts.append(f"status={status}")
    query = node.get("query")
    action = node.get("action")
    if not isinstance(query, str) and isinstance(action, dict):
        query = action.get("query")
    if isinstance(query, str) and query.strip():
        parts.append(f"query={query.strip()[:80]}")
    return " ".join(parts)


def _classify(node: dict) -> tuple[str, str] | None:
    """Label one JSON object as search evidence, or return None."""
    kind = node.get("type")
    if not isinstance(kind, str):
        return None
    key = kind.strip().lower()
    if not key:
        return None
    if "citation" in key:
        return ("citation", _citation_url(node))
    if key == "url" and isinstance(node.get("url"), str):
        return ("citation", node["url"])
    if "search" not in key:
        return None
    # A recorded call carries a status, a query, an action or sources. Anything
    # emptier is a tool declaration, not a call.
    if key.endswith("call") or {"query", "action", "sources", "result", "results"} & set(node):
        return ("call", _call_label(node))
    return ("weak", _call_label(node))


def extract_text(payload: Any) -> str:
    """The model's final answer, from either API shape."""
    if not isinstance(payload, dict):
        return ""

    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            if message["content"].strip():
                return message["content"].strip()

    parts: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for block in output:
            if not isinstance(block, dict):
                continue
            content = block.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for piece in content:
                    if isinstance(piece, dict) and isinstance(piece.get("text"), str):
                        parts.append(piece["text"])
            elif isinstance(block.get("text"), str):
                parts.append(block["text"])
    if parts:
        return "\n".join(part.strip() for part in parts if part.strip()).strip()

    for key in ("output_text", "text", "answer", "response"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def collect_evidence(payload: Any) -> Evidence:
    """Gather the search traces in one response body."""
    evidence = Evidence()
    if not isinstance(payload, dict):
        return evidence
    status = payload.get("status")
    if isinstance(status, str):
        evidence.status = status

    # When the API returns a messages list, that is the authoritative place for
    # the answer and its annotations; a bare 200 with text only stays UNKNOWN.
    scope: Any = payload.get("output") if isinstance(payload.get("output"), list) else payload
    for node in iter_objects(scope):
        verdict = _classify(node)
        if verdict is None:
            continue
        kind, value = verdict
        if kind == "citation" and value not in evidence.citations:
            evidence.citations.append(value)
        elif kind == "call" and value not in evidence.calls:
            evidence.calls.append(value)
        elif kind == "weak" and value not in evidence.weak:
            evidence.weak.append(value)

    evidence.text = extract_text(payload)
    return evidence


CAPABILITY_KEYS = ("capab", "feature", "tool", "search", "ground", "web", "support")
CAPABILITY_VALUE_LIMIT = 200


def model_list_url(base_url: str) -> str:
    """The model listing endpoint, where a gateway publishes its capabilities."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def describe_capabilities(payload: Any, model: str) -> list[str]:
    """The capabilities the provider declares for ``model``, if it declares any.

    Only keys that talk about capability, tools or search are reported: a listing
    of model names is not an answer about Web Search.
    """
    entries: list[dict] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            entries = [item for item in data if isinstance(item, dict)]
        elif isinstance(payload.get("id"), str):
            entries = [payload]

    wanted = model.strip().lower()
    for entry in entries:
        identifier = str(entry.get("id") or entry.get("model") or entry.get("name") or "")
        if wanted and identifier.strip().lower() != wanted:
            continue
        lines: list[str] = []
        for key, value in entry.items():
            if not any(token in key.lower() for token in CAPABILITY_KEYS):
                continue
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            lines.append(f"{key}={rendered[:CAPABILITY_VALUE_LIMIT]}")
        if lines:
            return [f"{identifier or model}:"] + [f"  {line}" for line in lines]
    return []


def probe_capabilities(settings: LLMSettings, timeout: float) -> tuple[str, list[str]]:
    """Ask the provider what this model supports, when it publishes a list.

    Nothing is inferred here. Unsupported or undeclared stays unproven, and a
    provider that has no capability listing simply says so.
    """
    url = model_list_url(settings.base_url)
    attempt = send_request("GET", url, {"Authorization": f"Bearer {settings.api_key}"}, None, timeout)
    if attempt.status_code is None:
        return f"no response ({attempt.transport_error})", []
    if attempt.status_code >= 400:
        message = error_message(attempt.payload)
        return f"HTTP {attempt.status_code}" + (f" ({message})" if message else ""), []
    if not attempt.parsed:
        return f"HTTP {attempt.status_code} (body is not JSON)", []
    return f"HTTP {attempt.status_code}", describe_capabilities(attempt.payload, settings.model)


def error_message(payload: Any) -> str:
    """The provider's error text, if the body carries one."""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or error.get("type")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return json.dumps(error, ensure_ascii=False)[:BODY_LIMIT]
    if isinstance(error, str) and error.strip():
        return error.strip()
    return ""


def looks_like_unsupported_tool(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in UNSUPPORTED_TOOL_MARKERS)


@dataclass
class Attempt:
    """One HTTP call, however it ended."""

    status_code: int | None = None
    payload: Any = None
    raw_text: str = ""
    parsed: bool = True
    transport_error: str = ""

    @property
    def body_preview(self) -> str:
        text = self.raw_text.strip()
        if not text and self.payload is not None:
            text = json.dumps(self.payload, ensure_ascii=False)
        return text[:BODY_LIMIT] + ("..." if len(text) > BODY_LIMIT else "")


def send_request(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict | None,
    timeout: float,
) -> Attempt:
    """Call the endpoint and never raise: every failure becomes an ``Attempt``."""
    attempt = Attempt()
    try:
        with httpx.Client(timeout=timeout) as client:
            if method == "GET":
                response = client.get(url, headers=headers)
            else:
                response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        attempt.transport_error = f"timed out after {timeout:g}s"
        return attempt
    except httpx.ConnectError as exc:
        attempt.transport_error = f"connection failed: {exc}"
        return attempt
    except httpx.HTTPError as exc:
        attempt.transport_error = f"HTTP error: {exc.__class__.__name__}"
        return attempt

    attempt.status_code = response.status_code
    attempt.raw_text = response.text
    try:
        attempt.payload = response.json()
    except ValueError:
        attempt.parsed = False
    return attempt


def decide(attempt: Attempt, evidence: Evidence) -> tuple[str, str]:
    """The verdict for one Responses attempt."""
    if attempt.status_code is None:
        return ERROR, attempt.transport_error or "the request never reached the server"

    message = error_message(attempt.payload)
    status = attempt.status_code

    if status in (401, 403):
        return ERROR, f"HTTP {status}: the API key was rejected ({message or 'no message'})"
    if status == 429:
        return ERROR, f"HTTP 429: rate limited, the capability was not tested ({message})"
    if message and looks_like_unsupported_tool(message):
        return FAIL_TOOL, f"HTTP {status}: {message}"
    if status == 404:
        return FAIL_RESPONSES, f"HTTP 404: no /responses endpoint here ({message or 'no message'})"
    if status in ENDPOINT_MISSING_STATUSES:
        return FAIL_RESPONSES, f"HTTP {status}: the /responses request was rejected ({message or 'no message'})"
    if status >= 500:
        return ERROR, f"HTTP {status}: the provider failed ({message or 'no message'})"
    if status >= 400:
        return ERROR, f"HTTP {status}: unexpected failure ({message or 'no message'})"
    if message:
        return FAIL_RESPONSES, f"HTTP {status} with an error body: {message}"
    if not attempt.parsed:
        return UNKNOWN, "HTTP 200 but the body is not JSON, so no search evidence could be read"
    if evidence.found:
        detail = []
        if evidence.calls:
            detail.append(f"{len(evidence.calls)} search call(s)")
        if evidence.citations:
            detail.append(f"{len(evidence.citations)} source URL(s)")
        return PASS, "HTTP 200 and the response carries " + " and ".join(detail)
    if evidence.weak:
        return UNKNOWN, "HTTP 200 but only a bare search tool declaration was returned, no call and no citation"
    return UNKNOWN, "HTTP 200 and an answer came back, but nothing in it proves a search ran"


def probe_chat_completions(settings: LLMSettings, timeout: float) -> str:
    """Diagnostic: is the project's existing /chat/completions path still alive?

    Only run when the Responses attempt fails, so a refused /responses request can
    be told apart from a bad key or a dead host.
    """
    base = settings.base_url.strip().rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    attempt = send_request("POST", url, headers, payload, timeout)
    if attempt.status_code is None:
        return attempt.transport_error
    message = error_message(attempt.payload)
    suffix = f" ({message})" if message else ""
    return f"HTTP {attempt.status_code}{suffix}"


def missing_variables(settings) -> list[str]:
    missing = []
    if not settings.api_key:
        missing.append("LLM_API_KEY")
    if not settings.model:
        missing.append("LLM_MODEL")
    if not settings.base_url:
        missing.append("LLM_BASE_URL")
    return missing


def format_answer(text: str) -> str:
    if not text:
        return "(no text content in the response)"
    if len(text) <= ANSWER_LIMIT:
        return text
    return text[:ANSWER_LIMIT] + f"\n... (truncated, {len(text)} characters in total)"


def run(question: str, timeout: float, dump_json: bool) -> int:
    settings = load_llm_settings()
    missing = missing_variables(settings)
    if missing:
        print("AI Daily Web Search probe")
        print()
        print("Cannot run: the LLM endpoint is not configured.")
        print(f"Missing environment variable(s): {', '.join(missing)}")
        print("Set them in backend/.env (copy backend/.env.example) or in the environment.")
        return 2

    url = responses_url(settings.base_url)
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": settings.model, "input": question, "tools": [WEB_SEARCH_TOOL]}

    print("AI Daily Web Search probe")
    print(f"BASE_URL:    {settings.base_url}")
    print(f"Endpoint:    {url}")
    print(f"MODEL:       {settings.model}")
    print(f"LLM_ENABLED: {settings.enabled}")
    print(f"Tool:        {json.dumps(WEB_SEARCH_TOOL)}")
    print(f"Timeout:     {timeout:g}s")
    print(f"Question:    {question}")
    if not settings.enabled:
        print("Note:        LLM_ENABLED is false; probing anyway, this is a diagnostic")
    print()

    attempt = send_request("POST", url, headers, payload, timeout)
    evidence = collect_evidence(attempt.payload) if attempt.parsed else Evidence()
    verdict, detail = decide(attempt, evidence)

    print(f"HTTP status: {attempt.status_code if attempt.status_code is not None else 'no response'}")
    if attempt.status_code is None:
        print(f"Transport:   {attempt.transport_error}")
    else:
        print(f"Body:        {attempt.body_preview}")
    print()

    print("Web Search evidence")
    print(f"  web_search_call (or provider search call): {'yes' if evidence.calls else 'not found'}")
    for label in evidence.calls:
        print(f"    - {label}")
    print(f"  URL citation / web source annotations:     {'yes' if evidence.citations else 'not found'}")
    for citation in evidence.citations:
        print(f"    - {citation}")
    if evidence.weak:
        print("  Bare search tool declaration (not evidence):")
        for label in evidence.weak:
            print(f"    - {label}")
    if evidence.status:
        print(f"  Response status field: {evidence.status}")
    print()

    print("Provider capability information")
    print(f"  GET {model_list_url(settings.base_url)}")
    cap_status, cap_entries = probe_capabilities(settings, timeout)
    print(f"  HTTP status: {cap_status}")
    if cap_entries:
        for line in cap_entries:
            print(f"    {line}")
    elif cap_status.startswith("HTTP 200"):
        print(f"    no tool / web-search capability is declared for {settings.model}")
    else:
        print("    the provider publishes no capability list here, so nothing is declared either way")
    print()

    print("Model answer")
    print("------------")
    print(format_answer(evidence.text))
    print()

    if dump_json and attempt.payload is not None:
        print("Raw response JSON")
        print("-----------------")
        print(json.dumps(attempt.payload, ensure_ascii=False, indent=2))
        print()

    request_failed = attempt.status_code is None or attempt.status_code >= 400
    if verdict != PASS and request_failed:
        print(f"Control probe (/chat/completions): {probe_chat_completions(settings, timeout)}")
        print()

    print(f"Conclusion: {verdict}")
    print(f"Detail:     {detail}")
    return 0 if verdict == PASS else (2 if verdict == ERROR else 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether the configured LLM API really supports Web Search"
    )
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="the prompt to send")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for the response (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument("--dump-json", action="store_true", help="print the raw response JSON")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    load_dotenv()
    return run(args.question, args.timeout, args.dump_json)


if __name__ == "__main__":
    raise SystemExit(main())
