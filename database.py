
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

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)


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


def save_message(sender, recipient, content):
    """Store a direct message and return its generated ID."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO messages (sender, recipient, content)
            VALUES (?, ?, ?)
            """,
            (sender, recipient, content),
        )
        return cursor.lastrowid


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
