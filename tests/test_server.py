"""TCP server integration tests for the Team 5 chat application."""

import base64
import hashlib
import json

import socket

import threading
import time
import ssl
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

import database

import server

import time
HOST = "127.0.0.1"

SOCKET_TIMEOUT = 3

def send_json(sock, payload):

    """Send one newline-delimited JSON request."""

    sock.sendall(

        (json.dumps(payload) + "\n").encode("utf-8")

    )

def receive_json(sock, stream, timeout=SOCKET_TIMEOUT):

    """Receive one newline-delimited JSON response."""

    deadline = time.monotonic() + timeout

    while True:

        sock.settimeout(max(0.01, deadline - time.monotonic()))

        line = stream.readline()

        if not line:

            raise AssertionError(

                "Server closed the connection unexpectedly."

            )

        response = json.loads(line.decode("utf-8"))

        if response.get("type") == "PING":

            sock.sendall(b'{"type":"PONG"}\n')

            if time.monotonic() >= deadline:
                raise AssertionError("Timed out while handling heartbeat messages.")

            continue

        return response

def expect_no_message(sock, stream, timeout=0.3):

    """Assert that no message arrives within the specified interval, ignoring heartbeats."""

    deadline = time.monotonic() + timeout

    while True:

        sock.settimeout(max(0.01, deadline - time.monotonic()))

        try:

            data = stream.readline()

        except socket.timeout:

            return

        if not data:

            return

        message = json.loads(data.decode("utf-8"))

        if message.get("type") == "PING":

            sock.sendall(b'{"type":"PONG"}\n')

            continue

        raise AssertionError(

            f"Unexpected message received: {data!r}"

        )

@pytest.fixture

def running_server(tmp_path, monkeypatch):

    """Start an isolated TCP server with a temporary SQLite database."""

    real_gensalt = server.auth.bcrypt.gensalt
    monkeypatch.setattr(
        server.auth.bcrypt, "gensalt", lambda: real_gensalt(rounds=4)
    )

    monkeypatch.setattr(

        database, "DB_PATH", tmp_path / "server_test.db"

    )

    database.init_db()

    with server.ACTIVE_CLIENTS_LOCK:

        server.ACTIVE_CLIENTS.clear()

    with server.TYPING_LOCK:

        server.TYPING_STATES.clear()

    with server.FILE_TRANSFER_LOCK:

        server.ACTIVE_FILE_TRANSFERS.clear()

    with server.LOGIN_RATE_LOCK:

        server.LOGIN_FAILURES_BY_IP.clear()

        server.LOGIN_BLOCKED_UNTIL_BY_IP.clear()

    test_server = server.ChatServer(

        (HOST, 0), server.ChatHandler

    )

    test_server_thread = threading.Thread(

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

        with server.ACTIVE_CLIENTS_LOCK:

            server.ACTIVE_CLIENTS.clear()

        with server.FILE_TRANSFER_LOCK:

            server.ACTIVE_FILE_TRANSFERS.clear()

        with server.LOGIN_RATE_LOCK:

            server.LOGIN_FAILURES_BY_IP.clear()

            server.LOGIN_BLOCKED_UNTIL_BY_IP.clear()

class ChatTestClient:

    """Helper for communicating with the server over TCP."""

    def __init__(self, address):

        self.sock = socket.create_connection(

            address, timeout=SOCKET_TIMEOUT

        )

        self.stream = self.sock.makefile("rb")

        self.token = None

    def send(self, payload):

        send_json(self.sock, payload)

    def receive(self, timeout=SOCKET_TIMEOUT):

        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.1, deadline - time.monotonic())
            response = receive_json(self.sock, self.stream, remaining)
            if response is None or response.get("type") != "PING":
                return response
            self.send({"type": "PONG"})

    def register(self, username, password="SecurePass123"):

        self.send({

            "type": "REGISTER_REQUEST",

            "username": username,

            "password": password,

        })

        return self.receive()

    def login(self, username, password="SecurePass123"):

        self.send({

            "type": "LOGIN_REQUEST",

            "username": username,

            "password": password,

        })

        response = self.receive()

        if response.get("status") == "OK":

            self.token = response["token"]

        return response

    def send_message(self, recipient, content, token=None):

        self.send({

            "type": "SEND_MESSAGE",

            "token": token if token is not None else self.token,

            "toUser": recipient,

            "content": content,

        })

    def request_history(self, token=None):

        self.send({

            "type": "HISTORY_REQUEST",

            "token": token if token is not None else self.token,

        })

        return self.receive()

    def close(self):

        try:

            self.stream.close()

        except (OSError, ValueError):

            pass

        try:

            self.sock.close()

        except OSError:

            pass

    def __enter__(self):

        return self

    def __exit__(self, exc_type, exc_value, traceback):

        self.close()

def register_and_login(client, username):

    """Register and authenticate a client on the same connection."""

    registration = client.register(username)

    assert registration["type"] == "REGISTER_RESPONSE"

    assert registration["status"] == "OK"

    login = client.login(username)

    assert login["type"] == "LOGIN_RESPONSE"

    assert login["status"] == "OK"

    assert login["userId"] == username

    assert isinstance(login.get("token"), str)

    assert len(login["token"]) > 20

    return login


def start_file_transfer(client, token, transfer_id, data, filename="payload.bin",
                        recipient=None, room=None):
    request = {
        "type": "FILE_START", "token": token, "filename": filename,
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "transferId": transfer_id,
    }
    if recipient is not None:
        request["toUser"] = recipient
    if room is not None:
        request["roomId"] = room
    client.send(request)
    return client.receive()


def send_file_chunks(client, token, transfer_id, data, timeout=SOCKET_TIMEOUT):
    chunks = [data[offset:offset + server.FILE_CHUNK_SIZE]
              for offset in range(0, len(data), server.FILE_CHUNK_SIZE)] or [b""]
    response = None
    for index, chunk in enumerate(chunks):
        final = index == len(chunks) - 1
        client.send({
            "type": "FILE_CHUNK", "token": token, "transferId": transfer_id,
            "data": base64.b64encode(chunk).decode("ascii"), "final": final,
        })
        response = client.receive(timeout=timeout)
        expected = "FILE_SENT" if final else "FILE_CHUNK_ACK"
        assert response["type"] == expected
        assert response["transferId"] == transfer_id
    return response


def read_received_file(client, transfer_id, chunk_count, timeout=SOCKET_TIMEOUT):
    started = client.receive(timeout=timeout)
    chunks = [client.receive(timeout=timeout) for _ in range(chunk_count)]
    ended = client.receive(timeout=timeout)
    assert started["type"] == "FILE_RECEIVE_START"
    assert started["transferId"] == transfer_id
    assert all(chunk["type"] == "FILE_RECEIVE_CHUNK" for chunk in chunks)
    assert ended["type"] == "FILE_RECEIVE_END"
    return started, b"".join(
        base64.b64decode(chunk["data"], validate=True) for chunk in chunks
    )

