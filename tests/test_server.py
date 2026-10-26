
"""TCP server integration tests for the Team 5 chat application."""

import json
import socket
import threading
import time

import pytest

import database
import server


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
        return receive_json(
            self.sock, self.stream, timeout
        )

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


def test_message_is_saved_in_history(running_server):
    """Messages appear in the sender's and recipient's history."""
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "history_alice")
        register_and_login(bob, "history_bob")

        alice.send_message(
            "history_bob", "Persist this message"
        )

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
        registration = client.register(
            "unauthenticated_sender"
        )
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
        register_and_login(
            alice, "unknownrecipient_alice"
        )

        alice.send_message("no_such_user", "Hello?")

        response = alice.receive()
        assert response["type"] == "MESSAGE_ERROR"
        assert response["code"] == 404


def test_typing_indicator_is_sent_to_recipient_and_clears(
    running_server,
):
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

        response = alice.receive()
        assert response["type"] == "TYPING_RESPONSE"
        assert response["status"] == "OK"

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

        response = alice.receive()
        assert response["type"] == "TYPING_RESPONSE"
        assert response["status"] == "OK"

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
    """TC-Msg-03: messages delivered live are not replayed on next login."""
    with (
        ChatTestClient(running_server) as alice,
        ChatTestClient(running_server) as bob,
    ):
        register_and_login(alice, "live_alice")
        register_and_login(bob, "live_bob")

        alice.send_message("live_bob", "delivered live")
        assert bob.receive()["content"] == "delivered live"
        assert alice.receive()["type"] == "MESSAGE_DELIVERED"

    assert database.get_pending_messages("live_bob") == []

    with ChatTestClient(running_server) as bob_again:
        assert bob_again.login("live_bob")["status"] == "OK"
        expect_no_message(bob_again.sock, bob_again.stream)


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

