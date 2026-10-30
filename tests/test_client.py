"""Client responsiveness tests for the Team 5 chat application."""

import json
import queue
import socket
import threading
import time

import client


def test_tc_ux_01_user_can_send_while_receiver_waits_on_slow_network():
    """A partial incoming response cannot block user-side socket writes."""
    client_socket, server_socket = socket.socketpair()
    responses = queue.Queue()
    stop_event = threading.Event()
    send_lock = threading.Lock()
    server_socket.settimeout(0.5)
    server_stream = server_socket.makefile("rb")

    receiver = threading.Thread(
        target=client.receive_messages,
        args=(client_socket, responses, stop_event),
        daemon=True,
    )
    receiver.start()

    try:
        # Simulate a slow network: the server begins an event but does not
        # finish the JSON line, leaving the receiver blocked in readline().
        server_socket.sendall(b'{"type":"SERVER_NOTICE","message":"slow')
        time.sleep(0.05)
        assert receiver.is_alive()
        assert responses.empty()

        # The interactive thread can still send while the listener waits for
        # the rest of the incoming event.
        request = {"type": "TYPING", "toUser": "bob", "isTyping": True}
        client.send_json(client_socket, send_lock, request)
        server_request = json.loads(server_stream.readline().decode("utf-8"))
        assert server_request == request

        server_socket.sendall(b" network" + b'"}\n')
        received = responses.get(timeout=0.5)
        assert received == {
            "type": "SERVER_NOTICE",
            "message": "slow network",
        }
    finally:
        stop_event.set()
        client_socket.close()
        server_stream.close()
        server_socket.close()
        receiver.join(timeout=1)


def test_client_rejects_oversized_file_before_sending(tmp_path, monkeypatch, capsys):
    filepath = tmp_path / "oversized.bin"
    filepath.write_bytes(b"12345")
    monkeypatch.setattr(client, "MAX_FILE_SIZE", 4)
    sent_requests = []

    monkeypatch.setattr(
        client, "send_json", lambda *args: sent_requests.append(args[-1])
    )
    client.send_file(
        None, None, queue.Queue(), threading.Event(),
        "token", "recipient", filepath,
    )

    assert sent_requests == []
    assert "exceeds the configured limit" in capsys.readouterr().out


def test_client_sends_file_to_room_in_bounded_chunks(tmp_path, monkeypatch):
    filepath = tmp_path / "room.bin"
    original = b"room-file-payload"
    filepath.write_bytes(original)
    monkeypatch.setattr(client, "FILE_CHUNK_SIZE", 5)
    responses = queue.Queue()
    requests = []

    def fake_send_json(sock, lock, payload):
        requests.append(payload)
        if payload["type"] == "FILE_START":
            responses.put({"type": "FILE_READY", "transferId": payload["transferId"]})
        elif payload["type"] == "FILE_CHUNK":
            expected = "FILE_SENT" if payload["final"] else "FILE_CHUNK_ACK"
            responses.put({"type": expected, "transferId": payload["transferId"]})

    monkeypatch.setattr(client, "send_json", fake_send_json)
    client.send_file(
        None, None, responses, threading.Event(),
        "token", "#General", filepath,
    )

    start = requests[0]
    chunks = requests[1:]
    assert start["roomId"] == "General"
    assert "toUser" not in start
    assert len(chunks) == 4
    assert b"".join(
        client.base64.b64decode(chunk["data"]) for chunk in chunks
    ) == original
    assert client.hashlib.sha256(original).hexdigest() == start["sha256"]


def test_client_receives_history_page_with_large_messages():
    client_socket, server_socket = socket.socketpair()
    responses = queue.Queue()
    stop_event = threading.Event()
    reader = threading.Thread(
        target=client.receive_messages,
        args=(client_socket, responses, stop_event),
    )
    large_content = "\U0001f600" * 4_000
    expected = {
        "type": "HISTORY_RESPONSE",
        "messages": [
            {"id": index, "content": large_content}
            for index in range(200)
        ],
        "nextBeforeId": 1,
    }

    try:
        reader.start()
        server_socket.sendall(
            (json.dumps(expected, ensure_ascii=False) + "\n").encode("utf-8")
        )
        response = responses.get(timeout=3)
        assert response == expected
    finally:
        server_socket.close()
        reader.join(timeout=3)
        client_socket.close()
    assert not reader.is_alive()
