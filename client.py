
"""Console client for the Team 5 TCP chat application."""

import json
import queue
import socket
import threading

HOST = "127.0.0.1"
PORT = 5000
MAX_RESPONSE_BYTES = 65_536

responses = queue.Queue()
stop_event = threading.Event()


def send_json(sock, lock, payload):
    data = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    with lock:
        sock.sendall(data)


def receive_messages(sock):
    """Read the socket in one thread and pass responses to the command loop."""
    try:
        with sock.makefile("rb") as stream:
            while not stop_event.is_set():
                line = stream.readline(MAX_RESPONSE_BYTES + 1)

                if not line:
                    break

                if len(line) > MAX_RESPONSE_BYTES or not line.endswith(b"\n"):
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

                if message.get("type") == "NEW_MESSAGE":
                    print(
                        f"\n[Private message from {message.get('fromUser', 'unknown')}] "
                        f"{message.get('content', '')}\n> ",
                        end="",
                        flush=True,
                    )
                else:
                    responses.put(message)

    except (OSError, ConnectionError):
        pass
    finally:
        stop_event.set()


def wait_for_response(expected_type, timeout=10):
    """Wait for a particular response without consuming other response types."""
    deferred = []

    try:
        while True:
            message = responses.get(timeout=timeout)

            if message.get("type") == expected_type:
                return message

            deferred.append(message)

    except queue.Empty:
        print(f"No {expected_type} response received within {timeout} seconds.")
        return None

    finally:
        for message in deferred:
            responses.put(message)


def display_response(message):
    if message is None:
        return

    safe_message = dict(message)
    safe_message.pop("token", None)
    print("[Server] " + json.dumps(safe_message, ensure_ascii=False))


def main():
    send_lock = threading.Lock()
    token = None
    sock = None

    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
        sock.settimeout(None)
    except OSError as error:
        print(f"Could not connect to {HOST}:{PORT}: {error}")
        print("Start server.py first.")
        return

    threading.Thread(
        target=receive_messages,
        args=(sock,),
        daemon=True,
    ).start()

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
                display_response(wait_for_response("REGISTER_RESPONSE"))

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

                response = wait_for_response("LOGIN_RESPONSE")
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

                # The server may return MESSAGE_DELIVERED, MESSAGE_STORED,
                # or MESSAGE_ERROR.
                expected = {
                    "MESSAGE_DELIVERED",
                    "MESSAGE_STORED",
                    "MESSAGE_ERROR",
                }
                response = None
                for _ in range(3):
                    candidate = responses.get(timeout=10)
                    if candidate.get("type") in expected:
                        response = candidate
                        break
                    display_response(candidate)

                display_response(response)

            elif command == "history":
                if not token:
                    print("Log in first.")
                    continue

                send_json(sock, send_lock, {
                    "type": "HISTORY_REQUEST",
                    "token": token,
                })
                response = wait_for_response("HISTORY_RESPONSE")
                display_response(response)

                if response:
                    for item in response.get("messages", []):
                        print(
                            f"{item['sender']} -> {item['recipient']}: "
                            f"{item['content']} ({item['created_at']})"
                        )

            elif command == "logout":
                if not token:
                    print("You are not logged in.")
                    continue

                send_json(sock, send_lock, {
                    "type": "LOGOUT_REQUEST",
                    "token": token,
                })
                response = wait_for_response("LOGOUT_RESPONSE")
                display_response(response)
                token = None

            elif command == "quit":
                break

            elif command:
                print("Unknown command. Use register, login, msg, history, logout, or quit.")

    except (OSError, queue.Empty) as error:
        print(f"Communication error: {error}")
    finally:
        stop_event.set()
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        print("Disconnected.")


if __name__ == "__main__":
    main()
