
"""Authentication tests mapped to the submitted STP."""

import auth
import database


def setup_test_database(monkeypatch, tmp_path):
    """Give each test its own isolated SQLite database."""
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test_chat.db")
    database.init_db()


def test_auth_01_register_unique_username(monkeypatch, tmp_path):
    """TC-Auth-01: register a unique username successfully."""
    setup_test_database(monkeypatch, tmp_path)

    success, message = auth.register("alice_1", "SecurePass123")

    assert success is True
    assert message == "Registration successful."
    assert database.get_user("alice_1") is not None


def test_auth_01_reject_duplicate_username(monkeypatch, tmp_path):
    """TC-Auth-01: reject duplicate usernames."""
    setup_test_database(monkeypatch, tmp_path)

    assert auth.register("alice_1", "SecurePass123")[0] is True

    success, message = auth.register("alice_1", "AnotherPass123")

    assert success is False
    assert message == "Username already exists."


def test_auth_01_reject_invalid_registration(monkeypatch, tmp_path):
    """TC-Auth-01: reject invalid usernames and short passwords."""
    setup_test_database(monkeypatch, tmp_path)

    assert auth.register("ab", "SecurePass123")[0] is False
    assert auth.register("valid_user", "short")[0] is False


def test_auth_02_valid_login_returns_session(monkeypatch, tmp_path):
    """TC-Auth-02: valid credentials issue a session token."""
    setup_test_database(monkeypatch, tmp_path)

    assert auth.register("alice_1", "SecurePass123")[0] is True

    result = auth.login("alice_1", "SecurePass123")

    assert result is not None
    assert result["username"] == "alice_1"
    assert isinstance(result["token"], str)
    assert len(result["token"]) > 20
    assert database.get_session_user(result["token"]) == "alice_1"


def test_auth_02_reject_invalid_password(monkeypatch, tmp_path):
    """TC-Auth-02: invalid credentials must not create a session."""
    setup_test_database(monkeypatch, tmp_path)

    assert auth.register("alice_1", "SecurePass123")[0] is True

    result = auth.login("alice_1", "WrongPassword123")

    assert result is None


def test_sec_02_password_is_hashed(monkeypatch, tmp_path):
    """TC-Sec-02: passwords must not be stored as plaintext."""
    setup_test_database(monkeypatch, tmp_path)

    password = "SecurePass123"
    assert auth.register("alice_1", password)[0] is True

    user = database.get_user("alice_1")

    assert user is not None
    assert user["password_hash"] != password
    assert user["password_hash"].startswith("$2")
    assert auth.bcrypt.checkpw(
        password.encode("utf-8"),
        user["password_hash"].encode("utf-8"),
    )
