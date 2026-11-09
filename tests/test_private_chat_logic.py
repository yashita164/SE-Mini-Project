"""Tests for the private chat display logic (no Tkinter or server needed)."""

from gui.private_chat_logic import (
    ack_text,
    format_history_row,
    format_line,
    is_message_from_partner,
    is_private_row,
    is_typing_from_partner,
    rows_for_conversation,
    short_time,
)


def row(msg_id, sender, recipient, content="hi", created="2026-11-10 09:05:00"):
    return {"id": msg_id, "sender": sender, "recipient": recipient,
            "content": content, "created_at": created}


def test_room_rows_are_not_private():
    assert is_private_row(row(1, "alice", "bob"))
    assert not is_private_row(row(2, "alice", "#general"))
    assert not is_private_row({"sender": "alice"})


def test_rows_for_conversation_keeps_only_this_pair():
    rows = [
        row(1, "alice", "bob"),
        row(2, "bob", "alice"),
        row(3, "alice", "carol"),
        row(4, "alice", "#general"),
        row(5, "carol", "bob"),
    ]
    kept = rows_for_conversation(rows, "alice", "bob")
    assert [r["id"] for r in kept] == [1, 2]


def test_short_time_accepts_both_timestamp_styles_and_bad_input():
    assert short_time("2026-11-10 09:05:00") == "09:05"
    assert short_time("2026-11-10T09:05:00+00:00") == "09:05"
    assert short_time("garbage") == "--:--"
    assert short_time(None) == "--:--"


def test_format_line_marks_own_messages_as_you():
    assert format_line("alice", "hello", "2026-11-10 09:05:00", "alice") == "[09:05] You: hello"
    assert format_line("bob", "hello", "2026-11-10 09:05:00", "alice") == "[09:05] bob: hello"


def test_format_history_row_handles_missing_fields():
    assert format_history_row(row(1, "bob", "alice", "yo"), "alice") == "[09:05] bob: yo"
    assert format_history_row({}, "alice") == "[--:--] ?: "


def test_is_message_from_partner_ignores_rooms_and_other_users():
    live = {"type": "NEW_MESSAGE", "fromUser": "bob", "content": "x"}
    assert is_message_from_partner(live, "bob")
    assert not is_message_from_partner(live, "carol")
    assert not is_message_from_partner({**live, "roomId": "general"}, "bob")
    assert not is_message_from_partner({"type": "ERROR"}, "bob")


def test_is_typing_from_partner():
    event = {"type": "TYPING_INDICATOR", "fromUser": "bob", "isTyping": True}
    assert is_typing_from_partner(event, "bob")
    assert not is_typing_from_partner(event, "carol")
    assert not is_typing_from_partner({**event, "roomId": "general"}, "bob")


def test_ack_text():
    assert ack_text({"type": "MESSAGE_DELIVERED"}) == "Delivered"
    assert "offline" in ack_text({"type": "MESSAGE_STORED"})
    assert ack_text({"type": "MESSAGE_ERROR", "message": "No such user"}) == "Not sent: No such user"
    assert ack_text({"type": "NEW_MESSAGE"}) is None
