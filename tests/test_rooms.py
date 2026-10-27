"""CHAT-F-020/021/022/023: chat rooms, room broadcast, online-user lists."""

import time

import pytest

from chat_harness import Conn, chat_port, register_and_login  # noqa: F401
import client
import database
import server


@pytest.fixture(autouse=True)
def clean_rooms():
    server.ROOMS.clear()
    yield
    server.ROOMS.clear()


def room_call(conn, token, kind, **fields):
    """Send a room request; return its reply (success type or ROOM_RESPONSE error)."""
    conn.send({"type": kind, "token": token, **fields})
    wanted = {"LIST_ROOMS": "ROOM_LIST", "LIST_USERS": "USER_LIST"}.get(kind, "ROOM_RESPONSE")
    for _ in range(10):
        message = conn.recv()
        if message is None or message["type"] in (wanted, "ROOM_RESPONSE"):
            return message
    return None


def test_create_room_appears_in_directory_immediately(chat_port):  # TC-Grp-01
    alice, token = register_and_login(chat_port, "alice")
    try:
        reply = room_call(alice, token, "CREATE_ROOM", room="General")
        assert reply["status"] == "OK" and reply["members"] == ["alice"]
        listing = room_call(alice, token, "LIST_ROOMS")
        assert listing["rooms"] == [{"name": "General", "memberCount": 1}]
    finally:
        alice.close()


@pytest.mark.parametrize("name", ["", "ab", "x" * 33, "bad name", "room!", "a/b", None, 5, ["room"]])
def test_create_room_rejects_invalid_names(chat_port, name):
    alice, token = register_and_login(chat_port, "alice")
    try:
        reply = room_call(alice, token, "CREATE_ROOM", room=name)
        assert reply["status"] == "ERROR" and reply["code"] == 400
    finally:
        alice.close()


def test_duplicate_room_name_rejected_case_insensitively(chat_port):
    alice, token = register_and_login(chat_port, "alice")
    try:
        assert room_call(alice, token, "CREATE_ROOM", room="General")["status"] == "OK"
        reply = room_call(alice, token, "CREATE_ROOM", room="GENERAL")
        assert reply["code"] == 409
    finally:
        alice.close()


def test_room_requests_need_a_valid_token(chat_port):
    conn = Conn(chat_port)
    try:
        for kind in ("CREATE_ROOM", "JOIN_ROOM", "LEAVE_ROOM", "LIST_ROOMS", "LIST_USERS"):
            conn.send({"type": kind, "token": "forged", "room": "General"})
            assert conn.recv_type("ROOM_RESPONSE")["code"] == 401
    finally:
        conn.close()


def test_join_and_leave_update_membership_for_everyone(chat_port):  # TC-Grp-02
    alice, a_tok = register_and_login(chat_port, "alice")
    bob, b_tok = register_and_login(chat_port, "bob")
    try:
        room_call(alice, a_tok, "CREATE_ROOM", room="General")

        joined = room_call(bob, b_tok, "JOIN_ROOM", room="general")
        assert joined["status"] == "OK" and joined["members"] == ["alice", "bob"]
        event = alice.recv_type("ROOM_EVENT")
        assert event["event"] == "JOINED" and event["user"] == "bob"
        assert event["members"] == ["alice", "bob"]

        left = room_call(bob, b_tok, "LEAVE_ROOM", room="General")
        assert left["status"] == "OK"
        event = alice.recv_type("ROOM_EVENT")
        assert event["event"] == "LEFT" and event["members"] == ["alice"]
    finally:
        alice.close()
        bob.close()


def test_join_leave_error_cases(chat_port):
    alice, token = register_and_login(chat_port, "alice")
    try:
        assert room_call(alice, token, "JOIN_ROOM", room="Nowhere")["code"] == 404
        assert room_call(alice, token, "LEAVE_ROOM", room="Nowhere")["code"] == 404
        room_call(alice, token, "CREATE_ROOM", room="General")
        assert room_call(alice, token, "JOIN_ROOM", room="General")["code"] == 409
        room_call(alice, token, "LEAVE_ROOM", room="General")
        assert room_call(alice, token, "LEAVE_ROOM", room="General")["code"] == 409
    finally:
        alice.close()


def test_room_message_reaches_all_online_members_only(chat_port):  # TC-Grp-03
    alice, a_tok = register_and_login(chat_port, "alice")
    bob, b_tok = register_and_login(chat_port, "bob")
    carol, c_tok = register_and_login(chat_port, "carol")
    dave, _ = register_and_login(chat_port, "dave")  # online but not a member
    try:
        room_call(alice, a_tok, "CREATE_ROOM", room="General")
        room_call(bob, b_tok, "JOIN_ROOM", room="General")
        room_call(carol, c_tok, "JOIN_ROOM", room="General")

        alice.send({"type": "SEND_MESSAGE", "token": a_tok, "roomId": "General",
                    "content": "hello room"})
        ack = alice.recv_type("MESSAGE_DELIVERED")
        assert ack["recipients"] == 2 and ack["room"] == "General"

        for member in (bob, carol):
            incoming = member.recv_type("NEW_MESSAGE")
            assert incoming["content"] == "hello room"
            assert incoming["fromUser"] == "alice" and incoming["roomId"] == "General"
            assert incoming["messageId"] == ack["messageId"]

        dave.sock.settimeout(0.3)
        assert dave.recv() is None            # non-member got nothing
        assert database.get_pending_messages("bob") == []  # not queued for replay
    finally:
        for c in (alice, bob, carol, dave):
            c.close()


