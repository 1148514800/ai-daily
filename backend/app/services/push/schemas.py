from __future__ import annotations

from dataclasses import dataclass, field

NOTIFICATION_TYPE_DAILY_DIGEST = "daily_digest"


@dataclass
class PushMessage:
    """One Expo push message. Content stays tiny: the app fetches the digest."""

    to: str
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    channel_id: str | None = None

    def to_payload(self) -> dict:
        payload: dict = {
            "to": self.to,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "sound": "default",
        }
        if self.channel_id:
            payload["channelId"] = self.channel_id
        return payload


@dataclass
class PushTicket:
    """Immediate send response for one message."""

    token: str
    ok: bool
    error: str | None = None
    details_error: str | None = None

    @property
    def device_not_registered(self) -> bool:
        return self.details_error == "DeviceNotRegistered"


@dataclass
class PushResult:
    tickets: list[PushTicket] = field(default_factory=list)
    error: str | None = None

    @property
    def delivered(self) -> int:
        return sum(1 for ticket in self.tickets if ticket.ok)

    @property
    def failed(self) -> int:
        return sum(1 for ticket in self.tickets if not ticket.ok)

    @property
    def stale_tokens(self) -> list[str]:
        return [ticket.token for ticket in self.tickets if ticket.device_not_registered]
