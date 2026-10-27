"""Console client for the Team 5 TCP chat application."""

import base64
import hashlib
import json

import queue
import uuid
from pathlib import Path

import socket

import threading

import time

HOST = "127.0.0.1"

PORT = 5000

MAX_RESPONSE_BYTES = 65_536
MAX_FILE_SIZE = 1024 * 1024  # 1 MiB; must match server.py
FILE_CHUNK_SIZE = 8_192
DOWNLOAD_DIR = Path("received_files")

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
    """Read server events, including reconstructing incoming file transfers."""
    incoming_files = {}
    try:
        with sock.makefile("rb") as stream:
            while not stop_event.is_set():
                line = stream.readline(MAX_RESPONSE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_RESPONSE_BYTES or not line.endswith(b"\n"):
                    responses.put({"type": "ERROR", "message": "Invalid or oversized server response."})
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    responses.put({"type": "ERROR", "message": "Invalid server response."})
                    continue
                if not isinstance(message, dict):
                    responses.put({"type": "ERROR", "message": "Unexpected server response format."})
                    continue

                kind = message.get("type")
                transfer_id = message.get("transferId")
                if kind == "NEW_MESSAGE":
                    print(f"\n[Private message from {message.get('fromUser', 'unknown')}] "
                          f"{message.get('content', '')}\n> ", end="", flush=True)
                elif kind == "ADMIN_ANNOUNCEMENT":
                    print(f"\n[Announcement from {message.get('adminId', 'administrator')}] "
                          f"{message.get('message', '')}\n> ", end="", flush=True)
                elif kind == "ADMIN_MODERATION_NOTICE":
                    print(f"\n[You were {message.get('action', 'moderated')} by "
                          f"{message.get('adminId', 'an administrator')}] "
                          f"{message.get('reason', '')}\n> ", end="", flush=True)
                elif kind == "FILE_RECEIVE_START":
                    filename = message.get("filename")
                    size = message.get("size")
                    checksum = message.get("sha256")
                    if (not isinstance(transfer_id, str) or not isinstance(filename, str)
                            or not filename or Path(filename).name != filename
                            or not isinstance(size, int) or isinstance(size, bool)
                            or size < 0 or size > MAX_FILE_SIZE
                            or not isinstance(checksum, str) or len(checksum) != 64):
                        print("\n[File transfer rejected: invalid metadata]\n> ", end="", flush=True)
                        continue
                    incoming_files[transfer_id] = {
                        "filename": filename, "size": size, "sha256": checksum,
                        "fromUser": message.get("fromUser", "unknown"), "data": bytearray(),
                    }
                elif kind == "FILE_RECEIVE_CHUNK":
                    transfer = incoming_files.get(transfer_id)
                    if transfer is None:
                        continue
                    try:
                        chunk = base64.b64decode(message.get("data", ""), validate=True)
                    except (ValueError, base64.binascii.Error):
                        incoming_files.pop(transfer_id, None)
                        print("\n[File transfer failed: invalid chunk]\n> ", end="", flush=True)
                        continue
                    transfer["data"].extend(chunk)
                    if len(transfer["data"]) > transfer["size"]:
                        incoming_files.pop(transfer_id, None)
                        print("\n[File transfer failed: size exceeded]\n> ", end="", flush=True)
                elif kind == "FILE_RECEIVE_END":
                    transfer = incoming_files.pop(transfer_id, None)
                    if transfer is None:
                        continue
                    data = bytes(transfer["data"])
                    digest = hashlib.sha256(data).hexdigest()
                    if len(data) != transfer["size"] or digest != transfer["sha256"]:
                        print(f"\n[File from {transfer['fromUser']} failed checksum verification]\n> ", end="", flush=True)
                        continue
                    try:
                        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
                        destination = DOWNLOAD_DIR / transfer["filename"]
                        # Avoid overwriting a file that already exists.
                        if destination.exists():
                            destination = DOWNLOAD_DIR / f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}"
                        destination.write_bytes(data)
                        print(f"\n[File received from {transfer['fromUser']}] {destination} "
                              f"({len(data)} bytes; SHA-256 verified)\n> ", end="", flush=True)
                    except OSError as error:
                        print(f"\n[Could not save received file: {error}]\n> ", end="", flush=True)
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
                elif message.get("type") not in {
                    "ADMIN_ANNOUNCEMENT",
                    "ADMIN_MODERATION_NOTICE",
                }:
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

