"""TCP server integration tests for the Team 5 chat application."""

import json

import socket

import threading
import time
from datetime import datetime

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

    sock.settimeout(timeout)

    line = stream.readline()

    if not line:

        raise AssertionError(

            "Server closed the connection unexpectedly."

        )

    return json.loads(line.decode("utf-8"))

def expect_no_message(sock, stream, timeout=0.3):

    """Assert that no message arrives within the specified interval."""

    sock.settimeout(timeout)

    try:

        data = stream.readline()

    except socket.timeout:

        return

    if data:

        raise AssertionError(

            f"Unexpected message received: {data!r}"

        )

@pytest.fixture

def running_server(tmp_path, monkeypatch):

    """Start an isolated TCP server with a temporary SQLite database."""

    monkeypatch.setattr(

        database, "DB_PATH", tmp_path / "server_test.db"

    )

    database.init_db()

    with server.ACTIVE_CLIENTS_LOCK:

        server.ACTIVE_CLIENTS.clear()

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

        return receive_json(self.sock, self.stream, timeout)

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

def test_unauthenticated_message_is_rejected(running_server):

    """Sending a message without authentication is rejected."""

    with ChatTestClient(running_server) as client:

        registration = client.register("unauthenticated_sender")

        assert registration["status"] == "OK"

        client.send({

            "type": "SEND_MESSAGE",

            "token": "invalid-token",

            "toUser": "someone",

            "content": "This should be rejected",

        })

        response = client.receive()

        assert response["type"] == "MESSAGE_ERROR"

        assert response["code"] == 401

def test_history_requires_authentication(running_server):

    """History requests require a valid session."""

    with ChatTestClient(running_server) as client:

        client.send({

            "type": "HISTORY_REQUEST",

            "token": "invalid-token",

        })

        response = client.receive()

        assert response["type"] == "ERROR"

        assert response["code"] == 401

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
        assert alice.receive()["type"] == "TYPING_RESPONSE"

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


def test_file_transfer_preserves_bytes_and_checksum(running_server):
    """TC-File-01: recipient receives the exact file bytes and SHA-256."""
    import base64
    import hashlib
    import uuid

    original = bytes(range(256)) * 40  # Binary data containing arbitrary byte values.
    checksum = hashlib.sha256(original).hexdigest()
    transfer_id = str(uuid.uuid4())

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


def test_file_transfer_rejects_file_over_configured_limit(running_server):
    """Oversized file metadata is rejected before any file data is sent."""
    import uuid

    with ChatTestClient(running_server) as alice:
        register_and_login(alice, "oversize_sender")
        alice.send({
            "type": "FILE_START",
            "token": alice.token,
            "toUser": "not_needed_for_oversize_validation",
            "filename": "too-large.bin",
            "size": server.MAX_FILE_SIZE + 1,
            "sha256": "a" * 64,
            "transferId": str(uuid.uuid4()),
        })
        response = alice.receive()
        assert response["type"] == "FILE_ERROR"
        assert response["code"] == 413

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

