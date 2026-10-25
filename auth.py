
"""Registration and authentication using bcrypt and session tokens."""

import re
import secrets

import bcrypt
import database


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,24}$")
MAX_BCRYPT_PASSWORD_BYTES = 72


def register(username, password):
    """Register a user with a salted bcrypt password hash."""
    if not isinstance(username, str):
        return False, "Username must be text."

    if not USERNAME_PATTERN.fullmatch(username):
        return (
            False,
            "Username must be 3-24 characters using letters, numbers, or underscores.",
        )

    if not isinstance(password, str):
        return False, "Password must be text."

    password_bytes = password.encode("utf-8")

    if not 8 <= len(password_bytes) <= MAX_BCRYPT_PASSWORD_BYTES:
        return False, "Password must be 8-72 UTF-8 bytes."

    password_hash = bcrypt.hashpw(
        password_bytes,
        bcrypt.gensalt(),
    ).decode("utf-8")

    if not database.create_user(username, password_hash):
        return False, "Username already exists."

    return True, "Registration successful."


def login(username, password):
    """Verify credentials and issue a random session token."""
    if not isinstance(username, str) or not isinstance(password, str):
        return None

    password_bytes = password.encode("utf-8")

    if not 1 <= len(password_bytes) <= MAX_BCRYPT_PASSWORD_BYTES:
        return None

    user = database.get_user(username)

    if user is None:
        return None

    try:
        password_is_valid = bcrypt.checkpw(
            password_bytes,
            user["password_hash"].encode("utf-8"),
        )
    except (ValueError, TypeError):
        return None

    if not password_is_valid:
        return None

    token = secrets.token_urlsafe(32)
    database.save_session(token, user["username"])

    return {
        "username": user["username"],
        "token": token,
    }
