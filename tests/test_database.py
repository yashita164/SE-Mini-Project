"""Database-level tests for the offline message queue (TC-Msg-03)."""

import sqlite3

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