def describe_message_result(response):
    """Turn a SEND_MESSAGE result into the text shown to the sender (CHAT-F-013).

    Only MESSAGE_DELIVERED means the message reached the recipient; a message
    stored for an offline recipient is never reported as delivered.
    """
    if not response:
        return "No delivery confirmation received."
    kind = response.get("type")
    if kind == "MESSAGE_DELIVERED":
        return f"\u2713 Delivered (message {response.get('messageId', '?')})"
    if kind == "MESSAGE_STORED":
        return (f"Saved, not delivered yet: recipient is offline "
                f"(message {response.get('messageId', '?')})")
    if kind == "MESSAGE_ERROR":
        return (f"Message not sent: {response.get('message', 'unknown error')} "
                f"(code {response.get('code', '?')})")
    return f"Unexpected response: {kind}"


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


def wait_for_file_response(responses, stop_event, expected_types, timeout=10):
    """Wait for a file protocol response, including server-side errors."""
    deferred = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                message = responses.get(timeout=remaining)
            except queue.Empty:
                return None
            if message.get("type") in set(expected_types) | {"FILE_ERROR"}:
                return message
            deferred.append(message)
            if stop_event.is_set() and responses.empty():
                return None
    finally:
        for message in deferred:
            responses.put(message)


def send_file(sock, send_lock, responses, stop_event, token, recipient, filepath):
    """Send a file through the server using bounded Base64 JSON chunks."""
    path = Path(filepath).expanduser()
    try:
        if not path.is_file():
            print("File not found.")
            return
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            print(f"File exceeds the configured limit ({MAX_FILE_SIZE} bytes / 1 MiB).")
            return
        data = path.read_bytes()
    except OSError as error:
        print(f"Could not read file: {error}")
        return

    transfer_id = str(uuid.uuid4())
    checksum = hashlib.sha256(data).hexdigest()
    send_json(sock, send_lock, {
        "type": "FILE_START", "token": token, "toUser": recipient,
        "filename": path.name, "size": len(data), "sha256": checksum,
        "transferId": transfer_id,
    })
    response = wait_for_file_response(responses, stop_event, {"FILE_READY"})
    if response and response.get("type") == "FILE_ERROR":
        display_response(response)
        return
    if not response or response.get("transferId") != transfer_id:
        print("File transfer was not accepted by the server.")
        return

    chunks = [data[offset:offset + FILE_CHUNK_SIZE]
              for offset in range(0, len(data), FILE_CHUNK_SIZE)]
    if not chunks:
        chunks = [b""]
    for index, chunk in enumerate(chunks):
        final = index == len(chunks) - 1
        send_json(sock, send_lock, {
            "type": "FILE_CHUNK", "token": token, "transferId": transfer_id,
            "data": base64.b64encode(chunk).decode("ascii"), "final": final,
        })
        expected = "FILE_SENT" if final else "FILE_CHUNK_ACK"
        response = wait_for_file_response(responses, stop_event, {expected})
        if not response:
            print("File transfer failed or timed out.")
            return
        if response.get("type") == "FILE_ERROR":
            display_response(response)
            return
        if response.get("transferId") != transfer_id:
            print("Received an unexpected file-transfer response.")
            return
    print(f"File sent: {path.name} ({len(data)} bytes)")
    print(f"SHA-256: {checksum}")


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

    print("Commands: register, login, msg, announce, kick, ban, history, logout, quit")

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

                print(describe_message_result(response))

            elif command == "announce":

                if not token:

                    print("Log in first.")

                    continue

                content = input("Announcement: ").strip()

                send_json(sock, send_lock, {

                    "type": "ADMIN_BROADCAST",

                    "token": token,

                    "message": content,

                })

                response = wait_for_response(

                    responses,

                    "ADMIN_BROADCAST_RESPONSE",

                    stop_event,

                )

                display_response(response)

            elif command in {"kick", "ban"}:

                if not token:

                    print("Log in first.")

                    continue

                username = input("Username to moderate: ").strip()

                reason = input("Reason (optional): ").strip()

                send_json(sock, send_lock, {

                    "type": "ADMIN_BAN" if command == "ban" else "ADMIN_KICK",

                    "token": token,

                    "username": username,

                    "reason": reason,

                })

                response = wait_for_response(

                    responses,

                    "ADMIN_MODERATION_RESPONSE",

                    stop_event,

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

                    "Unknown command. Use register, login, msg, announce, "
                    "kick, ban, "

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
