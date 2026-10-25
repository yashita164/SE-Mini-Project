
"""TCP server integration tests for the Team 5 chat application."""

import json
import socket
import subprocess
import sys
import time

import pytest


HOST = "127.0.0.1"


def receive_json(sock, stream, timeout=3):
    """Receive one newline-delimited JSON response."""
    sock.settimeout(timeout)
    line = stream.readline()
    if not line:
        raise AssertionError("Server closed the connection unexpectedly.")
    return json.loads(line.decode("utf-8"))


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    """Start an isolated server process using a temporary SQLite database."""
    import database

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "server_test.db")
    database.init_db()

    # Import the server after the database module is available.
    import server

    # Run the handler in this process on an available local port.
    test_server = server.ChatServer((HOST, 0), server.ChatHandler)
    test_server_thread = __import__("threading").Thread(
        target=test_server.serve_forever,
        daemon=True,
    )
    test_server_thread.start()

    try:
        yield test_server.server_address
    finally:
        test_server.shutdown()
        test_server.server_close()
        test_server_thread.join(timeout=3)


def send_json(sock, payload):
    """Send one newline-delimited JSON request."""
    sock.sendall(
        (json.dumps(payload) + "\n").encode("utf-8")
    )


def test_server_register_and_login(running_server):
    """A client can register and then authenticate over TCP."""
    host, port = running_server

    with socket.create_connection((host, port), timeout=3) as sock:
        stream = sock.makefile("rb")

        send_json(
            sock,
            {
                "type": "REGISTER_REQUEST",
                "username": "tcp_alice",
                "password": "SecurePass123",
            },
        )
        registration = receive_json(sock, stream)
        assert registration["type"] == "REGISTER_RESPONSE"
        assert registration["status"] == "OK"

        send_json(
            sock,
            {
                "type": "LOGIN_REQUEST",
                "username": "tcp_alice",
                "password": "SecurePass123",
            },
        )
        login = receive_json(sock, stream)
        assert login["type"] == "LOGIN_RESPONSE"
        assert login["status"] == "OK"
        assert login["userId"] == "tcp_alice"
        assert isinstance(login.get("token"), str)
        assert len(login["token"]) > 20


def test_server_rejects_invalid_login(running_server):
    """Invalid credentials are rejected by the TCP server."""
    host, port = running_server

    with socket.create_connection((host, port), timeout=3) as sock:
        stream = sock.makefile("rb")

        send_json(
            sock,
            {
                "type": "LOGIN_REQUEST",
                "username": "nobody",
                "password": "WrongPass123",
            },
        )
        response = receive_json(sock, stream)
        assert response["type"] == "LOGIN_RESPONSE"
        assert response["status"] == "ERROR"
        assert response["code"] == 401
