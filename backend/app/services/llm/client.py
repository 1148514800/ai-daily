from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.services.llm.settings import LLMSettings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


@dataclass
class LLMCompletion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def completions_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def extract_json_text(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


class LLMClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def complete(self, messages: list[dict[str, str]]) -> LLMCompletion:
        if not self.settings.available:
            raise LLMError("LLM is not configured")

        url = completions_url(self.settings.base_url)
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise LLMError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMError("LLM HTTP error") from exc
        except ValueError as exc:
            raise LLMError("LLM returned invalid JSON") from exc

        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM returned an empty response") from exc

        if not isinstance(text, str) or not text.strip():
            raise LLMError("LLM returned an empty response")

        usage = body.get("usage") if isinstance(body, dict) else None
        input_tokens = None
        output_tokens = None
        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            if isinstance(prompt, int):
                input_tokens = prompt
            if isinstance(completion, int):
                output_tokens = completion

        logger.info(
            "llm call model=%s input_tokens=%s output_tokens=%s",
            self.settings.model,
            input_tokens,
            output_tokens,
        )
        return LLMCompletion(text=text, input_tokens=input_tokens, output_tokens=output_tokens)


def parse_completion_json(text: str) -> dict:
    try:
        payload = json.loads(extract_json_text(text))
    except json.JSONDecodeError as exc:
        raise LLMError("LLM returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise LLMError("LLM returned malformed JSON")
    return payload