def test_server_register_and_login(running_server):

    """A client can register and then authenticate over TCP."""

    with ChatTestClient(running_server) as client:

        register_and_login(client, "tcp_alice")

def test_server_rejects_invalid_login(running_server):

    """Invalid credentials are rejected by the TCP server."""

    with ChatTestClient(running_server) as client:

        response = client.login("nobody", "WrongPass123")

        assert response["type"] == "LOGIN_RESPONSE"

        assert response["status"] == "ERROR"

        assert response["code"] == 401

        # A rejected login closes the socket; the client must reconnect.
        assert client.stream.readline() == b""


def test_tc_sec_05_login_attempts_are_rate_limited_per_ip(running_server):
    """TC-Sec-05: repeated failed logins are blocked after five failures."""
    for attempt in range(server.LOGIN_RATE_MAX_FAILURES):
        with ChatTestClient(running_server) as client:
            response = client.login("nobody", "WrongPass123")
            assert response["code"] == 401

    with ChatTestClient(running_server) as client:
        response = client.login("nobody", "WrongPass123")
        assert response["code"] == 429
        assert response["status"] == "ERROR"
        assert client.stream.readline() == b""


def test_tc_sec_05_successful_login_clears_failure_tracking(running_server, monkeypatch):
    """A successful login resets prior failures for its source IP."""
    with ChatTestClient(running_server) as registration:
        assert registration.register("rate_limit_alice", "Password123")["status"] == "OK"
        assert registration.login("rate_limit_alice", "Password123")["status"] == "OK"

    with server.LOGIN_RATE_LOCK:
        server.LOGIN_FAILURES_BY_IP["127.0.0.1"] = [time.monotonic()] * 4
        server.LOGIN_BLOCKED_UNTIL_BY_IP.pop("127.0.0.1", None)

    with ChatTestClient(running_server) as client:
        response = client.login("rate_limit_alice", "Password123")
        assert response["status"] == "OK"

    with server.LOGIN_RATE_LOCK:
        assert "127.0.0.1" not in server.LOGIN_FAILURES_BY_IP
        assert "127.0.0.1" not in server.LOGIN_BLOCKED_UNTIL_BY_IP

def test_server_rejects_duplicate_registration(running_server):

    """Duplicate usernames are rejected."""

    with ChatTestClient(running_server) as client:

        first = client.register("duplicate_user")

        second = client.register("duplicate_user")

        assert first["status"] == "OK"

        assert second["type"] == "REGISTER_RESPONSE"

        assert second["status"] == "ERROR"

        assert second["code"] == 409

def test_private_message_reaches_only_recipient(running_server):

    """A direct message reaches its intended recipient only."""

    with (

        ChatTestClient(running_server) as alice,

        ChatTestClient(running_server) as bob,

        ChatTestClient(running_server) as charlie,

    ):

        register_and_login(alice, "alice")

        register_and_login(bob, "bob")

        register_and_login(charlie, "charlie")

        alice.send_message("bob", "Hello Bob!")

        incoming = bob.receive()

        assert incoming["type"] == "NEW_MESSAGE"

        assert incoming["fromUser"] == "alice"

        assert incoming["content"] == "Hello Bob!"

        confirmation = alice.receive()

        assert confirmation["type"] == "MESSAGE_DELIVERED"

        assert confirmation["messageId"] == incoming["messageId"]

        expect_no_message(charlie.sock, charlie.stream)
        
def test_tc_msg_02_real_time_delivery_within_latency_target(running_server):
    """TC-Msg-02: Online messages are delivered within the 500 ms target."""
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "latency_alice")
        register_and_login(bob, "latency_bob")

        content = "TC-Msg-02 real-time delivery test"

        start = time.perf_counter()
        alice.send_message("latency_bob", content)
        incoming = bob.receive(timeout=2)
        latency_ms = (time.perf_counter() - start) * 1000

        assert incoming["type"] == "NEW_MESSAGE"
        assert incoming["fromUser"] == "latency_alice"
        assert incoming["content"] == content

        assert latency_ms < 500, (
            f"Delivery latency was {latency_ms:.2f} ms; target is under 500 ms"
        )

        confirmation = alice.receive()
        assert confirmation["type"] == "MESSAGE_DELIVERED"
        assert confirmation["messageId"] == incoming["messageId"]

        print(f"\nTC-Msg-02 delivery latency: {latency_ms:.2f} ms")

def test_message_is_saved_in_history(running_server):

    """Messages appear in the sender's and recipient's history."""

    with (

        ChatTestClient(running_server) as alice,

        ChatTestClient(running_server) as bob,

    ):

        register_and_login(alice, "history_alice")

        register_and_login(bob, "history_bob")

        alice.send_message("history_bob", "Persist this message")

        incoming = bob.receive()

        assert incoming["type"] == "NEW_MESSAGE"

        alice.receive()

        for client in (alice, bob):

            history = client.request_history()

            assert history["type"] == "HISTORY_RESPONSE"

            assert any(

                message["content"] == "Persist this message"

                and message["sender"] == "history_alice"

                and message["recipient"] == "history_bob"

                for message in history["messages"]

            )

def test_history_survives_reconnect(running_server):

    """Message history remains available after reconnecting."""

    with ChatTestClient(running_server) as alice:

        register_and_login(alice, "reconnect_alice")

        with ChatTestClient(running_server) as bob:

            register_and_login(bob, "reconnect_bob")

            alice.send_message(

                "reconnect_bob", "Saved before reconnect"

            )

            bob.receive()

            alice.receive()

        with ChatTestClient(running_server) as bob_again:

            login = bob_again.login("reconnect_bob")

            assert login["status"] == "OK"

            history = bob_again.request_history()

            assert history["type"] == "HISTORY_RESPONSE"

            assert any(

                message["content"] == "Saved before reconnect"

                for message in history["messages"]

            )


