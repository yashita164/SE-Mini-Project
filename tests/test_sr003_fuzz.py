"""CHAT-SR-003 / TC-Sec-03: malformed payloads must not crash the server."""

import json

import pytest

from chat_harness import Conn, chat_port, register_and_login  # noqa: F401
import server

DEEP = b"[" * 8_000 + b"]" * 8_000  # fits in one request but exceeds recursion limit

# (label, raw bytes) -- each must yield a JSON error and keep the connection usable.
FRAMED_PAYLOADS = [
    ("not json", b"this is not json\n"),
    ("json array", b"[1,2,3]\n"),
    ("json string", b'"hello"\n'),
    ("json null", b"null\n"),
    ("json number", b"42\n"),
    ("empty object", b"{}\n"),
    ("invalid utf-8", b"\xff\xfe\xfd\n"),
    ("truncated object", b'{"type":"SEND_MESSAGE",\n'),
    ("type is null", b'{"type":null}\n'),
    ("type is list", b'{"type":["LOGIN_REQUEST"]}\n'),
    ("type is object", b'{"type":{"a":1}}\n'),
    ("unknown type", b'{"type":"DROP TABLE users"}\n'),
    ("deeply nested", DEEP + b"\n"),
    ("register wrong types", b'{"type":"REGISTER_REQUEST","username":1,"password":[]}\n'),
    ("register missing fields", b'{"type":"REGISTER_REQUEST"}\n'),
    ("register sql injection", b'{"type":"REGISTER_REQUEST","username":"x\'; DROP TABLE users;--","password":"password123"}\n'),
    ("register NUL in password", b'{"type":"REGISTER_REQUEST","username":"nulluser","password":"abc\\u0000defgh"}\n'),
    ("login wrong types", b'{"type":"LOGIN_REQUEST","username":{},"password":5}\n'),
]


def is_error(message):
    return message is not None and (
        message.get("status") == "ERROR" or message.get("type", "").endswith("ERROR")
        or message.get("type") == "ERROR"
    )


@pytest.mark.parametrize("label,payload", FRAMED_PAYLOADS, ids=[p[0] for p in FRAMED_PAYLOADS])
def test_malformed_payload_gets_error_and_server_survives(chat_port, label, payload):
    conn = Conn(chat_port)
    try:
        conn.send_raw(payload)
        reply = conn.recv()
        assert is_error(reply), f"{label}: expected an error reply, got {reply!r}"

        # Same connection is still usable afterwards, except when the server
        # intentionally closes it (a rejected login ends the connection, F-002).
        if not label.startswith("login"):
            conn.send({"type": "REGISTER_REQUEST", "username": "afterfuzz", "password": "password123"})
            assert conn.recv_type("REGISTER_RESPONSE")["status"] == "OK"
    finally:
        conn.close()

    # And a brand-new connection can still authenticate.
    other, _token = register_and_login(chat_port, "survivor")
    other.close()


def test_oversized_request_is_rejected_with_413(chat_port):
    conn = Conn(chat_port)
    try:
        conn.send_raw(b"x" * (server.MAX_REQUEST_BYTES + 100) + b"\n")
        reply = conn.recv()
        assert reply["code"] == 413
    finally:
        conn.close()
    other, _ = register_and_login(chat_port, "survivor")
    other.close()


@pytest.mark.parametrize("bad_id", [[1], {"a": 1}, 7, None, True])
def test_file_chunk_with_non_string_transfer_id(chat_port, bad_id):
    conn, token = register_and_login(chat_port, "uploader")
    try:
        conn.send({"type": "FILE_CHUNK", "token": token, "transferId": bad_id,
                   "data": "", "final": True})
        assert is_error(conn.recv())
        conn.send({"type": "HISTORY_REQUEST", "token": token})
        assert conn.recv_type("HISTORY_RESPONSE") is not None
    finally:
        conn.close()


@pytest.mark.parametrize("fields", [
    {},                                              # missing everything
    {"toUser": "bob"},                               # missing content
    {"content": "hi"},                               # missing recipient
    {"toUser": ["bob"], "content": "hi"},            # wrong recipient type
    {"toUser": "bob", "content": {"x": 1}},          # wrong content type
    {"toUser": "bob", "content": 123},
    {"toUser": "bob", "content": "   "},             # blank
    {"toUser": "bob", "content": "hi\x00there"},     # NUL control character
    {"toUser": "bob", "content": "bell\x07"},        # other control character
    {"toUser": "bob", "content": "x" * (server.MAX_MESSAGE_LENGTH + 1)},  # oversized
    {"toUser": "nobody' OR '1'='1", "content": "hi"},  # injection-style recipient
])
def test_send_message_validation(chat_port, fields):
    bob, _ = register_and_login(chat_port, "bob")
    alice, token = register_and_login(chat_port, "alice")
    try:
        alice.send({"type": "SEND_MESSAGE", "token": token, **fields})
        reply = alice.recv_type("MESSAGE_ERROR")
        assert reply is not None and reply["code"] in (400, 404, 413)
        # Nothing was delivered to bob.
        bob.sock.settimeout(0.3)
        assert bob.recv() is None
    finally:
        alice.close()
        bob.close()


def test_valid_message_with_newline_and_tab_is_accepted(chat_port):
    bob, _ = register_and_login(chat_port, "bob")
    alice, token = register_and_login(chat_port, "alice")
    try:
        alice.send({"type": "SEND_MESSAGE", "token": token, "toUser": "bob",
                    "content": "line1\n\tline2 é中"})
        assert alice.recv_type("MESSAGE_DELIVERED") is not None
    finally:
        alice.close()
        bob.close()


def test_missing_or_bad_token_is_refused(chat_port):
    conn = Conn(chat_port)
    try:
        for token in (None, "", 123, ["x"], "forged-token"):
            conn.send({"type": "SEND_MESSAGE", "token": token, "toUser": "bob", "content": "hi"})
            assert conn.recv_type("MESSAGE_ERROR")["code"] == 401
    finally:
        conn.close()
