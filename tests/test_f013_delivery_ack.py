"""CHAT-F-013 / TC-Msg-04: delivery acknowledgement back to the sender."""

import time

from chat_harness import Conn, chat_port, register_and_login  # noqa: F401
import client
import database


def test_sender_gets_ack_when_recipient_online(chat_port):
    bob, _ = register_and_login(chat_port, "bob")
    alice, token = register_and_login(chat_port, "alice")
    try:
        alice.send({"type": "SEND_MESSAGE", "token": token, "toUser": "bob", "content": "hello"})
        ack = alice.recv_type("MESSAGE_DELIVERED")
        incoming = bob.recv_type("NEW_MESSAGE")
        assert ack is not None and ack["messageId"] == incoming["messageId"]
        assert ack["deliveredAt"]
        assert incoming["content"] == "hello" and incoming["fromUser"] == "alice"
    finally:
        alice.close()
        bob.close()


def test_offline_message_is_stored_not_reported_delivered(chat_port):
    alice, token = register_and_login(chat_port, "alice")
    bob_setup, _ = register_and_login(chat_port, "bob")
    bob_setup.close()  # bob exists but is now offline
    time.sleep(0.3)  # let the server process the disconnect
    try:
        alice.send({"type": "SEND_MESSAGE", "token": token, "toUser": "bob", "content": "later"})
        reply = alice.recv()
        assert reply["type"] == "MESSAGE_STORED"
        assert reply["type"] != "MESSAGE_DELIVERED"
        pending = database.get_pending_messages("bob")
        assert [m["content"] for m in pending] == ["later"]
    finally:
        alice.close()

    # On bob's next login the queued message arrives and is then marked delivered.
    bob = Conn(chat_port)
    try:
        bob.send({"type": "LOGIN_REQUEST", "username": "bob", "password": "correct-horse"})
        assert bob.recv_type("LOGIN_RESPONSE")["status"] == "OK"
        queued = bob.recv_type("NEW_MESSAGE")
        assert queued["content"] == "later" and queued["queued"] is True
    finally:
        bob.close()
    # The server marks a message delivered just after writing it; allow for that.
    deadline = time.monotonic() + 3
    while database.get_pending_messages("bob") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert database.get_pending_messages("bob") == []


def test_client_shows_delivered_indication():
    text = client.describe_message_result({"type": "MESSAGE_DELIVERED", "messageId": "7",
                                           "deliveredAt": "2026-10-27T03:00:00+00:00"})
    assert "delivered" in text.lower() and "7" in text


def test_client_does_not_show_delivered_for_stored_or_error():
    stored = client.describe_message_result({"type": "MESSAGE_STORED", "messageId": "8"})
    assert "delivered" not in stored.lower().replace("not delivered", "")
    assert "offline" in stored.lower()
    error = client.describe_message_result({"type": "MESSAGE_ERROR", "code": 404,
                                            "message": "Recipient not found."})
    assert "delivered" not in error.lower() and "Recipient not found." in error
    assert "no" in client.describe_message_result(None).lower()
