
"""SQLite persistence for users, sessions, and direct messages."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).with_name("chat.db")


@contextmanager
def get_connection():
    """Provide a database connection with safe commit, rollback, and close."""
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    """Create the required tables if they do not exist."""
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username)
                    REFERENCES users(username) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS banned_users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                banned_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username)
                    REFERENCES users(username) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                delivered INTEGER NOT NULL DEFAULT 0
            );
        """)
        _migrate_messages_table(connection)


def _migrate_messages_table(connection):
    """Add the delivered flag to databases created before the offline queue.

    Messages that existed before the flag was introduced were already
    available through history, so they are marked as delivered rather than
    being replayed to their recipients on next login.
    """
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(messages)")
    }

    if "delivered" not in columns:
        connection.execute(
            "ALTER TABLE messages "
            "ADD COLUMN delivered INTEGER NOT NULL DEFAULT 0"
        )
        connection.execute("UPDATE messages SET delivered = 1")


def create_user(username, password_hash):
    """Create a user; return False if the username already exists."""
    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_user(username):
    """Retrieve a user record or return None."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    return dict(row) if row else None


def save_session(token, username):
    """Persist a session token."""
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (token, username) VALUES (?, ?)",
            (token, username),
        )


def get_session_user(token):
    """Return the username associated with a token, or None."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT username FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()

    return row["username"] if row else None


def delete_session(token):
    """Invalidate a session token."""
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM sessions WHERE token = ?",
            (token,),
        )


def ban_user(username, banned_by):
    """Persist a server-wide ban for an existing username."""
    with get_connection() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO banned_users (username, banned_by) "
            "VALUES (?, ?)",
            (username, banned_by),
        )


def is_user_banned(username):
    """Return whether the username has an active server-wide ban."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM banned_users WHERE username = ?",
            (username,),
        ).fetchone()

    return row is not None


def save_message(sender, recipient, content, delivered=False):
    """Store a direct message and return its generated ID.

    Messages start undelivered; the server marks them delivered once they
    have been written to the recipient's connection.
    """
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO messages (sender, recipient, content, delivered)
            VALUES (?, ?, ?, ?)
            """,
            (sender, recipient, content, 1 if delivered else 0),
        )
        return cursor.lastrowid


def get_pending_messages(recipient):
    """Return undelivered messages for a user in original (send) order."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, sender, recipient, content, created_at
            FROM messages
            WHERE recipient = ? AND delivered = 0
            ORDER BY id ASC
            """,
            (recipient,),
        ).fetchall()

    return [dict(row) for row in rows]


def mark_message_delivered(message_id):
    """Mark one stored message as delivered to its recipient."""
    with get_connection() as connection:
        connection.execute(
            "UPDATE messages SET delivered = 1 WHERE id = ?",
            (message_id,),
        )


def get_messages_for(username, limit=50):
    """Return recent sent and received messages in chronological order."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, sender, recipient, content, created_at
            FROM messages
            WHERE sender = ? OR recipient = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (username, username, limit),
        ).fetchall()

    return [dict(row) for row in reversed(rows)]
