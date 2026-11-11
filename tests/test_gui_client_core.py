"""Tests for the GUI's shared, asynchronous protocol client."""

from __future__ import annotations

import hashlib
import base64
import json
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import auth
import database
from gui import client_core
from gui.app import ChatApplication
import server


def test_discover_view_loads_integrated_room_chat():
    from gui.room_chat import RoomChatView

    assert ChatApplication._discover_view(
        "gui.room_chat", "RoomChatView"
    ) is RoomChatView


class ProtocolPeer:
    """Small socket-pair peer that responds using the production protocol."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.requests: queue.Queue[dict[str, Any]] = queue.Queue()
        self.file_chunks: list[bytes] = []
        self._send_lock = threading.Lock()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _send(self, payload: dict[str, Any]) -> None:
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        with self._send_lock:
            self.sock.sendall(data)

    def send_event(self, payload: dict[str, Any]) -> None:
        self._send(payload)

    def _serve(self) -> None:
        try:
            with self.sock.makefile("rb") as stream:
                for line in stream:
                    request = json.loads(line.decode("utf-8"))
                    self.requests.put(request)
                    kind = request.get("type")
                    if kind == "REGISTER_REQUEST":
                        self._send({"type": "REGISTER_RESPONSE", "status": "OK"})
                    elif kind == "LOGIN_REQUEST":
                        self._send({
                            "type": "LOGIN_RESPONSE",
                            "status": "OK",
                            "userId": request["username"],
                            "token": "test-session-token",
                        })
                    elif kind == "SEND_MESSAGE":
                        self._send({
                            "type": "MESSAGE_DELIVERED",
                            "messageId": "1",
                        })
                    elif kind in {"CREATE_ROOM", "JOIN_ROOM", "LEAVE_ROOM"}:
                        self._send({
                            "type": "ROOM_RESPONSE",
                            "status": "OK",
                            "action": kind.removesuffix("_ROOM"),
                            "room": request.get("room"),
                        })
                    elif kind == "LIST_ROOMS":
                        self._send({
                            "type": "ROOM_LIST",
                            "rooms": [{"name": "General", "memberCount": 2}],
                        })
                    elif kind == "LIST_USERS":
                        self._send({
                            "type": "USER_LIST",
                            "room": request.get("room"),
                            "users": ["alice", "bob"],
                        })
                    elif kind == "HISTORY_REQUEST":
                        self._send({
                            "type": "HISTORY_RESPONSE",
                            "messages": [],
                            "nextBeforeId": None,
                        })
                    elif kind == "FILE_START":
                        self.file_chunks.clear()
                        self._send({
                            "type": "FILE_READY",
                            "transferId": request["transferId"],
                        })
                    elif kind == "FILE_CHUNK":
                        self.file_chunks.append(
                            base64.b64decode(request["data"], validate=True)
                        )
                        self._send({
                            "type": "FILE_SENT" if request["final"] else "FILE_CHUNK_ACK",
                            "transferId": request["transferId"],
                        })
                    elif kind == "LOGOUT_REQUEST":
                        self._send({"type": "LOGOUT_RESPONSE", "status": "OK"})
                        return
        except (OSError, ValueError, json.JSONDecodeError):
            return

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self._thread.join(timeout=1)


def next_event(
    events: queue.Queue[dict[str, Any]],
    predicate,
    timeout: float = 3.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = events.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            break
        if predicate(event):
            return event
    raise AssertionError("Expected client event did not arrive before timeout.")


@pytest.fixture
def connected_core(monkeypatch):
    client_socket, server_socket = socket.socketpair()
    peer = ProtocolPeer(server_socket)
    monkeypatch.setattr(
        client_core.socket,
        "create_connection",
        lambda address, timeout: client_socket,
    )
    core = client_core.ClientCore(connect_timeout=1)
    assert core.connect()
    next_event(
        core.events,
        lambda event: event.get("_event") == "connection"
        and event.get("status") == "connected",
    )
    try:
        yield core, peer
    finally:
        core.close()
        peer.close()


@pytest.fixture
def live_chat_server(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "gui_client_test.db")
    real_gensalt = auth.bcrypt.gensalt
    monkeypatch.setattr(
        auth.bcrypt, "gensalt", lambda: real_gensalt(rounds=4)
    )
    database.init_db()
    with server.ACTIVE_CLIENTS_LOCK:
        server.ACTIVE_CLIENTS.clear()
    with server.ROOMS_LOCK:
        server.ROOMS.clear()
    with server.TYPING_LOCK:
        server.TYPING_STATES.clear()
    with server.FILE_TRANSFER_LOCK:
        server.ACTIVE_FILE_TRANSFERS.clear()

    chat_server = server.ChatServer(("127.0.0.1", 0), server.ChatHandler)
    thread = threading.Thread(target=chat_server.serve_forever, daemon=True)
    thread.start()
    try:
        yield chat_server.server_address
    finally:
        chat_server.shutdown()
        chat_server.server_close()
        thread.join(timeout=3)
        with server.ROOMS_LOCK:
            server.ROOMS.clear()
        with server.TYPING_LOCK:
            server.TYPING_STATES.clear()
        with server.FILE_TRANSFER_LOCK:
            server.ACTIVE_FILE_TRANSFERS.clear()


def _register_and_login(core: client_core.ClientCore) -> None:
    core.register("gui_user", "SecurePass123")
    assert next_event(
        core.events, lambda event: event.get("type") == "REGISTER_RESPONSE"
    )["status"] == "OK"
    core.login("gui_user", "SecurePass123")
    assert next_event(
        core.events, lambda event: event.get("type") == "LOGIN_RESPONSE"
    )["status"] == "OK"
    assert core.is_authenticated
    assert core.username == "gui_user"


def test_core_auth_messaging_rooms_and_history_use_server_protocol(
    connected_core,
):
    core, peer = connected_core
    _register_and_login(core)

    core.send_private_message("bob", "private text")
    assert next_event(
        core.events, lambda event: event.get("type") == "MESSAGE_DELIVERED"
    )
    core.create_room("General")
    assert next_event(
        core.events, lambda event: event.get("type") == "ROOM_RESPONSE"
    )
    core.join_room("General")
    assert next_event(
        core.events, lambda event: event.get("type") == "ROOM_RESPONSE"
    )
    core.send_room_message("General", "room text")
    assert next_event(
        core.events, lambda event: event.get("type") == "MESSAGE_DELIVERED"
    )
    core.list_rooms()
    assert next_event(core.events, lambda event: event.get("type") == "ROOM_LIST")
    core.list_users()
    assert next_event(core.events, lambda event: event.get("type") == "USER_LIST")
    core.request_history(limit=20, before_id=12)
    assert next_event(
        core.events, lambda event: event.get("type") == "HISTORY_RESPONSE"
    )

    received = [peer.requests.get(timeout=1) for _ in range(8)]
    assert [request["type"] for request in received] == [
        "REGISTER_REQUEST",
        "LOGIN_REQUEST",
        "SEND_MESSAGE",
        "CREATE_ROOM",
        "JOIN_ROOM",
        "SEND_MESSAGE",
        "LIST_ROOMS",
        "LIST_USERS",
    ]
    assert received[2]["token"] == "test-session-token"
    assert received[2]["toUser"] == "bob"
    assert received[5]["roomId"] == "General"

    history = peer.requests.get(timeout=1)
    assert history["type"] == "HISTORY_REQUEST"
    assert history["limit"] == 20
    assert history["beforeId"] == 12
    assert history["token"] == "test-session-token"


def test_core_file_transfer_uses_existing_chunk_protocol(
    connected_core, tmp_path: Path
):
    core, peer = connected_core
    _register_and_login(core)
    original = bytes(range(256)) * 30
    filepath = tmp_path / "payload.bin"
    filepath.write_bytes(original)

    transfer_id = core.send_file("#General", filepath)
    start = next_event(
        core.events, lambda event: event.get("type") == "FILE_READY"
    )
    assert start["transferId"] == transfer_id
    result = next_event(
        core.events,
        lambda event: event.get("_event") == "file_transfer"
        and event.get("transferId") == transfer_id,
    )
    assert result["status"] == "sent"
    assert b"".join(peer.file_chunks) == original
    start_request = next_event(
        peer.requests,
        lambda request: request.get("type") == "FILE_START",
    )
    assert start_request["sha256"] == hashlib.sha256(original).hexdigest()
    assert start_request["roomId"] == "General"


def test_disconnect_stops_and_joins_file_transfer_worker(
    connected_core, monkeypatch, tmp_path
):
    core, _peer = connected_core
    _register_and_login(core)
    filepath = tmp_path / "pending.txt"
    filepath.write_text("pending transfer", encoding="utf-8")
    waiting_for_response = threading.Event()

    def wait_for_disconnect(responses, expected, transfer_id, stop_event):
        waiting_for_response.set()
        stop_event.wait(3)
        raise ConnectionError("Connection closed during file transfer.")

    monkeypatch.setattr(core, "_wait_file_response", wait_for_disconnect)
    core.send_file("bob", filepath)
    assert waiting_for_response.wait(1)
    with core._file_workers_lock:
        worker = next(iter(core._file_workers))

    core.disconnect()

    assert not worker.is_alive()
    with core._file_workers_lock:
        assert not core._file_workers


def test_core_reports_unexpected_disconnect(connected_core):
    core, peer = connected_core
    peer.close()
    next_event(
        core.events,
        lambda event: event.get("_event") == "connection"
        and event.get("status") == "disconnected",
    )
    assert core.connection_state == "disconnected"
    assert not core.is_authenticated


def test_core_receives_and_verifies_incoming_file(connected_core, monkeypatch, tmp_path):
    core, peer = connected_core
    monkeypatch.setattr(client_core, "DOWNLOAD_DIR", tmp_path / "received")
    data = b"received through the file protocol"
    transfer_id = "incoming-file-1"
    peer.send_event({
        "type": "FILE_RECEIVE_START",
        "transferId": transfer_id,
        "fromUser": "bob",
        "filename": "shared.txt",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })
    peer.send_event({
        "type": "FILE_RECEIVE_CHUNK",
        "transferId": transfer_id,
        "data": base64.b64encode(data).decode("ascii"),
    })
    peer.send_event({
        "type": "FILE_RECEIVE_END",
        "transferId": transfer_id,
    })

    received = next_event(
        core.events,
        lambda event: event.get("_event") == "file_transfer"
        and event.get("status") == "received",
    )
    saved_path = Path(received["path"])
    assert saved_path.read_bytes() == data
    assert received["fromUser"] == "bob"


def test_tk_event_poll_dispatches_on_calling_thread_and_reschedules():
    class FakeRoot:
        def __init__(self):
            self.after_calls = []

        def after(self, delay, callback):
            self.after_calls.append((delay, callback))

    class FakeView:
        def __init__(self):
            self.events = []

        def handle_event(self, event):
            self.events.append((event, threading.current_thread()))

    app = ChatApplication.__new__(ChatApplication)
    app.root = FakeRoot()
    app.client = type("FakeClient", (), {"events": queue.Queue()})()
    app._closing = False
    app._current_view = FakeView()
    app.client.events.put({"_event": "client_error", "message": "offline"})

    app._poll_events()

    assert app._current_view.events[0][0]["message"] == "offline"
    assert app._current_view.events[0][1] is threading.current_thread()
    assert app.root.after_calls[0][0] == 50


def test_core_interoperates_with_existing_server_for_chat_rooms_history_and_files(
    live_chat_server, monkeypatch, tmp_path
):
    host, port = live_chat_server
    monkeypatch.setattr(client_core, "DOWNLOAD_DIR", tmp_path / "received")
    alice = client_core.ClientCore(host, port)
    bob = client_core.ClientCore(host, port)
    try:
        alice.connect()
        bob.connect()
        next_event(
            alice.events,
            lambda event: event.get("_event") == "connection"
            and event.get("status") == "connected",
        )
        next_event(
            bob.events,
            lambda event: event.get("_event") == "connection"
            and event.get("status") == "connected",
        )
        alice.register("gui_alice", "SecurePass123")
        bob.register("gui_bob", "SecurePass123")
        next_event(
            alice.events, lambda event: event.get("type") == "REGISTER_RESPONSE"
        )
        next_event(
            bob.events, lambda event: event.get("type") == "REGISTER_RESPONSE"
        )
        alice.login("gui_alice", "SecurePass123")
        bob.login("gui_bob", "SecurePass123")
        next_event(
            alice.events, lambda event: event.get("type") == "LOGIN_RESPONSE"
        )
        next_event(
            bob.events, lambda event: event.get("type") == "LOGIN_RESPONSE"
        )

        alice.send_private_message("gui_bob", "private from GUI core")
        delivered = next_event(
            alice.events, lambda event: event.get("type") == "MESSAGE_DELIVERED"
        )
        incoming = next_event(
            bob.events,
            lambda event: event.get("type") == "NEW_MESSAGE"
            and event.get("content") == "private from GUI core",
        )
        assert delivered["messageId"] == incoming["messageId"]

        alice.create_room("General")
        next_event(alice.events, lambda event: event.get("type") == "ROOM_RESPONSE")
        bob.join_room("General")
        next_event(bob.events, lambda event: event.get("type") == "ROOM_RESPONSE")
        alice.send_room_message("General", "room from GUI core")
        next_event(
            alice.events,
            lambda event: event.get("type") == "MESSAGE_DELIVERED",
        )
        next_event(
            bob.events,
            lambda event: event.get("type") == "NEW_MESSAGE"
            and event.get("content") == "room from GUI core",
        )

        alice.request_history(limit=20)
        history = next_event(
            alice.events, lambda event: event.get("type") == "HISTORY_RESPONSE"
        )
        assert any(
            message["content"] == "private from GUI core"
            for message in history["messages"]
        )

        original = b"existing backend file transfer"
        filepath = tmp_path / "upload.txt"
        filepath.write_bytes(original)
        transfer_id = alice.send_file("gui_bob", filepath)
        sent = next_event(
            alice.events,
            lambda event: event.get("_event") == "file_transfer"
            and event.get("transferId") == transfer_id,
        )
        received = next_event(
            bob.events,
            lambda event: event.get("_event") == "file_transfer"
            and event.get("status") == "received",
        )
        assert sent["status"] == "sent"
        assert Path(received["path"]).read_bytes() == original
    finally:
        alice.close()
        bob.close()
