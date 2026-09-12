from __future__ import annotations

import logging

import httpx

from app.config.push import MAX_MESSAGES_PER_REQUEST, expo_push_url
from app.services.push.schemas import PushMessage, PushResult, PushTicket

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10.0


class ExpoPushError(RuntimeError):
    """Raised when the Expo Push service cannot be reached or rejects the request."""


class ExpoPushClient:
    """Thin wrapper around the Expo Push send endpoint.

    Only the immediate send response is handled; receipt polling is intentionally
    left for a later phase.
    """

    def __init__(self, url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.url = url or expo_push_url()
        self._transport = transport

    def send(self, messages: list[PushMessage]) -> PushResult:
        if not messages:
            return PushResult()

        result = PushResult()
        for start in range(0, len(messages), MAX_MESSAGES_PER_REQUEST):
            batch = messages[start : start + MAX_MESSAGES_PER_REQUEST]
            result.tickets.extend(self._send_batch(batch))
            logger.info("expo push batch size=%s", len(batch))
        return result

    def _send_batch(self, batch: list[PushMessage]) -> list[PushTicket]:
        payload = [message.to_payload() for message in batch]
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, transport=self._transport) as client:
                response = client.post(self.url, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise ExpoPushError(f"expo push request failed: {exc}") from exc
        except ValueError as exc:
            raise ExpoPushError("expo push returned invalid JSON") from exc

        return self._parse_tickets(batch, body)

    @staticmethod
    def _parse_tickets(batch: list[PushMessage], body: object) -> list[PushTicket]:
        entries: list[dict] = []
        if isinstance(body, dict):
            raw = body.get("data")
            if isinstance(raw, list):
                entries = [item for item in raw if isinstance(item, dict)]
            elif isinstance(raw, dict):
                # A single message may come back as one object instead of a list.
                entries = [raw]
        elif isinstance(body, list):
            entries = [item for item in body if isinstance(item, dict)]

        if len(entries) != len(batch):
            raise ExpoPushError(
                f"expo push returned {len(entries)} tickets for {len(batch)} messages"
            )

        tickets: list[PushTicket] = []
        for message, entry in zip(batch, entries):
            status = str(entry.get("status", "error"))
            details = entry.get("details")
            details_error = None
            if isinstance(details, dict) and details.get("error"):
                details_error = str(details["error"])
            tickets.append(
                PushTicket(
                    token=message.to,
                    ok=status == "ok",
                    error=None if status == "ok" else str(entry.get("message") or "push failed"),
                    details_error=details_error,
                )
            )
        return tickets
