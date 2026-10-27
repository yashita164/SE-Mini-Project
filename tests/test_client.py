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

