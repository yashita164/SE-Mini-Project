
"""SQLite persistence for users, sessions, and direct messages."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                admin_id TEXT NOT NULL,
                target TEXT,
                detail TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                delivered INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_messages_sender_history
                ON messages (sender, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_messages_recipient_history
                ON messages (recipient, created_at, id);
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


def log_admin_action(action, admin_id, target=None, detail=''):
    """Persist one successful administrative action with its actor and time."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO admin_audit_log (action, admin_id, target, detail)
            VALUES (?, ?, ?, ?)
            """,
            (action, admin_id, target, detail),
        )
        return cursor.lastrowid


def get_admin_audit_log(limit=100):
    """Return recent administrative audit entries in chronological order."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, action, admin_id, target, detail, timestamp
            FROM admin_audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in reversed(rows)]


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


def get_messages_for(username, limit=50, before_id=None):
    """Return one chronological page of a user's last 90 days of messages."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if (before_id is not None
            and (not isinstance(before_id, int) or isinstance(before_id, bool)
                 or before_id < 1)):
        raise ValueError("before_id must be a positive integer")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    cursor_filter = " AND id < ?" if before_id is not None else ""
    parameters = [username, username, cutoff]
    if before_id is not None:
        cursor_filter = """ AND (created_at, id) < (
            SELECT created_at, id FROM messages
            WHERE id = ? AND (sender = ? OR recipient = ?)
        )"""
        parameters.append(before_id)
        parameters.extend((username, username))
    parameters.append(limit)

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT id, sender, recipient, content, created_at
            FROM messages
            WHERE (sender = ? OR recipient = ?) AND created_at >= ?
            {cursor_filter}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()

    return [dict(row) for row in reversed(rows)]