def test_history_request_pages_messages_across_the_90_day_window(
    running_server, monkeypatch,
):
    fixed_now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(database, "datetime", FrozenDateTime)
    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "history_90d_alice")
        seeded = [
            ("outside", 90, 1),
            ("boundary", 90, 0),
            ("older than 60 days", 61, 0),
            ("older than 30 days", 31, 0),
            ("recent", 0, 0),
        ]
        for content, days, seconds in seeded:
            message_id = database.save_message(
                "history_90d_alice", "history_90d_bob", content,
                delivered=True,
            )
            created_at = fixed_now - timedelta(days=days, seconds=seconds)
            with database.get_connection() as connection:
                connection.execute(
                    "UPDATE messages SET created_at = ? WHERE id = ?",
                    (created_at.strftime("%Y-%m-%d %H:%M:%S"), message_id),
                )

        pages = []
        before_id = None
        while True:
            request = {
                "type": "HISTORY_REQUEST", "token": alice.token, "limit": 2,
            }
            if before_id is not None:
                request["beforeId"] = before_id
            alice.send(request)
            response = alice.receive()
            assert response["type"] == "HISTORY_RESPONSE"
            pages.append(response["messages"])
            before_id = response["nextBeforeId"]
            if before_id is None:
                break

        chronological = [
            message for page in reversed(pages) for message in page
        ]
        assert [message["content"] for message in chronological] == [
            "boundary", "older than 60 days", "older than 30 days", "recent",
        ]
        assert [message["created_at"] for message in chronological] == sorted(
            message["created_at"] for message in chronological
        )

def test_offline_message_is_stored(running_server):

    """Messages to offline users are stored, not delivered live."""

    with ChatTestClient(running_server) as alice:

        register_and_login(alice, "offline_alice")

        with ChatTestClient(running_server) as bob:

            registration = bob.register("offline_bob")

            assert registration["status"] == "OK"

        alice.send_message("offline_bob", "You were offline")

        response = alice.receive()

        assert response["type"] == "MESSAGE_STORED"

        assert "messageId" in response

        history = alice.request_history()

        assert any(

            message["content"] == "You were offline"

            and message["recipient"] == "offline_bob"

            for message in history["messages"]

        )

@pytest.mark.parametrize(
    "token",
    [None, "invalid-token"],
    ids=["missing-token", "invalid-token"],
)
def test_unauthenticated_message_is_rejected(running_server, token):

    """Sending a message without a valid session is rejected."""

    with ChatTestClient(running_server) as client:

        registration = client.register("unauthenticated_sender")

        assert registration["status"] == "OK"

        request = {

            "type": "SEND_MESSAGE",

            "toUser": "someone",

            "content": "This should be rejected",

        }

        if token is not None:

            request["token"] = token

        client.send(request)

        response = client.receive()

        assert response["type"] == "MESSAGE_ERROR"

        assert response["code"] == 401

@pytest.mark.parametrize(
    "token",
    [None, "invalid-token"],
    ids=["missing-token", "invalid-token"],
)
def test_history_requires_authentication(running_server, token):
    """History requests require a valid session."""
    with ChatTestClient(running_server) as client:
        request = {"type": "HISTORY_REQUEST"}
        if token is not None:
            request["token"] = token
        client.send(request)
        response = client.receive()
        assert response["type"] == "ERROR"
        assert response["code"] == 401

@pytest.mark.parametrize(
    "request_type,response_type",
    [
        ("TYPING", "TYPING_RESPONSE"),
        ("FILE_START", "FILE_ERROR"),
        ("FILE_CHUNK", "FILE_ERROR"),
        ("LOGOUT_REQUEST", "ERROR"),
    ],
)
@pytest.mark.parametrize(
    "token",
    [None, "invalid-token"],
    ids=["missing-token", "invalid-token"],
)
def test_session_token_is_required_for_protected_requests(
    running_server, request_type, response_type, token
):
    """Every remaining authenticated operation rejects absent or bad tokens."""
    with ChatTestClient(running_server) as client:
        request = {"type": request_type}
        if token is not None:
            request["token"] = token

        client.send(request)
        response = client.receive()

        assert response["type"] == response_type
        assert response["code"] == 401

def test_successful_logout_closes_connection_and_removes_active_client(
    running_server,
):
    """Successful logout closes the socket and removes the active client."""
    with ChatTestClient(running_server) as client:
        register_and_login(client, "logout_test_user")
        token = client.token

        with server.ACTIVE_CLIENTS_LOCK:
            assert "logout_test_user" in server.ACTIVE_CLIENTS

        client.send({
            "type": "LOGOUT_REQUEST",
            "token": token,
        })

        response = client.receive()
        assert response["type"] == "LOGOUT_RESPONSE"
        assert response["status"] == "OK"

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with server.ACTIVE_CLIENTS_LOCK:
                if "logout_test_user" not in server.ACTIVE_CLIENTS:
                    break
            time.sleep(0.01)

        with server.ACTIVE_CLIENTS_LOCK:
            assert "logout_test_user" not in server.ACTIVE_CLIENTS

        client.sock.settimeout(1.0)
        assert client.stream.readline() == b""


