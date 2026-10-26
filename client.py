"""Console client for the Team 5 TCP chat application."""

import json
import queue
import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 5000
MAX_RESPONSE_BYTES = 65_536


def send_json(sock, lock, payload):
    """Send one newline-delimited JSON request."""
    data = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n"
    ).encode("utf-8")

    with lock:
        sock.sendall(data)


def receive_messages(sock, responses, stop_event):
    """Read socket responses in one thread and queue them for the command loop."""
    try:
        with sock.makefile("rb") as stream:
            while not stop_event.is_set():
                line = stream.readline(MAX_RESPONSE_BYTES + 1)

                if not line:
                    break

                if (
                    len(line) > MAX_RESPONSE_BYTES
                    or not line.endswith(b"\n")
                ):
                    responses.put({
                        "type": "ERROR",
                        "message": "Invalid or oversized server response.",
                    })
                    break

                try:
                    message = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    responses.put({
                        "type": "ERROR",
                        "message": "Invalid server response.",
                    })
                    continue

                if not isinstance(message, dict):
                    responses.put({
                        "type": "ERROR",
                        "message": "Unexpected server response format.",
                    })
                    continue

                if message.get("type") == "NEW_MESSAGE":
                    offline_note = (
                        " (received while you were offline)"
                        if message.get("queued")
                        else ""
                    )
                    print(
                        f"\n[Private message from "
                        f"{message.get('fromUser', 'unknown')}"
                        f"{offline_note}] "
                        f"{message.get('content', '')}\n> ",
                        end="",
                        flush=True,
                    )
                else:
                    responses.put(message)

    except (OSError, ConnectionError, ValueError):
        pass
    finally:
        stop_event.set()


def wait_for_response(
    responses,
    expected_type,
    stop_event,
    timeout=10,
):
    """Wait for a particular response while preserving unrelated responses."""
    deferred = []
    deadline = time.monotonic() + timeout

    try:
        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                print(
                    f"No {expected_type} response received "
                    f"within {timeout} seconds."
                )
                return None

            try:
                message = responses.get(timeout=remaining)
            except queue.Empty:
                print(
                    f"No {expected_type} response received "
                    f"within {timeout} seconds."
                )
                return None

            if message.get("type") == expected_type:
                return message

            deferred.append(message)

            if stop_event.is_set() and responses.empty():
                print("Connection closed before the expected response arrived.")
                return None

    finally:
        for message in deferred:
            responses.put(message)


def wait_for_message_result(
    responses,
    stop_event,
    timeout=10,
):
    """Wait for a message delivery result without losing unrelated responses."""
    expected_types = {
        "MESSAGE_DELIVERED",
        "MESSAGE_STORED",
        "MESSAGE_ERROR",
    }
    deferred = []
    deadline = time.monotonic() + timeout

    try:
        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                print(
                    f"No message confirmation received within "
                    f"{timeout} seconds."
                )
                return None

            try:
                message = responses.get(timeout=remaining)
            except queue.Empty:
                print(
                    f"No message confirmation received within "
                    f"{timeout} seconds."
                )
                return None

            if message.get("type") in expected_types:
                return message

            deferred.append(message)

            if stop_event.is_set() and responses.empty():
                print("Connection closed before message confirmation arrived.")
                return None

    finally:
        for message in deferred:
            responses.put(message)


def display_response(message):
    """Display a server response without exposing the session token."""
    if message is None:
        return

    safe_message = dict(message)
    safe_message.pop("token", None)

    print(
        "[Server] "
        + json.dumps(safe_message, ensure_ascii=False)
    )


def main():
    """Run the interactive console client."""
    responses = queue.Queue()
    stop_event = threading.Event()
    send_lock = threading.Lock()
    token = None
    sock = None

    try:
        sock = socket.create_connection(
            (HOST, PORT),
            timeout=5,
        )
        sock.settimeout(None)

    except OSError as error:
        print(f"Could not connect to {HOST}:{PORT}: {error}")
        print("Start server.py first.")
        return

    receiver = threading.Thread(
        target=receive_messages,
        args=(sock, responses, stop_event),
        daemon=True,
    )
    receiver.start()

    print("\n=== Team 5 TCP Chat ===")
    print("Commands: register, login, msg, history, logout, quit")

    try:
        while not stop_event.is_set():
            try:
                command = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if command == "register":
                username = input("Username: ").strip()
                password = input("Password (8-72 UTF-8 bytes): ")

                send_json(sock, send_lock, {
                    "type": "REGISTER_REQUEST",
                    "username": username,
                    "password": password,
                })

                response = wait_for_response(
                    responses,
                    "REGISTER_RESPONSE",
                    stop_event,
                )
                display_response(response)

            elif command == "login":
                if token:
                    print("Already logged in. Use logout first.")
                    continue

                username = input("Username: ").strip()
                password = input("Password: ")

                send_json(sock, send_lock, {
                    "type": "LOGIN_REQUEST",
                    "username": username,
                    "password": password,
                })

                response = wait_for_response(
                    responses,
                    "LOGIN_RESPONSE",
                    stop_event,
                )
                display_response(response)

                if response and response.get("status") == "OK":
                    token = response.get("token")
                    print("Login successful. Session token received securely.")

            elif command == "msg":
                if not token:
                    print("Log in first.")
                    continue

                recipient = input("Recipient username: ").strip()
                content = input("Message: ")

                send_json(sock, send_lock, {
                    "type": "SEND_MESSAGE",
                    "token": token,
                    "toUser": recipient,
                    "content": content,
                })

                response = wait_for_message_result(
                    responses,
                    stop_event,
                    timeout=10,
                )
                display_response(response)

            elif command == "history":
                if not token:
                    print("Log in first.")
                    continue

                send_json(sock, send_lock, {
                    "type": "HISTORY_REQUEST",
                    "token": token,
                })

                response = wait_for_response(
                    responses,
                    "HISTORY_RESPONSE",
                    stop_event,
                )
                display_response(response)

                if response:
                    for item in response.get("messages", []):
                        print(
                            f"{item.get('sender', '?')} -> "
                            f"{item.get('recipient', '?')}: "
                            f"{item.get('content', '')} "
                            f"({item.get('created_at', '')})"
                        )

            elif command == "logout":
                if not token:
                    print("You are not logged in.")
                    continue

                send_json(sock, send_lock, {
                    "type": "LOGOUT_REQUEST",
                    "token": token,
                })

                response = wait_for_response(
                    responses,
                    "LOGOUT_RESPONSE",
                    stop_event,
                )
                display_response(response)

                if response and response.get("status") == "OK":
                    token = None

            elif command == "quit":
                break

            elif command:
                print(
                    "Unknown command. Use register, login, msg, "
                    "history, logout, or quit."
                )

    except (OSError, ConnectionError) as error:
        print(f"Communication error: {error}")

    finally:
        stop_event.set()

        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

            sock.close()

        receiver.join(timeout=1)
        print("Disconnected.")


if __name__ == "__main__":
    main()