def test_room_message_rules(chat_port):
    alice, a_tok = register_and_login(chat_port, "alice")
    bob, b_tok = register_and_login(chat_port, "bob")
    try:
        room_call(alice, a_tok, "CREATE_ROOM", room="General")

        def send(token_conn, token, room, content="hi"):
            token_conn.send({"type": "SEND_MESSAGE", "token": token,
                             "roomId": room, "content": content})
            return token_conn.recv()

        assert send(bob, b_tok, "General")["code"] == 403            # not a member
        assert send(alice, a_tok, "Nowhere")["code"] == 404
        assert send(alice, a_tok, 5)["code"] == 400                  # wrong type
        assert send(alice, a_tok, "General", "   ")["code"] == 400   # blank
        assert send(alice, a_tok, "General", "x" * 5000)["code"] == 413
        assert send(alice, a_tok, "General", "bad\x00")["code"] == 400
        # alone in the room -> stored, not "delivered"
        assert send(alice, a_tok, "General")["type"] == "MESSAGE_STORED"
    finally:
        alice.close()
        bob.close()


def test_disconnect_removes_user_from_rooms_and_notifies(chat_port):
    alice, a_tok = register_and_login(chat_port, "alice")
    bob, b_tok = register_and_login(chat_port, "bob")
    try:
        room_call(alice, a_tok, "CREATE_ROOM", room="General")
        room_call(bob, b_tok, "JOIN_ROOM", room="General")
        alice.recv_type("ROOM_EVENT")  # bob joined
        bob.close()
        event = alice.recv_type("ROOM_EVENT")
        assert event["event"] == "LEFT" and event["user"] == "bob"
        assert server.ROOMS["general"]["members"] == {"alice"}
    finally:
        alice.close()


def test_online_user_lists_global_and_per_room(chat_port):  # TC-Grp-04
    alice, a_tok = register_and_login(chat_port, "alice")
    bob, b_tok = register_and_login(chat_port, "bob")
    carol, _ = register_and_login(chat_port, "carol")
    try:
        room_call(alice, a_tok, "CREATE_ROOM", room="General")
        room_call(bob, b_tok, "JOIN_ROOM", room="General")

        assert room_call(alice, a_tok, "LIST_USERS")["users"] == ["alice", "bob", "carol"]
        in_room = room_call(alice, a_tok, "LIST_USERS", room="General")
        assert in_room["users"] == ["alice", "bob"] and in_room["room"] == "General"

        assert room_call(alice, a_tok, "LIST_USERS", room="Nowhere")["code"] == 404
        carol.close()
        time.sleep(0.3)
        assert room_call(alice, a_tok, "LIST_USERS")["users"] == ["alice", "bob"]  # refreshes
    finally:
        alice.close()
        bob.close()


def test_non_member_cannot_list_room_users(chat_port):
    alice, a_tok = register_and_login(chat_port, "alice")
    bob, b_tok = register_and_login(chat_port, "bob")
    try:
        room_call(alice, a_tok, "CREATE_ROOM", room="General")
        assert room_call(bob, b_tok, "LIST_USERS", room="General")["code"] == 403
    finally:
        alice.close()
        bob.close()


# ------------------------------------------------------------- client display
def test_client_formats_room_traffic():
    assert client.format_incoming({"type": "NEW_MESSAGE", "fromUser": "bob",
                                   "roomId": "General", "content": "yo"}) == "[Room General] bob: yo"
    assert "joined" in client.format_incoming({"type": "ROOM_EVENT", "event": "JOINED",
                                               "room": "General", "user": "bob"})
    assert "left" in client.format_incoming({"type": "ROOM_EVENT", "event": "LEFT",
                                             "room": "General", "user": "bob"})
    private = client.format_incoming({"type": "NEW_MESSAGE", "fromUser": "bob",
                                      "content": "psst", "queued": True})
    assert "Private message from bob" in private and "while you were offline" in private


def test_client_describes_room_responses():
    assert "Created room General" in client.describe_room_response(
        {"type": "ROOM_RESPONSE", "status": "OK", "action": "CREATE", "room": "General", "members": ["a"]})
    assert "General (2 members)" in client.describe_room_response(
        {"type": "ROOM_LIST", "rooms": [{"name": "General", "memberCount": 2}]})
    assert "alice, bob" in client.describe_room_response(
        {"type": "USER_LIST", "room": None, "users": ["alice", "bob"]})
    failed = client.describe_room_response(
        {"type": "ROOM_RESPONSE", "status": "ERROR", "code": 404, "message": "Room not found."})
    assert "Room not found." in failed and "404" in failed
    assert "No response" in client.describe_room_response(None)