def test_tls_handshake_round_trips_application_data(tmp_path, monkeypatch):
    """TC-Sec-01: configured server accepts a TLS 1.2+ connection."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL executable is required for the TLS handshake test")

    cert_file = tmp_path / "server-cert.pem"
    key_file = tmp_path / "server-key.pem"
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key_file), "-out", str(cert_file), "-days", "1",
        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
    ], check=True, capture_output=True)

    monkeypatch.setenv("CHAT_TLS_CERT_FILE", str(cert_file))
    monkeypatch.setenv("CHAT_TLS_KEY_FILE", str(key_file))
    test_server = server.ChatServer((HOST, 0), server.ChatHandler)
    thread = threading.Thread(target=test_server.serve_forever, daemon=True)
    thread.start()

    try:
        raw_socket = socket.create_connection(test_server.server_address, timeout=3)
        context = ssl.create_default_context(cafile=str(cert_file))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_socket = context.wrap_socket(raw_socket, server_hostname="127.0.0.1")
        tls_socket.sendall(b"{not valid json}\n")
        response = receive_json(tls_socket, tls_socket.makefile("rb"))
        assert response["type"] == "ERROR"
        assert response["code"] == 400
        tls_socket.close()
    finally:
        test_server.shutdown()
        test_server.server_close()
        thread.join(timeout=3)


def test_tc_perf_01_100_clients_p95_below_500ms(tmp_path):
    """TC-Perf-01: run the load script with 100 clients and verify p95 latency."""
    repository_root = Path(__file__).resolve().parents[1]
    raw_output = tmp_path / "tc-perf-01-raw.csv"
    completed = subprocess.run([
        sys.executable,
        str(repository_root / "scripts" / "measure_message_latency.py"),
        "--clients", "100",
        "--samples-per-client", "1",
        "--raw-output", str(raw_output),
    ], cwd=repository_root, capture_output=True, text=True, timeout=120)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    metadata = json.loads(raw_output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert metadata["concurrent_clients"] == 100
    assert metadata["sample_count"] == 100
    assert metadata["p95_latency_ms"] <= metadata["target_ms"]
    assert metadata["result"] == "PASS"


def test_tc_scale_01_200_clients_remain_connected(tmp_path):
    """TC-Scale-01: verify 200 concurrent authenticated sessions stay active."""
    repository_root = Path(__file__).resolve().parents[1]
    raw_output = tmp_path / "tc-scale-01-raw.csv"
    completed = subprocess.run([
        sys.executable,
        str(repository_root / "scripts" / "measure_concurrent_clients.py"),
        "--clients", "200",
        "--stability-seconds", "2",
        "--raw-output", str(raw_output),
    ], cwd=repository_root, capture_output=True, text=True, timeout=300)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    metadata = json.loads(raw_output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert metadata["concurrent_clients"] == 200
    assert metadata["active_sessions_verified"] == 200
    assert metadata["dropped_sessions"] == 0
    assert metadata["result"] == "PASS"


def test_silent_disconnect_is_removed_from_presence_and_session(
    running_server, monkeypatch
):
    """TC-Auth-04 / TC-Rel-01: unresponsive clients lose presence and sessions."""
    monkeypatch.setattr(server, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(server, "HEARTBEAT_TIMEOUT_SECONDS", 0.25)

    with ChatTestClient(running_server) as client:
        register_and_login(client, "silent_disconnect_user")
        token = client.token

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with server.ACTIVE_CLIENTS_LOCK:
                still_present = "silent_disconnect_user" in server.ACTIVE_CLIENTS
            session_user = database.get_session_user(token)
            if not still_present and session_user is None:
                break
            time.sleep(0.02)

        with server.ACTIVE_CLIENTS_LOCK:
            assert "silent_disconnect_user" not in server.ACTIVE_CLIENTS
        assert database.get_session_user(token) is None


def test_malformed_json_returns_error_and_connection_recovers(

    running_server,

):

    """Malformed JSON returns 400 and the connection remains usable."""

    with ChatTestClient(running_server) as client:

        client.sock.sendall(b"{not valid json}\n")

        error = client.receive()

        assert error["type"] == "ERROR"

        assert error["code"] == 400

        response = client.register("after_bad_json")

        assert response["type"] == "REGISTER_RESPONSE"

        assert response["status"] == "OK"

def test_unknown_request_returns_error(running_server):

    """Unknown request types are rejected."""

    with ChatTestClient(running_server) as client:

        client.send({"type": "NOT_A_REAL_REQUEST"})

        response = client.receive()

        assert response["type"] == "ERROR"

        assert response["code"] == 400

def test_empty_message_is_rejected(running_server):

    """Whitespace-only message content is rejected."""

    with (

        ChatTestClient(running_server) as alice,

        ChatTestClient(running_server) as bob,

    ):

        register_and_login(alice, "emptymsg_alice")

        register_and_login(bob, "emptymsg_bob")

        alice.send_message("emptymsg_bob", "   ")

        response = alice.receive()

        assert response["type"] == "MESSAGE_ERROR"

        assert response["code"] == 400

def test_unknown_recipient_is_rejected(running_server):

    """Messages to nonexistent recipients return 404."""

    with ChatTestClient(running_server) as alice:

        register_and_login(alice, "unknownrecipient_alice")

        alice.send_message("no_such_user", "Hello?")

        response = alice.receive()

        assert response["type"] == "MESSAGE_ERROR"

        assert response["code"] == 404

def test_typing_indicator_is_sent_to_recipient_and_clears(running_server):
    """Typing true/false events reach the target and no unrelated client."""
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
        ChatTestClient(running_server) as charlie,
    ):
        register_and_login(alice, "typing_alice")
        register_and_login(bob, "typing_bob")
        register_and_login(charlie, "typing_charlie")

        started_at = time.monotonic()
        alice.send({
            "type": "TYPING",
            "token": alice.token,
            "toUser": "typing_bob",
            "isTyping": True,
        })

        started = bob.receive()
        assert started["type"] == "TYPING_INDICATOR"
        assert started["fromUser"] == "typing_alice"
        assert started["isTyping"] is True
        assert time.monotonic() - started_at < 2
        assert alice.receive()["type"] == "TYPING_RESPONSE"

        stopped_at = time.monotonic()
        alice.send({
            "type": "TYPING",
            "token": alice.token,
            "toUser": "typing_bob",
            "isTyping": False,
        })

        stopped = bob.receive()
        assert stopped["type"] == "TYPING_INDICATOR"
        assert stopped["fromUser"] == "typing_alice"
        assert stopped["isTyping"] is False
        assert time.monotonic() - stopped_at < 2
        assert alice.receive()["type"] == "TYPING_RESPONSE"

        expect_no_message(charlie.sock, charlie.stream)

def test_typing_indicator_requires_authentication(running_server):
    """Unauthenticated clients cannot broadcast typing events."""
    with ChatTestClient(running_server) as client:
        client.send({
            "type": "TYPING",
            "token": "invalid-token",
            "toUser": "someone",
            "isTyping": True,
        })

        response = client.receive()
        assert response["type"] == "TYPING_RESPONSE"
        assert response["status"] == "ERROR"
        assert response["code"] == 401


def test_typing_indicator_deduplicates_repeated_state_and_rejects_bad_recipient(
    running_server,
):
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "typing_repeat_alice")
        register_and_login(bob, "typing_repeat_bob")

        request = {
            "type": "TYPING", "token": alice.token,
            "toUser": "typing_repeat_bob", "isTyping": True,
        }
        alice.send(request)
        assert bob.receive()["isTyping"] is True
        assert alice.receive()["status"] == "OK"

        alice.send(request)
        assert alice.receive()["status"] == "OK"
        expect_no_message(bob.sock, bob.stream)

        alice.send({**request, "toUser": "missing_typing_user"})
        response = alice.receive()
        assert response["type"] == "TYPING_RESPONSE"
        assert response["code"] == 404


def test_typing_state_clears_on_disconnect_and_expiry(running_server):
    with ChatTestClient(running_server) as bob:
        alice = ChatTestClient(running_server)
        register_and_login(alice, "typing_cleanup_alice")
        register_and_login(bob, "typing_cleanup_bob")
        key = ("typing_cleanup_alice", "user", "typing_cleanup_bob")
        request = {
            "type": "TYPING", "token": alice.token,
            "toUser": "typing_cleanup_bob", "isTyping": True,
        }

        alice.send(request)
        assert bob.receive()["isTyping"] is True
        assert alice.receive()["status"] == "OK"
        with server.TYPING_LOCK:
            server.TYPING_STATES[key] = time.monotonic() - server.TYPING_STATE_TIMEOUT_SECONDS - 1
        server.expire_stale_typing_states()
        expired = bob.receive()
        assert expired["type"] == "TYPING_INDICATOR"
        assert expired["isTyping"] is False
        assert key not in server.TYPING_STATES

        alice.send(request)
        assert bob.receive()["isTyping"] is True
        assert alice.receive()["status"] == "OK"
        disconnected_at = time.monotonic()
        alice.close()
        stopped = bob.receive()
        assert stopped["type"] == "TYPING_INDICATOR"
        assert stopped["fromUser"] == "typing_cleanup_alice"
        assert stopped["isTyping"] is False
        assert time.monotonic() - disconnected_at < 2
        assert key not in server.TYPING_STATES


def test_typing_state_expires_within_two_seconds(running_server):
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "typing_expiry_alice")
        register_and_login(bob, "typing_expiry_bob")
        key = ("typing_expiry_alice", "user", "typing_expiry_bob")

        started_at = time.monotonic()
        alice.send({
            "type": "TYPING", "token": alice.token,
            "toUser": "typing_expiry_bob", "isTyping": True,
        })
        assert bob.receive()["isTyping"] is True
        assert alice.receive()["status"] == "OK"

        stopped = bob.receive(timeout=2)
        assert stopped["type"] == "TYPING_INDICATOR"
        assert stopped["fromUser"] == "typing_expiry_alice"
        assert stopped["isTyping"] is False
        assert time.monotonic() - started_at < 2
        assert key not in server.TYPING_STATES


def test_file_transfer_preserves_bytes_and_checksum(running_server):
    """TC-File-01: recipient receives the exact file bytes and SHA-256."""
    original = bytes(range(256)) * 40  # Binary data containing arbitrary byte values.
    checksum = hashlib.sha256(original).hexdigest()
    transfer_id = "binary-transfer-1"
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "file_binary_alice")
        register_and_login(bob, "file_binary_bob")

        ready = start_file_transfer(
            alice, alice.token, transfer_id, original,
            recipient="file_binary_bob",
        )
        assert ready["type"] == "FILE_READY"
        assert send_file_chunks(alice, alice.token, transfer_id, original)["sha256"] == checksum

        metadata, received = read_received_file(
            bob, transfer_id,
            (len(original) + server.FILE_CHUNK_SIZE - 1) // server.FILE_CHUNK_SIZE,
        )
        assert metadata["fromUser"] == "file_binary_alice"
        assert metadata["filename"] == "payload.bin"
        assert metadata["sha256"] == checksum
        assert received == original
        assert hashlib.sha256(received).hexdigest() == checksum


def test_file_transfer_supports_empty_file_and_isolated_transfer_ids(running_server):
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "file_multi_alice")
        register_and_login(bob, "file_multi_bob")

        for transfer_id, filename, data in (
            ("empty-transfer", "empty.bin", b""),
            ("second-transfer", "second.bin", b"second payload"),
        ):
            ready = start_file_transfer(
                alice, alice.token, transfer_id, data, filename,
                recipient="file_multi_bob",
            )
            assert ready["type"] == "FILE_READY"
            sent = send_file_chunks(alice, alice.token, transfer_id, data)
            assert sent["size"] == len(data)
            metadata, received = read_received_file(bob, transfer_id,
                                                     1 if data else 0)
            assert metadata["filename"] == filename
            assert received == data


def test_file_transfer_broadcasts_only_to_online_room_members(running_server):
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
        ChatTestClient(running_server) as carol,
        ChatTestClient(running_server) as outsider,
    ):
        register_and_login(alice, "file_room_alice")
        register_and_login(bob, "file_room_bob")
        register_and_login(carol, "file_room_carol")
        register_and_login(outsider, "file_room_outside")
        alice.send({"type": "CREATE_ROOM", "token": alice.token, "room": "Files"})
        assert alice.receive()["status"] == "OK"
        bob.send({"type": "JOIN_ROOM", "token": bob.token, "room": "Files"})
        assert bob.receive()["status"] == "OK"
        assert alice.receive()["type"] == "ROOM_EVENT"
        carol.send({"type": "JOIN_ROOM", "token": carol.token, "room": "Files"})
        assert carol.receive()["status"] == "OK"
        assert alice.receive()["type"] == "ROOM_EVENT"
        assert bob.receive()["type"] == "ROOM_EVENT"

        data = bytes(range(64))
        transfer_id = "room-file-transfer"
        ready = start_file_transfer(alice, alice.token, transfer_id, data, room="Files")
        assert ready["type"] == "FILE_READY"
        sent = send_file_chunks(alice, alice.token, transfer_id, data)
        assert sent["deliveredTo"] == 2
        for recipient in (bob, carol):
            metadata, received = read_received_file(recipient, transfer_id, 1)
            assert metadata["roomId"] == "Files"
            assert received == data
        expect_no_message(outsider.sock, outsider.stream, timeout=0.3)

# ---------------------------------------------------------------------------
# TC-Msg-03 (CHAT-F-012): queue messages for offline users, deliver on login
# ---------------------------------------------------------------------------


def wait_for_no_pending(username, timeout=3):
    """Poll until a user has no queued messages left.

    The server marks a message delivered just after writing it to the socket,
    so a client can receive it a moment before the database is updated.
    """
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not database.get_pending_messages(username):
            return True
        time.sleep(0.05)

    return not database.get_pending_messages(username)


def register_offline_user(running_server, username):
    """Register a user and disconnect, leaving them offline."""
    with ChatTestClient(running_server) as client:
        assert client.register(username)["status"] == "OK"


def test_msg_03_offline_messages_are_stored(running_server):
    """TC-Msg-03: messages sent to an offline user are stored, undelivered."""
    register_offline_user(running_server, "queue_bob")

    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "queue_alice")

        for text in ("first", "second", "third"):
            alice.send_message("queue_bob", text)
            assert alice.receive()["type"] == "MESSAGE_STORED"

    pending = database.get_pending_messages("queue_bob")

    assert [message["content"] for message in pending] == [
        "first",
        "second",
        "third",
    ]
    assert {message["sender"] for message in pending} == {"queue_alice"}


def test_msg_03_queued_messages_delivered_in_order_on_login(running_server):
    """TC-Msg-03: queued messages arrive in original order after login."""
    register_offline_user(running_server, "order_bob")

    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as charlie,
    ):
        register_and_login(alice, "order_alice")
        register_and_login(charlie, "order_charlie")

        # Interleave two senders: the original send order must be preserved.
        sent_order = [
            (alice, "order_alice", "m1 from alice"),
            (charlie, "order_charlie", "m2 from charlie"),
            (alice, "order_alice", "m3 from alice"),
            (charlie, "order_charlie", "m4 from charlie"),
            (alice, "order_alice", "m5 from alice"),
        ]

        for client, _, text in sent_order:
            client.send_message("order_bob", text)
            assert client.receive()["type"] == "MESSAGE_STORED"

        with ChatTestClient(running_server) as bob:
            login = bob.login("order_bob")

            # The login response always comes first, then the backlog.
            assert login["type"] == "LOGIN_RESPONSE"
            assert login["status"] == "OK"

            received = [bob.receive() for _ in sent_order]

    assert all(message["type"] == "NEW_MESSAGE" for message in received)
    assert [message["content"] for message in received] == [
        text for _, _, text in sent_order
    ]
    assert [message["fromUser"] for message in received] == [
        sender for _, sender, _ in sent_order
    ]

    message_ids = [int(message["messageId"]) for message in received]
    assert message_ids == sorted(message_ids)
    assert all(message.get("queued") is True for message in received)
    assert all(message.get("timestamp") for message in received)


def test_msg_03_queued_messages_are_delivered_only_once(running_server):
    """TC-Msg-03: a replayed message is not delivered again on later logins."""
    register_offline_user(running_server, "once_bob")

    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "once_alice")
        alice.send_message("once_bob", "deliver me once")
        assert alice.receive()["type"] == "MESSAGE_STORED"

    with ChatTestClient(running_server) as bob:
        assert bob.login("once_bob")["status"] == "OK"
        assert bob.receive()["content"] == "deliver me once"

    assert wait_for_no_pending("once_bob")

    with ChatTestClient(running_server) as bob_again:
        assert bob_again.login("once_bob")["status"] == "OK"
        expect_no_message(bob_again.sock, bob_again.stream)


def test_msg_03_live_messages_are_not_queued(running_server):
    """TC-Msg-03: Messages delivered live are not replayed on next login."""

    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "live_alice")

        with ChatTestClient(running_server) as bob:
            register_and_login(bob, "live_bob")

            alice.send_message("live_bob", "Hello while online")

            incoming = bob.receive()
            assert incoming["type"] == "NEW_MESSAGE"
            assert incoming["fromUser"] == "live_alice"
            assert incoming["content"] == "Hello while online"

            confirmation = alice.receive()
            assert confirmation["type"] == "MESSAGE_DELIVERED"
            assert confirmation["messageId"] == incoming["messageId"]

        # Bob disconnects and logs in again.
        with ChatTestClient(running_server) as bob_again:
            response = bob_again.login("live_bob")
            assert response["type"] == "LOGIN_RESPONSE"
            assert response["status"] == "OK"

            # A message delivered live must not be replayed.
            expect_no_message(
                bob_again.sock,
                bob_again.stream,
                timeout=0.5,
            )


@pytest.mark.parametrize(
    "size", [server.MAX_FILE_SIZE + 1, server.MAX_FILE_SIZE * 100],
    ids=["one-byte-over", "significantly-over"],
)
def test_file_transfer_rejects_file_over_configured_limit(running_server, size):
    """Oversized file metadata is rejected before any file data is sent."""
    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "oversize_sender")
        transfer_id = "oversized-transfer"
        alice.send({
            "type": "FILE_START",
            "token": alice.token,
            "toUser": "not_needed_for_oversize_validation",
            "filename": "too-large.bin",
            "size": size,
            "sha256": "a" * 64,
            "transferId": transfer_id,
        })
        response = alice.receive()
        assert response["type"] == "FILE_ERROR"
        assert response["code"] == 413
        assert response["message"]
        assert transfer_id not in server.ACTIVE_FILE_TRANSFERS
        alice.send({
            "type": "FILE_CHUNK", "token": alice.token,
            "transferId": transfer_id, "data": "", "final": True,
        })
        rejected_chunk = alice.receive()
        assert rejected_chunk["type"] == "FILE_ERROR"
        assert rejected_chunk["code"] == 404


@pytest.mark.parametrize("size", [-1, "12", None, True, 1.5],
                         ids=["negative", "string", "null", "boolean", "float"])
def test_file_transfer_rejects_invalid_sizes_before_accepting_chunks(
    running_server, size
):
    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "invalid_size_sender")
        transfer_id = f"invalid-size-{type(size).__name__}"
        request = {
            "type": "FILE_START", "token": alice.token,
            "toUser": "recipient-not-checked-for-invalid-size",
            "filename": "payload.bin", "sha256": "a" * 64,
            "transferId": transfer_id,
        }
        if size is not None:
            request["size"] = size
        alice.send(request)
        response = alice.receive()
        assert response["type"] == "FILE_ERROR"
        assert response["code"] == 400
        assert transfer_id not in server.ACTIVE_FILE_TRANSFERS


def test_file_transfer_rejects_missing_size_and_unsafe_filename(running_server):
    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "invalid_metadata_sender")
        for index, fields in enumerate((
            {"filename": "missing-size.bin"},
            {"filename": "../escape.bin", "size": 1},
            {"filename": "..\\escape.bin", "size": 1},
            {"filename": "C:escape.bin", "size": 1},
        )):
            transfer_id = f"invalid-metadata-{index}"
            alice.send({
                "type": "FILE_START", "token": alice.token,
                "toUser": "recipient-not-checked-for-invalid-metadata",
                "sha256": "a" * 64, "transferId": transfer_id, **fields,
            })
            response = alice.receive()
            assert response["type"] == "FILE_ERROR"
            assert response["code"] == 400
            assert transfer_id not in server.ACTIVE_FILE_TRANSFERS


def test_file_transfer_at_exact_limit_is_accepted_and_intact(running_server):
    original = bytes(range(256)) * (server.MAX_FILE_SIZE // 256)
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "limit_sender")
        register_and_login(bob, "limit_recipient")
        transfer_id = "exact-limit-transfer"
        ready = start_file_transfer(
            alice, alice.token, transfer_id, original,
            recipient="limit_recipient",
        )
        assert ready["type"] == "FILE_READY"
        received_file = {}
        receiver_thread = threading.Thread(
            target=lambda: received_file.setdefault(
                "value",
                read_received_file(
                    bob, transfer_id,
                    server.MAX_FILE_SIZE // server.FILE_CHUNK_SIZE,
                    timeout=30,
                ),
            ),
            daemon=True,
        )
        receiver_thread.start()
        sent = send_file_chunks(alice, alice.token, transfer_id, original, timeout=30)
        assert sent["size"] == server.MAX_FILE_SIZE
        receiver_thread.join(timeout=30)
        assert not receiver_thread.is_alive()
        metadata, received = received_file["value"]
        assert metadata["size"] == server.MAX_FILE_SIZE
        assert received == original


def test_file_transfer_cleans_up_interrupted_upload(running_server):
    with ChatTestClient(running_server) as recipient:
        register_and_login(recipient, "interrupted_recipient")
        alice = ChatTestClient(running_server)
        register_and_login(alice, "interrupted_sender")
        transfer_id = "interrupted-transfer"
        ready = start_file_transfer(
            alice, alice.token, transfer_id, b"0123456789",
            recipient="interrupted_recipient",
        )
        assert ready["type"] == "FILE_READY"
        alice.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if transfer_id not in server.ACTIVE_FILE_TRANSFERS:
                break
            time.sleep(0.01)
        assert transfer_id not in server.ACTIVE_FILE_TRANSFERS


def test_file_transfer_rejects_recipient_disconnect_and_releases_state(running_server):
    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "disconnect_sender")
        bob = ChatTestClient(running_server)
        register_and_login(bob, "disconnect_recipient")
        transfer_id = "recipient-disconnect-transfer"
        ready = start_file_transfer(
            alice, alice.token, transfer_id, b"x", recipient="disconnect_recipient",
        )
        assert ready["type"] == "FILE_READY"
        bob.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with server.ACTIVE_CLIENTS_LOCK:
                if "disconnect_recipient" not in server.ACTIVE_CLIENTS:
                    break
            time.sleep(0.01)
        alice.send({
            "type": "FILE_CHUNK", "token": alice.token, "transferId": transfer_id,
            "data": base64.b64encode(b"x").decode("ascii"), "final": True,
        })
        response = alice.receive()
        assert response["type"] == "FILE_ERROR" and response["code"] == 404
        assert transfer_id not in server.ACTIVE_FILE_TRANSFERS


def test_file_transfer_expires_abandoned_state(running_server):
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "expiry_sender")
        register_and_login(bob, "expiry_recipient")
        transfer_id = "expired-transfer"
        ready = start_file_transfer(
            alice, alice.token, transfer_id, b"pending", recipient="expiry_recipient",
        )
        assert ready["type"] == "FILE_READY"
        owner, _ = server.ACTIVE_FILE_TRANSFERS[transfer_id]
        with server.FILE_TRANSFER_LOCK:
            server.ACTIVE_FILE_TRANSFERS[transfer_id] = (
                owner, time.monotonic() - server.FILE_TRANSFER_TIMEOUT_SECONDS - 1,
            )
        server.expire_stale_file_transfers()
        assert transfer_id not in server.ACTIVE_FILE_TRANSFERS
        assert transfer_id not in owner.file_transfers


def test_file_transfer_idle_timeout_resets_after_valid_chunk(running_server):
    data = b"xy"
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "idle_timeout_sender")
        register_and_login(bob, "idle_timeout_recipient")
        transfer_id = "idle-timeout-transfer"
        ready = start_file_transfer(
            alice, alice.token, transfer_id, data,
            recipient="idle_timeout_recipient",
        )
        assert ready["type"] == "FILE_READY"

        with server.FILE_TRANSFER_LOCK:
            owner, _ = server.ACTIVE_FILE_TRANSFERS[transfer_id]
            old_timestamp = time.monotonic() - server.FILE_TRANSFER_TIMEOUT_SECONDS - 1
            server.ACTIVE_FILE_TRANSFERS[transfer_id] = (
                owner, old_timestamp,
            )

        alice.send({
            "type": "FILE_CHUNK", "token": alice.token,
            "transferId": transfer_id,
            "data": base64.b64encode(data[:1]).decode("ascii"),
            "final": False,
        })
        assert alice.receive()["type"] == "FILE_CHUNK_ACK"
        with server.FILE_TRANSFER_LOCK:
            refreshed_at = server.ACTIVE_FILE_TRANSFERS[transfer_id][1]
        assert refreshed_at > old_timestamp
        server.expire_stale_file_transfers(
            now=old_timestamp + server.FILE_TRANSFER_TIMEOUT_SECONDS + 1,
        )
        assert transfer_id in server.ACTIVE_FILE_TRANSFERS

        sent = send_file_chunks(alice, alice.token, transfer_id, data[1:])
        assert sent["type"] == "FILE_SENT"
        _, received = read_received_file(bob, transfer_id, 1)
        assert received == data


def test_room_file_transfer_skips_member_who_leaves_during_upload(running_server):
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
        ChatTestClient(running_server) as carol,
    ):
        register_and_login(alice, "room_transfer_sender")
        register_and_login(bob, "room_transfer_leaver")
        register_and_login(carol, "room_remaining_carol")
        alice.send({"type": "CREATE_ROOM", "token": alice.token, "room": "General"})
        assert alice.receive()["status"] == "OK"
        bob.send({"type": "JOIN_ROOM", "token": bob.token, "room": "General"})
        assert bob.receive()["status"] == "OK"
        assert alice.receive()["type"] == "ROOM_EVENT"
        carol.send({"type": "JOIN_ROOM", "token": carol.token, "room": "General"})
        assert carol.receive()["status"] == "OK"
        assert alice.receive()["type"] == "ROOM_EVENT"
        assert bob.receive()["type"] == "ROOM_EVENT"

        data = b"private room data"
        transfer_id = "room-member-leaves-during-upload"
        ready = start_file_transfer(
            alice, alice.token, transfer_id, data, room="General",
        )
        assert ready["type"] == "FILE_READY"

        bob.send({"type": "LEAVE_ROOM", "token": bob.token, "room": "General"})
        assert bob.receive()["status"] == "OK"
        assert alice.receive()["type"] == "ROOM_EVENT"
        assert carol.receive()["type"] == "ROOM_EVENT"

        sent = send_file_chunks(alice, alice.token, transfer_id, data)
        assert sent["type"] == "FILE_SENT"
        assert sent["deliveredTo"] == 1
        _, received = read_received_file(
            carol, transfer_id, 1,
        )
        assert received == data
        expect_no_message(bob.sock, bob.stream)
        assert transfer_id not in server.ACTIVE_FILE_TRANSFERS

def test_msg_03_only_the_recipient_receives_the_backlog(running_server):
    """TC-Msg-03: another user's login does not receive queued messages."""
    register_offline_user(running_server, "private_bob")

    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "private_alice")
        alice.send_message("private_bob", "for bob only")
        assert alice.receive()["type"] == "MESSAGE_STORED"

    with ChatTestClient(running_server) as charlie:
        register_and_login(charlie, "private_charlie")
        expect_no_message(charlie.sock, charlie.stream)

    assert len(database.get_pending_messages("private_bob")) == 1
