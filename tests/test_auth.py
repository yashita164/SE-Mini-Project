
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


def read_all_user_rows():
    """Read the users table directly, bypassing the application layer."""
    import sqlite3

    connection = sqlite3.connect(database.DB_PATH)
    try:
        return connection.execute("SELECT * FROM users").fetchall()
    finally:
        connection.close()


def test_sec_02_same_password_produces_different_hashes(monkeypatch, tmp_path):
    """TC-Sec-02: a unique salt means equal passwords never share a hash."""
    setup_test_database(monkeypatch, tmp_path)

    password = "SharedPass123"
    assert auth.register("alice_1", password)[0] is True
    assert auth.register("bob_1", password)[0] is True

    alice_hash = database.get_user("alice_1")["password_hash"]
    bob_hash = database.get_user("bob_1")["password_hash"]

    assert alice_hash != bob_hash

    # The salt is the 22 characters after the "$2b$NN$" prefix.
    assert alice_hash[7:29] != bob_hash[7:29]

    # Different salts must not break verification for either user.
    assert auth.login("alice_1", password) is not None
    assert auth.login("bob_1", password) is not None


def test_sec_02_stored_hash_has_bcrypt_format(monkeypatch, tmp_path):
    """TC-Sec-02: stored values are well-formed bcrypt hashes."""
    setup_test_database(monkeypatch, tmp_path)

    assert auth.register("alice_1", "SecurePass123")[0] is True

    stored = database.get_user("alice_1")["password_hash"]

    assert len(stored) == 60
    assert stored.startswith("$2b$")


def test_sec_02_database_contains_only_hashed_passwords(monkeypatch, tmp_path):
    """TC-Sec-02: inspecting the database never reveals a plaintext password."""
    setup_test_database(monkeypatch, tmp_path)

    passwords = {"alice_1": "AlicePlain#789", "bob_1": "BobPlain#456"}

    for username, password in passwords.items():
        assert auth.register(username, password)[0] is True

    rows = read_all_user_rows()
    assert len(rows) == len(passwords)

    # Every stored value in every column, as seen by a raw SQL query.
    stored_values = [str(value) for row in rows for value in row]

    for password in passwords.values():
        assert all(password not in value for value in stored_values)

    # And the raw database file itself, as an attacker with disk access sees it.
    raw_file = database.DB_PATH.read_bytes()

    for password in passwords.values():
        assert password.encode("utf-8") not in raw_file

    for row in rows:
        password_hash = row[1]
        assert password_hash.startswith("$2")
