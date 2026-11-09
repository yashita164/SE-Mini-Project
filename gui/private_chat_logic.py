"""Display logic for the private chat screen (no Tkinter, so it is easy to test).

History rows come from ``HISTORY_RESPONSE`` as dictionaries with the keys
``id``, ``sender``, ``recipient``, ``content`` and ``created_at``. Room
messages are stored with a recipient that starts with ``#`` and are not
private messages, so they are skipped here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def is_private_row(row: dict[str, Any]) -> bool:
    """Return True for a stored one-to-one message (not a ``#room`` message)."""
    recipient = row.get("recipient")
    return isinstance(recipient, str) and not recipient.startswith("#")


def rows_for_conversation(
    rows: list[dict[str, Any]], me: str, partner: str
) -> list[dict[str, Any]]:
    """Keep only the messages exchanged between ``me`` and ``partner``."""
    wanted = {me, partner}
    return [
        row for row in rows
        if is_private_row(row) and {row.get("sender"), row.get("recipient")} == wanted
    ]


def short_time(timestamp: Any) -> str:
    """Return ``HH:MM`` for an ISO or ``YYYY-MM-DD HH:MM:SS`` timestamp."""
    if isinstance(timestamp, str):
        try:
            return datetime.fromisoformat(timestamp).strftime("%H:%M")
        except ValueError:
            pass
    return "--:--"


def format_line(sender: str, content: str, timestamp: Any, me: str) -> str:
    """Format one chat line, showing your own messages as ``You``."""
    name = "You" if sender == me else sender
    return f"[{short_time(timestamp)}] {name}: {content}"


def format_history_row(row: dict[str, Any], me: str) -> str:
    return format_line(
        str(row.get("sender", "?")), str(row.get("content", "")),
        row.get("created_at"), me,
    )


def is_message_from_partner(event: dict[str, Any], partner: str) -> bool:
    """True for a live private ``NEW_MESSAGE`` sent by ``partner``."""
    return (
        event.get("type") == "NEW_MESSAGE"
        and "roomId" not in event
        and event.get("fromUser") == partner
    )


def is_typing_from_partner(event: dict[str, Any], partner: str) -> bool:
    return (
        event.get("type") == "TYPING_INDICATOR"
        and "roomId" not in event
        and event.get("fromUser") == partner
    )


def ack_text(event: dict[str, Any]) -> str | None:
    """Return the status text for a send acknowledgement, or None."""
    kind = event.get("type")
    if kind == "MESSAGE_DELIVERED":
        return "Delivered"
    if kind == "MESSAGE_STORED":
        return "Saved - recipient is offline and will get it at next login"
    if kind == "MESSAGE_ERROR":
        return "Not sent: " + str(event.get("message", "unknown error"))
    return None