def test_sec_02_no_plaintext_password_in_server_logs(
    running_server, capsys, caplog
):
    """TC-Sec-02: passwords never appear in server output or log records."""
    caplog.set_level("DEBUG")

    good_password = "LogCheck#Good123"
    wrong_password = "LogCheck#Wrong456"

    with ChatTestClient(running_server) as client:
        assert client.register("log_user", good_password)["status"] == "OK"
        assert client.register("log_user", good_password)["status"] == "ERROR"
        assert client.login("log_user", wrong_password)["status"] == "ERROR"

    # A failed login closes its connection, so retry on a fresh client socket.
    with ChatTestClient(running_server) as client:
        assert client.login("log_user", good_password)["status"] == "OK"

    # Allow the handler thread to log the disconnect before reading output.
    time.sleep(0.5)

    captured = capsys.readouterr()
    output = captured.out + captured.err
    log_text = "\n".join(record.getMessage() for record in caplog.records)

    # Guard against a vacuous pass: the server really did write to the log.
    assert "[CONNECT]" in output

    for secret in (good_password, wrong_password):
        assert secret not in output
        assert secret not in log_text


def test_tc_admin_01_announcement_reaches_all_active_clients_within_latency(
    running_server, monkeypatch
):
    """Configured admins can broadcast an announcement to every online user."""
    monkeypatch.setenv("CHAT_ADMIN_USERS", "site_admin")

    with (
        ChatTestClient(running_server) as admin,
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(admin, "site_admin")
        register_and_login(alice, "announcement_alice")
        register_and_login(bob, "announcement_bob")

        started = time.perf_counter()
        admin.send({
            "type": "ADMIN_BROADCAST",
            "token": admin.token,
            "message": "Scheduled maintenance at 18:00 UTC",
        })

        announcements = [
            client.receive(timeout=0.5)
            for client in (admin, alice, bob)
        ]
        latency_ms = (time.perf_counter() - started) * 1000

        for announcement in announcements:
            assert announcement["type"] == "ADMIN_ANNOUNCEMENT"
            assert announcement["adminId"] == "site_admin"
            assert announcement["message"] == "Scheduled maintenance at 18:00 UTC"
            assert announcement["timestamp"]

        response = admin.receive(timeout=0.5)
        assert response["type"] == "ADMIN_BROADCAST_RESPONSE"
        assert response["status"] == "OK"
        assert response["deliveredTo"] == 3
        assert latency_ms < 500


def test_tc_admin_01_non_admin_cannot_broadcast(running_server, monkeypatch):
    """Only usernames in the server administrator allowlist may broadcast."""
    monkeypatch.setenv("CHAT_ADMIN_USERS", "site_admin")

    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "ordinary_alice")
        register_and_login(bob, "ordinary_bob")

        alice.send({
            "type": "ADMIN_BROADCAST",
            "token": alice.token,
            "message": "Unauthorized announcement",
        })

        response = alice.receive()
        assert response["type"] == "ADMIN_BROADCAST_RESPONSE"
        assert response["status"] == "ERROR"
        assert response["code"] == 403
        expect_no_message(bob.sock, bob.stream)


