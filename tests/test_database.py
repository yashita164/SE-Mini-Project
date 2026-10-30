"""Database-level tests for the offline message queue (TC-Msg-03)."""

import sqlite3
from datetime import datetime, timedelta, timezone

import database


def use_temp_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test_chat.db")


def test_msg_03_pending_messages_are_returned_in_send_order(
    monkeypatch, tmp_path
):
    """TC-Msg-03: the queue is ordered by send order, not by sender."""
    use_temp_database(monkeypatch, tmp_path)
    database.init_db()

    ids = [
        database.save_message("a", "bob", "one"),
        database.save_message("c", "bob", "two"),
        database.save_message("a", "bob", "three"),
    ]
    database.save_message("a", "someone_else", "not for bob")

    pending = database.get_pending_messages("bob")

    assert [message["id"] for message in pending] == ids
    assert [message["content"] for message in pending] == [
        "one",
        "two",
        "three",
    ]


def test_msg_03_marking_delivered_removes_only_that_message(
    monkeypatch, tmp_path
):
    """TC-Msg-03: delivered messages leave the queue; others stay."""
    use_temp_database(monkeypatch, tmp_path)
    database.init_db()

    first = database.save_message("a", "bob", "one")
    second = database.save_message("a", "bob", "two")

    database.mark_message_delivered(first)

    assert [m["id"] for m in database.get_pending_messages("bob")] == [second]


def test_msg_03_messages_saved_as_delivered_are_not_queued(
    monkeypatch, tmp_path
):
    """TC-Msg-03: live-delivered messages never enter the queue."""
    use_temp_database(monkeypatch, tmp_path)
    database.init_db()

    database.save_message("a", "bob", "live", delivered=True)

    assert database.get_pending_messages("bob") == []


def test_msg_03_existing_database_is_migrated_without_replaying_history(
    monkeypatch, tmp_path
):
    """A database from before the queue gains the column; old rows are
    treated as delivered so users are not flooded with old history."""
    use_temp_database(monkeypatch, tmp_path)

    legacy = sqlite3.connect(database.DB_PATH)
    legacy.executescript("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO messages (sender, recipient, content)
        VALUES ('a', 'bob', 'old message');
    """)
    legacy.commit()
    legacy.close()

    database.init_db()
    database.init_db()  # migration must be idempotent

    assert database.get_pending_messages("bob") == []

    database.save_message("a", "bob", "new message")

    assert [m["content"] for m in database.get_pending_messages("bob")] == [
        "new message"
    ]


def test_history_includes_messages_through_the_90_day_boundary(
    monkeypatch, tmp_path
):
    """History includes the full 90-day window and preserves chronological order."""
    use_temp_database(monkeypatch, tmp_path)
    database.init_db()

    fixed_now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(database, "datetime", FrozenDateTime)
    messages = [
        ("today", 0, 0),
        ("older than 30 days", 31, 0),
        ("older than 60 days", 61, 0),
        ("within 90 days", 89, 23 * 60 + 59),
        ("at 90-day boundary", 90, 0),
        ("outside 90 days", 90, 0),
    ]
    ids = []
    for content, days_ago, minutes_ago in messages:
        message_id = database.save_message("alice", "bob", content)
        ids.append(message_id)
        created_at = fixed_now - timedelta(days=days_ago, minutes=minutes_ago)
        if content == "outside 90 days":
            created_at -= timedelta(seconds=1)
        with database.get_connection() as connection:
            connection.execute(
                "UPDATE messages SET created_at = ? WHERE id = ?",
                (created_at.strftime("%Y-%m-%d %H:%M:%S"), message_id),
            )

    history = database.get_messages_for("alice", limit=20)
    assert [message["content"] for message in history] == [
        "at 90-day boundary",
        "within 90 days",
        "older than 60 days",
        "older than 30 days",
        "today",
    ]
    assert [message["id"] for message in history] == [
        ids[4], ids[3], ids[2], ids[1], ids[0]
    ]


def test_history_pages_do_not_skip_or_repeat_messages(monkeypatch, tmp_path):
    """History pages can reach older records while remaining chronological."""
    use_temp_database(monkeypatch, tmp_path)
    database.init_db()
    ids = [
        database.save_message("alice", "bob", f"message {index}")
        for index in range(5)
    ]

    first_page = database.get_messages_for("alice", limit=2)
    second_page = database.get_messages_for(
        "alice", limit=2, before_id=first_page[0]["id"]
    )
    third_page = database.get_messages_for(
        "alice", limit=2, before_id=second_page[0]["id"]
    )

    result = third_page + second_page + first_page
    assert [message["id"] for message in result] == ids
    assert [message["content"] for message in result] == [
        f"message {index}" for index in range(5)
    ]
