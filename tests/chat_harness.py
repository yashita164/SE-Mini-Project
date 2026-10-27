"""Shared helpers: run a real ChatServer on a free port with a temp database."""

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth  # noqa: E402
import bcrypt  # noqa: E402
import database  # noqa: E402
import server  # noqa: E402


class Conn:
    """Minimal newline-delimited-JSON test client."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sock.settimeout(5)
        self.stream = self.sock.makefile("rb")

    def send(self, payload):
        self.send_raw(json.dumps(payload).encode("utf-8") + b"\n")

    def send_raw(self, data):
        self.sock.sendall(data)

    def recv(self):
        """Return the next JSON message, or None if the server closed/timed out."""
        try:
            line = self.stream.readline()
        except (socket.timeout, OSError):
            return None
        return json.loads(line) if line else None

    def recv_type(self, wanted, limit=10):
        """Skip unrelated events until a message of type `wanted` arrives."""
        for _ in range(limit):
            message = self.recv()
            if message is None or message.get("type") == wanted:
                return message
        return None

    def close(self):
        try:
            self.stream.close()
            self.sock.close()
        except OSError:
            pass


def register_and_login(port, username, password="correct-horse"):
    conn = Conn(port)
    conn.send({"type": "REGISTER_REQUEST", "username": username, "password": password})
    assert conn.recv_type("REGISTER_RESPONSE")["status"] == "OK"
    conn.send({"type": "LOGIN_REQUEST", "username": username, "password": password})
    reply = conn.recv_type("LOGIN_RESPONSE")
    assert reply["status"] == "OK"
    return conn, reply["token"]


@pytest.fixture
def chat_port(tmp_path, monkeypatch):
    """Start a server on an OS-assigned port; yields the port number."""
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "chat.db")
    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(auth.bcrypt, "gensalt", lambda: real_gensalt(rounds=4))
    database.init_db()
    server.ACTIVE_CLIENTS.clear()

    srv = server.ChatServer(("127.0.0.1", 0), server.ChatHandler)
    thread = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        server.ACTIVE_CLIENTS.clear()