def test_tc_admin_02_kick_closes_target_socket(running_server, monkeypatch):
    """An administrator kick notifies and disconnects an online user."""
    monkeypatch.setenv("CHAT_ADMIN_USERS", "moderation_admin")

    with (
        ChatTestClient(running_server) as admin,
        ChatTestClient(running_server) as target,
    ):
        register_and_login(admin, "moderation_admin")
        register_and_login(target, "kick_target")

        admin.send({
            "type": "ADMIN_KICK",
            "token": admin.token,
            "username": "kick_target",
            "reason": "Testing moderator kick",
        })

        response = admin.receive()
        assert response["type"] == "ADMIN_MODERATION_RESPONSE"
        assert response["status"] == "OK"
        assert response["action"] == "kick"
        assert response["username"] == "kick_target"
        assert response["disconnected"] is True

        notice = target.receive()
        assert notice["type"] == "ADMIN_MODERATION_NOTICE"
        assert notice["action"] == "kick"
        assert notice["adminId"] == "moderation_admin"
        assert target.stream.readline() == b""


def test_tc_admin_02_ban_disconnects_and_refuses_later_login(
    running_server, monkeypatch
):
    """A ban disconnects the user and remains enforced at their next login."""
    monkeypatch.setenv("CHAT_ADMIN_USERS", "moderation_admin")

    with (
        ChatTestClient(running_server) as admin,
        ChatTestClient(running_server) as target,
    ):
        register_and_login(admin, "moderation_admin")
        register_and_login(target, "ban_target")

        admin.send({
            "type": "ADMIN_BAN",
            "token": admin.token,
            "username": "ban_target",
            "reason": "Repeated abuse",
        })

        response = admin.receive()
        assert response["type"] == "ADMIN_MODERATION_RESPONSE"
        assert response["status"] == "OK"
        assert response["action"] == "ban"
        assert response["username"] == "ban_target"
        assert response["disconnected"] is True

        notice = target.receive()
        assert notice["type"] == "ADMIN_MODERATION_NOTICE"
        assert notice["action"] == "ban"
        assert notice["adminId"] == "moderation_admin"
        assert target.stream.readline() == b""

        assert database.is_user_banned("ban_target")

    with ChatTestClient(running_server) as banned_user:
        response = banned_user.login("ban_target")
        assert response["type"] == "LOGIN_RESPONSE"
        assert response["status"] == "ERROR"
        assert response["code"] == 403
        assert banned_user.stream.readline() == b""


def test_tc_admin_03_admin_actions_are_audited_with_actor_and_timestamp(
    running_server, monkeypatch
):
    """Broadcast, kick, and ban actions retain their admin and timestamp."""
    monkeypatch.setenv("CHAT_ADMIN_USERS", "audit_admin")

    with (
        ChatTestClient(running_server) as admin,
        ChatTestClient(running_server) as kick_target,
        ChatTestClient(running_server) as ban_target,
    ):
        register_and_login(admin, "audit_admin")
        register_and_login(kick_target, "audit_kick_target")
        register_and_login(ban_target, "audit_ban_target")

        admin.send({
            "type": "ADMIN_BROADCAST",
            "token": admin.token,
            "message": "Audit test announcement",
        })
        for client in (admin, kick_target, ban_target):
            assert client.receive()["type"] == "ADMIN_ANNOUNCEMENT"
        assert admin.receive()["status"] == "OK"

        admin.send({
            "type": "ADMIN_KICK",
            "token": admin.token,
            "username": "audit_kick_target",
            "reason": "Audit test kick",
        })
        assert admin.receive()["status"] == "OK"
        assert kick_target.receive()["type"] == "ADMIN_MODERATION_NOTICE"
        assert kick_target.stream.readline() == b""

        admin.send({
            "type": "ADMIN_BAN",
            "token": admin.token,
            "username": "audit_ban_target",
            "reason": "Audit test ban",
        })
        assert admin.receive()["status"] == "OK"
        assert ban_target.receive()["type"] == "ADMIN_MODERATION_NOTICE"
        assert ban_target.stream.readline() == b""

    entries = database.get_admin_audit_log()
    assert [entry["action"] for entry in entries] == ["broadcast", "kick", "ban"]
    assert all(entry["admin_id"] == "audit_admin" for entry in entries)
    assert [entry["target"] for entry in entries] == [
        None, "audit_kick_target", "audit_ban_target"
    ]
    assert [entry["detail"] for entry in entries] == [
        "Audit test announcement", "Audit test kick", "Audit test ban"
    ]
    for entry in entries:
        assert entry["timestamp"].endswith("Z")
        datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
