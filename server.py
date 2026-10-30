"""Threaded TCP server for the Team 5 chat application.

Protocol: newline-delimited JSON over TCP.

Development configuration: localhost, port 5000, no TLS.

"""

import base64
import hashlib
import json
import os
import socket
import ssl

import re
import sys
import traceback
import unicodedata

import socketserver

import threading
import time

from datetime import datetime, timezone

import auth

import database

HOST = "127.0.0.1"

PORT = 5000

# Payload limits (CHAT-SR-003). The SRS does not state a maximum, so these are
# the documented defaults: one JSON request line may be at most 16 KiB and a
# chat message at most 4,000 characters. Larger input is rejected with 413.
MAX_REQUEST_BYTES = 16_384

MAX_MESSAGE_LENGTH = 4_000
MAX_FILE_SIZE = 1024 * 1024  # 1 MiB; documented default for CHAT-F-030
FILE_CHUNK_SIZE = 8_192  # Base64 JSON request remains below MAX_REQUEST_BYTES
ACTIVE_FILE_TRANSFERS = {}
FILE_TRANSFER_LOCK = threading.Lock()
FILE_TRANSFER_TIMEOUT_SECONDS = 120.0

# username -> (socket, socket-send lock)

ACTIVE_CLIENTS = {}

ACTIVE_CLIENTS_LOCK = threading.Lock()
TYPING_STATE_TIMEOUT_SECONDS = 1.5
TYPING_STATES = {}
TYPING_LOCK = threading.Lock()

HEARTBEAT_INTERVAL_SECONDS = 10.0
HEARTBEAT_TIMEOUT_SECONDS = 30.0
HEARTBEAT_LAST_SEEN = {}
HEARTBEAT_TOKENS = {}
HEARTBEAT_LOCK = threading.Lock()

LOGIN_RATE_MAX_FAILURES = max(1, int(os.getenv("CHAT_LOGIN_RATE_MAX_FAILURES", "5")))
LOGIN_RATE_WINDOW_SECONDS = max(1.0, float(os.getenv("CHAT_LOGIN_RATE_WINDOW_SECONDS", "60")))
LOGIN_RATE_LOCKOUT_SECONDS = max(1.0, float(os.getenv("CHAT_LOGIN_RATE_LOCKOUT_SECONDS", "60")))
LOGIN_FAILURES_BY_IP = {}
LOGIN_BLOCKED_UNTIL_BY_IP = {}
LOGIN_RATE_LOCK = threading.Lock()


def is_login_rate_limited(ip_address):
    now = time.monotonic()
    with LOGIN_RATE_LOCK:
        blocked_until = LOGIN_BLOCKED_UNTIL_BY_IP.get(ip_address)
        if blocked_until is not None:
            if now < blocked_until:
                return True
            LOGIN_BLOCKED_UNTIL_BY_IP.pop(ip_address, None)
            LOGIN_FAILURES_BY_IP.pop(ip_address, None)

        cutoff = now - LOGIN_RATE_WINDOW_SECONDS
        failures = [timestamp for timestamp in LOGIN_FAILURES_BY_IP.get(ip_address, []) if timestamp >= cutoff]
        if failures:
            LOGIN_FAILURES_BY_IP[ip_address] = failures
        else:
            LOGIN_FAILURES_BY_IP.pop(ip_address, None)
        return False


def record_failed_login(ip_address):
    now = time.monotonic()
    with LOGIN_RATE_LOCK:
        cutoff = now - LOGIN_RATE_WINDOW_SECONDS
        failures = [timestamp for timestamp in LOGIN_FAILURES_BY_IP.get(ip_address, []) if timestamp >= cutoff]
        failures.append(now)
        LOGIN_FAILURES_BY_IP[ip_address] = failures
        if len(failures) >= LOGIN_RATE_MAX_FAILURES:
            LOGIN_BLOCKED_UNTIL_BY_IP[ip_address] = now + LOGIN_RATE_LOCKOUT_SECONDS


def clear_login_failures(ip_address):
    with LOGIN_RATE_LOCK:
        LOGIN_FAILURES_BY_IP.pop(ip_address, None)
        LOGIN_BLOCKED_UNTIL_BY_IP.pop(ip_address, None)

# Serialises "store + live-deliver" (sender side) against "register + replay
# queued messages" (login side) so a message is never delivered twice and
# queued messages cannot be overtaken by newer live ones.

DELIVERY_LOCK = threading.Lock()

def to_iso_timestamp(db_timestamp):

    """Convert SQLite's UTC 'YYYY-MM-DD HH:MM:SS' value to ISO 8601."""

    try:

        parsed = datetime.strptime(db_timestamp, "%Y-%m-%d %H:%M:%S")

    except (TypeError, ValueError):

        return datetime.now(timezone.utc).isoformat()

    return parsed.replace(tzinfo=timezone.utc).isoformat()

def send_json(client_socket, send_lock, payload):

    """Send one complete JSON response, terminated by a newline."""

    encoded = (

        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

    ).encode("utf-8")

    with send_lock:

        client_socket.sendall(encoded)


def configured_admins():

    """Return the exact usernames configured as server administrators."""

    return {
        username.strip()
        for username in os.environ.get("CHAT_ADMIN_USERS", "").split(",")
        if username.strip()
    }

ROOM_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")

# room key (lower-case name) -> {"name": display name, "members": set of usernames}
# Rooms live in memory only (documented deviation): they reset on server restart.
ROOMS = {}
# Lock order rule: never acquire ACTIVE_CLIENTS_LOCK while holding ROOMS_LOCK.
ROOMS_LOCK = threading.Lock()


def send_to_user(username, payload):
    """Push an event to one online user; return True if it was written."""
    with ACTIVE_CLIENTS_LOCK:
        target = ACTIVE_CLIENTS.get(username)
    if target is None:
        return False
    try:
        send_json(target[0], target[1], payload)
        return True
    except (OSError, ConnectionError):
        return False


def release_file_transfer_id(transfer_id):
    with FILE_TRANSFER_LOCK:
        ACTIVE_FILE_TRANSFERS.pop(transfer_id, None)


def refresh_file_transfer_timeout(transfer_id, owner):
    """Reset an active upload's idle timeout after receiving a valid chunk."""
    with FILE_TRANSFER_LOCK:
        if transfer_id in ACTIVE_FILE_TRANSFERS:
            current_owner, _ = ACTIVE_FILE_TRANSFERS[transfer_id]
            if current_owner is owner:
                ACTIVE_FILE_TRANSFERS[transfer_id] = (owner, time.monotonic())


def expire_stale_file_transfers(now=None):
    """Discard uploads that have been idle for the configured timeout."""
    if now is None:
        now = time.monotonic()
    with FILE_TRANSFER_LOCK:
        stale = [
            (transfer_id, owner, started_at)
            for transfer_id, (owner, started_at) in ACTIVE_FILE_TRANSFERS.items()
            if now - started_at >= FILE_TRANSFER_TIMEOUT_SECONDS
        ]
    for transfer_id, owner, started_at in stale:
        with owner.file_transfer_lock:
            with FILE_TRANSFER_LOCK:
                if ACTIVE_FILE_TRANSFERS.get(transfer_id) == (owner, started_at):
                    ACTIVE_FILE_TRANSFERS.pop(transfer_id, None)
                    owner.file_transfers.pop(transfer_id, None)


def send_typing_indicator(sender, destination_type, destination, is_typing):
    """Send a typing transition only to its private or room recipients."""
    if destination_type == "room":
        with ROOMS_LOCK:
            room = ROOMS.get(destination)
            if room is None:
                return
            recipients = sorted(room["members"] - {sender})
            destination_name = room["name"]
    else:
        recipients = [destination]
        destination_name = destination

    event = {
        "type": "TYPING_INDICATOR",
        "fromUser": sender,
        "isTyping": is_typing,
    }
    event["roomId" if destination_type == "room" else "toUser"] = destination_name
    for recipient in recipients:
        send_to_user(recipient, event)


def clear_typing_states(username, room_key=None):
    """Clear typing state owned by or addressed to a departing user."""
    with TYPING_LOCK:
        removed = []
        for key in list(TYPING_STATES):
            sender, destination_type, destination = key
            if sender == username and (
                room_key is None
                or (destination_type == "room" and destination == room_key)
            ):
                removed.append(key)
            elif room_key is None and destination_type == "user" and destination == username:
                TYPING_STATES.pop(key, None)
        for key in removed:
            TYPING_STATES.pop(key, None)

    for sender, destination_type, destination in removed:
        send_typing_indicator(sender, destination_type, destination, False)


def expire_stale_typing_states(now=None):
    """Expire states whose client stopped sending typing updates."""
    if now is None:
        now = time.monotonic()
    cutoff = now - TYPING_STATE_TIMEOUT_SECONDS
    with TYPING_LOCK:
        expired = [key for key, updated in TYPING_STATES.items() if updated < cutoff]
        for key in expired:
            TYPING_STATES.pop(key, None)
    for sender, destination_type, destination in expired:
        send_typing_indicator(sender, destination_type, destination, False)


def broadcast_room_event(room_key, event, user):
    """Tell every current member of a room that `user` joined or left."""
    with ROOMS_LOCK:
        room = ROOMS.get(room_key)
        if room is None:
            return
        name = room["name"]
        members = sorted(room["members"])
    for member in members:
        if member != user:
            send_to_user(member, {
                "type": "ROOM_EVENT", "event": event, "room": name,
                "user": user, "members": members,
            })


def leave_all_rooms(username):
    """Remove a user from every room; return the keys of rooms they were in."""
    with ROOMS_LOCK:
        left = [key for key, room in ROOMS.items() if username in room["members"]]
        for key in left:
            ROOMS[key]["members"].discard(username)
    return left


def has_control_chars(text, allowed=""):
    """True if text contains control characters other than those in `allowed`."""
    return any(
        unicodedata.category(ch) == "Cc" and ch not in allowed for ch in text
    )


def log_unexpected_error(client_address):
    """Log a handler failure server-side only; clients get a generic 500."""
    print(f"[ERROR] Unhandled exception for {client_address}", file=sys.stderr)
    traceback.print_exc()


class ChatHandler(socketserver.StreamRequestHandler):

    """Handle requests from one connected client."""

    def setup(self):

        super().setup()

        self.send_lock = threading.Lock()

        self.username = None

        self.token = None
        self.close_after_request = False
        self.file_transfers = {}
        self.file_transfer_lock = threading.RLock()
        self.left_rooms = []

    def handle(self):

        print(f"[CONNECT] Client connected from {self.client_address}")

        try:

            while True:

                line = self.rfile.readline(MAX_REQUEST_BYTES + 1)

                if not line:

                    break

                if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):

                    self.reply({

                        "type": "ERROR",

                        "code": 413,

                        "message": "Request too large or improperly framed.",

                    })

                    break

                try:

                    request = json.loads(line.decode("utf-8"))

                    if not isinstance(request, dict):

                        raise ValueError("Expected a JSON object")

                except (json.JSONDecodeError, UnicodeDecodeError, ValueError,
                        RecursionError):

                    self.reply({

                        "type": "ERROR",

                        "code": 400,

                        "message": "Invalid JSON request.",

                    })

                    continue

                try:

                    self.process_request(request)

                    if self.close_after_request:

                        break

                except Exception:

                    # Any unexpected failure while handling one request must not
                    # kill this connection's thread or leak internals (SR-003).

                    log_unexpected_error(self.client_address)


                    self.reply({

                        "type": "ERROR",

                        "code": 500,

                        "message": "Request could not be completed.",

                    })

        except (OSError, ConnectionError):

            pass

        finally:

            self.cleanup()

            print(f"[DISCONNECT] Client disconnected from {self.client_address}")

    def reply(self, payload):

        """Send a response without exposing internal exception details."""

        try:

            send_json(self.request, self.send_lock, payload)

        except (OSError, ConnectionError):

            pass

    def process_request(self, request):

        """Dispatch a request by its protocol type."""

        request_type = request.get("type")

        if request_type == "REGISTER_REQUEST":

            self.handle_register(request)

        elif request_type == "LOGIN_REQUEST":

            self.handle_login(request)

        elif request_type == "LOGOUT_REQUEST":

            self.handle_logout(request)

        elif request_type == "PONG":

            if self.username is not None:
                with HEARTBEAT_LOCK:
                    HEARTBEAT_LAST_SEEN[self.username] = datetime.now(timezone.utc).timestamp()

        elif request_type == "SEND_MESSAGE":

            self.handle_send_message(request)

        elif request_type == "HISTORY_REQUEST":

            self.handle_history(request)

        elif request_type == "TYPING":

            self.handle_typing(request)

        elif request_type == "FILE_START":

            self.handle_file_start(request)

        elif request_type == "FILE_CHUNK":

            self.handle_file_chunk(request)

        elif request_type == "ADMIN_BROADCAST":

            self.handle_admin_broadcast(request)

        elif request_type in {"ADMIN_KICK", "ADMIN_BAN"}:

            self.handle_admin_moderation(request, request_type)

        elif request_type == "CREATE_ROOM":

            self.handle_create_room(request)

        elif request_type == "JOIN_ROOM":

            self.handle_join_room(request)

        elif request_type == "LEAVE_ROOM":

            self.handle_leave_room(request)

        elif request_type == "LIST_ROOMS":

            self.handle_list_rooms(request)

        elif request_type == "LIST_USERS":

            self.handle_list_users(request)

        else:

            self.reply({

                "type": "ERROR",

                "code": 400,

                "message": "Unknown request type.",

            })

    def handle_register(self, request):

        username = request.get("username")

        password = request.get("password")

        success, message = auth.register(username, password)

        if success:

            self.reply({

                "type": "REGISTER_RESPONSE",

                "status": "OK",

                "message": message,

            })

        else:

            duplicate = message == "Username already exists."

            self.reply({

                "type": "REGISTER_RESPONSE",

                "status": "ERROR",

                "code": 409 if duplicate else 400,

                "message": message,

            })

    def handle_login(self, request):

        ip_address = self.client_address[0] if isinstance(self.client_address, tuple) else str(self.client_address)

        if is_login_rate_limited(ip_address):
            self.reply({
                "type": "LOGIN_RESPONSE",
                "status": "ERROR",
                "code": 429,
                "message": "Too many login attempts. Try again later.",
            })
            self.close_after_request = True
            return

        if self.username is not None:

            self.reply({

                "type": "LOGIN_RESPONSE",

                "status": "ERROR",

                "code": 409,

                "message": "This connection is already authenticated.",

            })

            return

        requested_username = request.get("username")

        if (isinstance(requested_username, str)
                and database.is_user_banned(requested_username)):

            self.reply({

                "type": "LOGIN_RESPONSE",

                "status": "ERROR",

                "code": 403,

                "message": "This account is banned from the server.",

            })

            self.close_after_request = True

            record_failed_login(ip_address)
            return

        result = auth.login(

            requested_username,

            request.get("password"),

        )

        if result is None:

            self.reply({

                "type": "LOGIN_RESPONSE",

                "status": "ERROR",

                "code": 401,

                "message": "Invalid credentials.",

            })

            # A rejected login ends this connection; retries reconnect first.

            self.close_after_request = True

            record_failed_login(ip_address)
            return

        clear_login_failures(ip_address)
        username = result["username"]

        token = result["token"]

        # Registering the connection, answering the login and replaying queued
        # messages happen under one lock, so a concurrent sender can neither
        # deliver ahead of the login response nor duplicate a queued message.

        with DELIVERY_LOCK:

            self.complete_login(username, token)

    def complete_login(self, username, token):

        """Register the connection, confirm login, then replay queued messages."""

        # Only one active connection per username in this initial version.

        with ACTIVE_CLIENTS_LOCK:

            old_connection = ACTIVE_CLIENTS.get(username)

            ACTIVE_CLIENTS[username] = (self.request, self.send_lock)

        self.username = username

        self.token = token

        with HEARTBEAT_LOCK:
            HEARTBEAT_LAST_SEEN[username] = datetime.now(timezone.utc).timestamp()
            HEARTBEAT_TOKENS[username] = token

        # Close any previous active connection for this username.

        if old_connection is not None and old_connection[0] is not self.request:

            old_socket = old_connection[0]

            try:

                old_socket.shutdown(2)

            except OSError:

                pass

            try:

                old_socket.close()

            except OSError:

                pass

        self.reply({

            "type": "LOGIN_RESPONSE",

            "status": "OK",

            "token": token,

            "userId": username,

        })

        self.deliver_queued_messages(username)

    def deliver_queued_messages(self, username):

        """Send messages stored while the user was offline, oldest first.

        Each message is marked delivered only after it was written to the
        socket. If the connection fails part-way, the remainder stays queued
        and is retried on the user's next login.
        """

        for stored in database.get_pending_messages(username):

            try:

                send_json(self.request, self.send_lock, {

                    "type": "NEW_MESSAGE",

                    "messageId": str(stored["id"]),

                    "fromUser": stored["sender"],

                    "content": stored["content"],

                    "timestamp": to_iso_timestamp(stored["created_at"]),

                    "queued": True,

                })

            except (OSError, ConnectionError):

                return

            database.mark_message_delivered(stored["id"])

    def authenticated_username(self, request):

        """Return the authenticated username, or None."""

        token = request.get("token")

        if not isinstance(token, str) or not token:

            return None

        if self.username is None or token != self.token:

            return None

        username = database.get_session_user(token)

        if username != self.username:

            return None

        return username

    def handle_typing(self, request):

        """Forward a typing transition to one user or the members of a room."""
        sender = self.authenticated_username(request)
        if sender is None:
            self.reply({"type": "TYPING_RESPONSE", "status": "ERROR",
                        "code": 401, "message": "Invalid or expired token."})
            return

        is_typing = request.get("isTyping")
        has_recipient = "toUser" in request
        has_room = "roomId" in request
        if has_recipient == has_room:
            self.reply({"type": "TYPING_RESPONSE", "status": "ERROR",
                        "code": 400, "message": "Specify exactly one recipient or room."})
            return
        if not isinstance(is_typing, bool):
            self.reply({"type": "TYPING_RESPONSE", "status": "ERROR",
                        "code": 400, "message": "isTyping must be a boolean."})
            return

        if has_room:
            room_id = request.get("roomId")
            if not isinstance(room_id, str) or not ROOM_NAME_PATTERN.fullmatch(room_id):
                code, message = 400, "A valid room name is required."
            else:
                destination = room_id.lower()
                with ROOMS_LOCK:
                    room = ROOMS.get(destination)
                    if room is None:
                        code, message = 404, "Room not found."
                    elif sender not in room["members"]:
                        code, message = 403, "You are not a member of this room."
                    else:
                        code = None
                destination_type = "room"
        else:
            recipient = request.get("toUser")
            if not isinstance(recipient, str) or not recipient.strip():
                code, message = 400, "A recipient username is required."
            else:
                recipient_user = database.get_user(recipient.strip())
                if recipient_user is None:
                    code, message = 404, "Recipient not found."
                else:
                    destination = recipient_user["username"]
                    destination_type = "user"
                    code = None

        if code is not None:
            self.reply({"type": "TYPING_RESPONSE", "status": "ERROR",
                        "code": code, "message": message})
            return
        if destination_type == "user" and destination == sender:
            self.reply({"type": "TYPING_RESPONSE", "status": "OK"})
            return

        state_key = (sender, destination_type, destination)
        changed = False
        with TYPING_LOCK:
            if is_typing:
                changed = state_key not in TYPING_STATES
                TYPING_STATES[state_key] = time.monotonic()
            elif state_key in TYPING_STATES:
                TYPING_STATES.pop(state_key)
                changed = True
        if changed:
            send_typing_indicator(sender, destination_type, destination, is_typing)
        self.reply({"type": "TYPING_RESPONSE", "status": "OK"})

    def handle_send_message(self, request):

        sender = self.authenticated_username(request)

        if sender is None:

            self.reply({

                "type": "MESSAGE_ERROR",

                "code": 401,

                "message": "Invalid or expired token.",

            })

            return

        if "roomId" in request:

            self.handle_room_message(sender, request)

            return

        recipient = request.get("toUser")

        content = request.get("content")

        if not isinstance(recipient, str) or not recipient.strip():

            self.reply({

                "type": "MESSAGE_ERROR",

                "code": 400,

                "message": "A recipient username is required.",

            })

            return

        if not isinstance(content, str) or not content.strip():

            self.reply({

                "type": "MESSAGE_ERROR",

                "code": 400,

                "message": "Message content cannot be empty.",

            })

            return

        if len(content) > MAX_MESSAGE_LENGTH:

            self.reply({

                "type": "MESSAGE_ERROR",

                "code": 413,

                "message": "Message exceeds the allowed length.",

            })

            return

        if (has_control_chars(content, allowed="\n\r\t")
                or has_control_chars(recipient)):

            self.reply({

                "type": "MESSAGE_ERROR",

                "code": 400,

                "message": "Message contains unsupported control characters.",

            })

            return

        recipient_user = database.get_user(recipient)

        if recipient_user is None:

            self.reply({

                "type": "MESSAGE_ERROR",

                "code": 404,

                "message": "Recipient not found.",

            })

            return

        recipient = recipient_user["username"]

        message_id, timestamp, delivered = self.store_and_deliver(

            sender, recipient, content,

        )

        if delivered:

            self.reply({

                "type": "MESSAGE_DELIVERED",

                "messageId": str(message_id),

                "deliveredAt": timestamp,

            })

        else:

            # The message is stored but not confirmed as delivered.

            self.reply({

                "type": "MESSAGE_STORED",

                "messageId": str(message_id),

                "message": "Message saved; recipient is offline.",

            })

    def handle_file_start(self, request):
        """Validate a file transfer before accepting its chunks."""
        sender = self.authenticated_username(request)
        if sender is None:
            self.reply({"type": "FILE_ERROR", "code": 401,
                        "message": "Authentication required."})
            return

        recipient = request.get("toUser")
        room_id = request.get("roomId")
        filename = request.get("filename")
        size = request.get("size")
        checksum = request.get("sha256")
        transfer_id = request.get("transferId")

        if ("toUser" in request) == ("roomId" in request):
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Specify exactly one recipient or room."})
            return
        if (not isinstance(filename, str) or not filename.strip()
                or filename in {".", ".."} or "/" in filename or "\\" in filename
                or ":" in filename or has_control_chars(filename)):
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid filename."})
            return
        if not isinstance(size, int) or isinstance(size, bool):
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "File size must be a non-negative integer."})
            return
        if size < 0:
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "File size must be a non-negative integer."})
            return
        if size > MAX_FILE_SIZE:
            self.reply({"type": "FILE_ERROR", "code": 413,
                        "message": f"File exceeds the configured limit of {MAX_FILE_SIZE} bytes."})
            return
        if (not isinstance(checksum, str) or len(checksum) != 64
                or any(ch not in "0123456789abcdefABCDEF" for ch in checksum)):
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid SHA-256 checksum."})
            return
        if (not isinstance(transfer_id, str) or not transfer_id
                or len(transfer_id) > 64 or has_control_chars(transfer_id)):
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid transfer ID."})
            return

        if room_id is not None:
            if not isinstance(room_id, str) or not ROOM_NAME_PATTERN.fullmatch(room_id):
                self.reply({"type": "FILE_ERROR", "code": 400,
                            "message": "A valid room name is required."})
                return
            destination = room_id.lower()
            with ROOMS_LOCK:
                room = ROOMS.get(destination)
                if room is None:
                    code, message = 404, "Room not found."
                    room_name = None
                    members = set()
                elif sender not in room["members"]:
                    code, message = 403, "You are not a member of this room."
                    room_name = None
                    members = set()
                else:
                    code = None
                    room_name = room["name"]
                    members = set(room["members"] - {sender})
            if code is not None:
                self.reply({"type": "FILE_ERROR", "code": code, "message": message})
                return
            with ACTIVE_CLIENTS_LOCK:
                recipients = sorted(members & set(ACTIVE_CLIENTS))
            if not recipients:
                self.reply({"type": "FILE_ERROR", "code": 404,
                            "message": "No other room members are online."})
                return
            destination_type = "room"
        else:
            if not isinstance(recipient, str) or not recipient.strip():
                self.reply({"type": "FILE_ERROR", "code": 400,
                            "message": "Recipient is required."})
                return
            recipient_user = database.get_user(recipient.strip())
            if recipient_user is None:
                self.reply({"type": "FILE_ERROR", "code": 404,
                            "message": "Recipient not found."})
                return
            recipient = recipient_user["username"]
            if recipient == sender:
                self.reply({"type": "FILE_ERROR", "code": 400,
                            "message": "Cannot send a file to yourself."})
                return
            with ACTIVE_CLIENTS_LOCK:
                online = recipient in ACTIVE_CLIENTS
            if not online:
                self.reply({"type": "FILE_ERROR", "code": 404,
                            "message": "Recipient is offline."})
                return
            recipients = [recipient]
            room_name = None
            destination_type = "user"

        with FILE_TRANSFER_LOCK:
            if transfer_id in ACTIVE_FILE_TRANSFERS:
                duplicate_transfer_id = True
            else:
                ACTIVE_FILE_TRANSFERS[transfer_id] = (self, time.monotonic())
                duplicate_transfer_id = False
        if duplicate_transfer_id:
            self.reply({"type": "FILE_ERROR", "code": 409,
                        "message": "Transfer ID already exists."})
            return

        with self.file_transfer_lock:
            self.file_transfers[transfer_id] = {
                "sender": sender,
                "recipients": recipients,
                "destination_type": destination_type,
                "room": room_name,
                "filename": filename,
                "size": size,
                "sha256": checksum.lower(),
                "data": bytearray(),
            }
        self.reply({"type": "FILE_READY", "transferId": transfer_id})

    def discard_file_transfer(self, transfer_id):
        with self.file_transfer_lock:
            self.file_transfers.pop(transfer_id, None)
            release_file_transfer_id(transfer_id)

    def handle_file_chunk(self, request):
        with self.file_transfer_lock:
            self._handle_file_chunk(request)

    def _handle_file_chunk(self, request):
        """Collect chunks, verify SHA-256, and forward the intact file."""
        sender = self.authenticated_username(request)
        if sender is None:
            self.reply({"type": "FILE_ERROR", "code": 401,
                        "message": "Authentication required."})
            return

        transfer_id = request.get("transferId")
        # transferId comes from the client: only strings are valid dict keys here.
        transfer = (self.file_transfers.get(transfer_id)
                    if isinstance(transfer_id, str) else None)
        encoded = request.get("data")
        final = request.get("final")
        if transfer is None or transfer["sender"] != sender:
            self.reply({"type": "FILE_ERROR", "code": 404,
                        "message": "Transfer not found."})
            return
        if not isinstance(encoded, str) or not isinstance(final, bool):
            self.discard_file_transfer(transfer_id)
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid file chunk."})
            return
        try:
            chunk = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            self.discard_file_transfer(transfer_id)
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid Base64 chunk."})
            return
        if len(chunk) > FILE_CHUNK_SIZE:
            self.discard_file_transfer(transfer_id)
            self.reply({"type": "FILE_ERROR", "code": 413,
                        "message": "Chunk exceeds the configured limit."})
            return

        if len(transfer["data"]) + len(chunk) > transfer["size"]:
            self.discard_file_transfer(transfer_id)
            self.reply({"type": "FILE_ERROR", "code": 413,
                        "message": "Received more data than declared."})
            return
        transfer["data"].extend(chunk)
        if not final:
            refresh_file_transfer_timeout(transfer_id, self)
            self.reply({"type": "FILE_CHUNK_ACK", "transferId": transfer_id})
            return

        self.discard_file_transfer(transfer_id)
        file_data = bytes(transfer["data"])
        if len(file_data) != transfer["size"]:
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "File size does not match declared size."})
            return
        checksum = hashlib.sha256(file_data).hexdigest()
        if checksum != transfer["sha256"]:
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "File checksum verification failed."})
            return

        with ACTIVE_CLIENTS_LOCK:
            recipients = set(transfer["recipients"])
            if transfer["destination_type"] == "room":
                with ROOMS_LOCK:
                    room = ROOMS.get(transfer["room"].lower())
                    if room is None:
                        recipients.clear()
                    else:
                        recipients.intersection_update(room["members"])
            targets = [(name, ACTIVE_CLIENTS.get(name))
                       for name in recipients]
        delivered_to = 0
        for recipient, target in targets:
            if target is None:
                continue
            target_socket, target_lock = target
            try:
                with target_lock:
                    def send_event(payload):
                        data = (json.dumps(payload, ensure_ascii=False,
                                           separators=(",", ":")) + "\n").encode("utf-8")
                        target_socket.sendall(data)

                    start_event = {
                        "type": "FILE_RECEIVE_START", "transferId": transfer_id,
                        "fromUser": sender, "filename": transfer["filename"],
                        "size": len(file_data), "sha256": checksum,
                    }
                    if transfer["destination_type"] == "room":
                        start_event["roomId"] = transfer["room"]
                    send_event(start_event)
                    for offset in range(0, len(file_data), FILE_CHUNK_SIZE):
                        send_event({"type": "FILE_RECEIVE_CHUNK", "transferId": transfer_id,
                                    "data": base64.b64encode(
                                        file_data[offset:offset + FILE_CHUNK_SIZE]
                                    ).decode("ascii")})
                    send_event({"type": "FILE_RECEIVE_END", "transferId": transfer_id})
                delivered_to += 1
            except (OSError, ConnectionError):
                continue

        if not delivered_to:
            self.reply({"type": "FILE_ERROR", "code": 404,
                        "message": "All file recipients went offline."})
            return
        self.reply({"type": "FILE_SENT", "transferId": transfer_id,
                    "filename": transfer["filename"], "size": len(file_data),
                    "sha256": checksum, "deliveredTo": delivered_to})
    def room_reply(self, response_type, status, **fields):
        self.reply({"type": response_type, "status": status, **fields})

    def room_name_from(self, request, response_type="ROOM_RESPONSE"):
        """Return (room_key, name) for a valid room name, else reply 400 and None."""
        name = request.get("room")
        if not isinstance(name, str) or not ROOM_NAME_PATTERN.fullmatch(name):
            self.room_reply(
                response_type, "ERROR", code=400,
                message="Room name must be 3-32 characters: letters, numbers, _ or -.",
            )
            return None
        return name.lower(), name

    def handle_create_room(self, request):
        """CHAT-F-020: create a named room; the creator becomes its first member."""
        user = self.authenticated_username(request)
        if user is None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=401,
                            message="Invalid or expired token.")
            return
        parsed = self.room_name_from(request)
        if parsed is None:
            return
        key, name = parsed
        with ROOMS_LOCK:
            exists = key in ROOMS
            if not exists:
                ROOMS[key] = {"name": name, "members": {user}}
        if exists:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=409,
                            message="A room with that name already exists.")
            return
        self.room_reply("ROOM_RESPONSE", "OK", action="CREATE", room=name,
                        members=[user])

    def handle_join_room(self, request):
        """CHAT-F-021: join an existing room."""
        user = self.authenticated_username(request)
        if user is None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=401,
                            message="Invalid or expired token.")
            return
        parsed = self.room_name_from(request)
        if parsed is None:
            return
        key, _ = parsed
        code = None
        with ROOMS_LOCK:
            room = ROOMS.get(key)
            if room is None:
                code, message = 404, "Room not found."
            elif user in room["members"]:
                code, message = 409, "You are already in this room."
            else:
                room["members"].add(user)
                name = room["name"]
                members = sorted(room["members"])
        if code is not None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=code, message=message)
            return
        self.room_reply("ROOM_RESPONSE", "OK", action="JOIN", room=name,
                        members=members)
        broadcast_room_event(key, "JOINED", user)

    def handle_leave_room(self, request):
        """CHAT-F-021: leave a room you are in."""
        user = self.authenticated_username(request)
        if user is None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=401,
                            message="Invalid or expired token.")
            return
        parsed = self.room_name_from(request)
        if parsed is None:
            return
        key, _ = parsed
        code = None
        with ROOMS_LOCK:
            room = ROOMS.get(key)
            if room is None:
                code, message = 404, "Room not found."
            elif user not in room["members"]:
                code, message = 409, "You are not in this room."
            else:
                room["members"].discard(user)
                name = room["name"]
        if code is not None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=code, message=message)
            return
        clear_typing_states(user, room_key=key)
        self.room_reply("ROOM_RESPONSE", "OK", action="LEAVE", room=name)
        broadcast_room_event(key, "LEFT", user)

    def handle_list_rooms(self, request):
        """Room directory: every room with its member count."""
        if self.authenticated_username(request) is None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=401,
                            message="Invalid or expired token.")
            return
        with ROOMS_LOCK:
            rooms = [{"name": r["name"], "memberCount": len(r["members"])}
                     for r in ROOMS.values()]
        rooms.sort(key=lambda r: r["name"].lower())
        self.reply({"type": "ROOM_LIST", "rooms": rooms})

    def handle_list_users(self, request):
        """CHAT-F-023: online users, globally or for one room you belong to."""
        user = self.authenticated_username(request)
        if user is None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=401,
                            message="Invalid or expired token.")
            return
        room_field = request.get("room")
        with ACTIVE_CLIENTS_LOCK:
            online = set(ACTIVE_CLIENTS)
        if room_field is None:
            self.reply({"type": "USER_LIST", "room": None, "users": sorted(online)})
            return
        parsed = self.room_name_from(request)
        if parsed is None:
            return
        key, _ = parsed
        code = None
        with ROOMS_LOCK:
            room = ROOMS.get(key)
            if room is None:
                code, message = 404, "Room not found."
            elif user not in room["members"]:
                code, message = 403, "You are not a member of this room."
            else:
                name = room["name"]
                members = set(room["members"])
        if code is not None:
            self.room_reply("ROOM_RESPONSE", "ERROR", code=code, message=message)
            return
        self.reply({"type": "USER_LIST", "room": name,
                    "users": sorted(members & online)})

    def handle_room_message(self, sender, request):
        """CHAT-F-022: broadcast a message to every online member of a room."""
        room_id = request.get("roomId")
        content = request.get("content")
        if not isinstance(room_id, str) or not ROOM_NAME_PATTERN.fullmatch(room_id):
            self.reply({"type": "MESSAGE_ERROR", "code": 400,
                        "message": "A valid room name is required."})
            return
        if not isinstance(content, str) or not content.strip():
            self.reply({"type": "MESSAGE_ERROR", "code": 400,
                        "message": "Message content cannot be empty."})
            return
        if len(content) > MAX_MESSAGE_LENGTH:
            self.reply({"type": "MESSAGE_ERROR", "code": 413,
                        "message": "Message exceeds the allowed length."})
            return
        if has_control_chars(content, allowed="\n\r\t"):
            self.reply({"type": "MESSAGE_ERROR", "code": 400,
                        "message": "Message contains unsupported control characters."})
            return
        with ROOMS_LOCK:
            room = ROOMS.get(room_id.lower())
            if room is None:
                code, message = 404, "Room not found."
            elif sender not in room["members"]:
                code, message = 403, "You are not a member of this room."
            else:
                code = None
                name = room["name"]
                recipients = sorted(room["members"] - {sender})
        if code is not None:
            self.reply({"type": "MESSAGE_ERROR", "code": code, "message": message})
            return
        # Stored under "#<room>" (usernames cannot contain '#'), already delivered
        # so it is never replayed from the offline queue.
        message_id = database.save_message(sender, "#" + name, content, delivered=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        delivered_to = 0
        for member in recipients:
            if send_to_user(member, {
                "type": "NEW_MESSAGE", "messageId": str(message_id),
                "fromUser": sender, "roomId": name, "content": content,
                "timestamp": timestamp,
            }):
                delivered_to += 1
        if delivered_to:
            self.reply({"type": "MESSAGE_DELIVERED", "messageId": str(message_id),
                        "deliveredAt": timestamp, "room": name,
                        "recipients": delivered_to})
        else:
            self.reply({"type": "MESSAGE_STORED", "messageId": str(message_id),
                        "message": "Message saved; no other room members are online."})

    def store_and_deliver(self, sender, recipient, content):

        """Persist a message, then push it live if the recipient is online.

        A message that cannot be delivered right now stays flagged as
        undelivered, which queues it for the recipient's next login.
        Returns (message_id, timestamp, delivered).
        """

        with DELIVERY_LOCK:

            message_id = database.save_message(sender, recipient, content)

            timestamp = datetime.now(timezone.utc).isoformat()

            with ACTIVE_CLIENTS_LOCK:

                target = ACTIVE_CLIENTS.get(recipient)

            delivered = False

            if target is not None:

                target_socket, target_lock = target

                try:

                    send_json(target_socket, target_lock, {

                        "type": "NEW_MESSAGE",

                        "messageId": str(message_id),

                        "fromUser": sender,

                        "content": content,

                        "timestamp": timestamp,

                    })

                    delivered = True

                except (OSError, ConnectionError):

                    pass

            if delivered:

                database.mark_message_delivered(message_id)

        return message_id, timestamp, delivered

    def handle_history(self, request):

        username = self.authenticated_username(request)

        if username is None:

            self.reply({

                "type": "ERROR",

                "code": 401,

                "message": "Invalid or expired token.",

            })

            return

        limit = request.get("limit", 50)
        before_id = request.get("beforeId")
        if (not isinstance(limit, int) or isinstance(limit, bool)
                or not 1 <= limit <= 200):
            self.reply({"type": "ERROR", "code": 400,
                        "message": "History limit must be between 1 and 200."})
            return
        try:
            messages = database.get_messages_for(
                username, limit=limit + 1, before_id=before_id,
            )
        except ValueError as error:
            self.reply({"type": "ERROR", "code": 400, "message": str(error)})
            return
        has_more = len(messages) > limit
        if has_more:
            messages = messages[-limit:]

        self.reply({

            "type": "HISTORY_RESPONSE",

            "messages": messages,
            "nextBeforeId": messages[0]["id"] if has_more else None,

        })

    def handle_admin_broadcast(self, request):

        """Send an administrator announcement to every connected client."""

        username = self.authenticated_username(request)

        if username is None:

            self.reply({

                "type": "ADMIN_BROADCAST_RESPONSE",

                "status": "ERROR",

                "code": 401,

                "message": "Invalid or expired token.",

            })

            return

        if username not in configured_admins():

            self.reply({

                "type": "ADMIN_BROADCAST_RESPONSE",

                "status": "ERROR",

                "code": 403,

                "message": "Administrator privileges are required.",

            })

            return

        message = request.get("message")

        if not isinstance(message, str) or not message.strip():

            self.reply({

                "type": "ADMIN_BROADCAST_RESPONSE",

                "status": "ERROR",

                "code": 400,

                "message": "A non-empty announcement is required.",

            })

            return

        if len(message) > MAX_MESSAGE_LENGTH:

            self.reply({

                "type": "ADMIN_BROADCAST_RESPONSE",

                "status": "ERROR",

                "code": 413,

                "message": f"Announcement exceeds {MAX_MESSAGE_LENGTH} characters.",

            })

            return

        announcement = {

            "type": "ADMIN_ANNOUNCEMENT",

            "adminId": username,

            "message": message.strip(),

            "timestamp": datetime.now(timezone.utc).isoformat(),

        }

        database.log_admin_action(
            "broadcast", username, detail=message.strip()
        )

        with ACTIVE_CLIENTS_LOCK:

            active_clients = list(ACTIVE_CLIENTS.values())

        delivered = 0

        for client_socket, send_lock in active_clients:

            try:

                send_json(client_socket, send_lock, announcement)

                delivered += 1

            except (OSError, ConnectionError):

                continue

        self.reply({

            "type": "ADMIN_BROADCAST_RESPONSE",

            "status": "OK",

            "deliveredTo": delivered,

        })

    def handle_admin_moderation(self, request, request_type):

        """Kick a user or persist a server-wide ban, then disconnect them."""

        admin = self.authenticated_username(request)

        if admin is None:

            self.reply({

                "type": "ADMIN_MODERATION_RESPONSE",

                "status": "ERROR",

                "code": 401,

                "message": "Invalid or expired token.",

            })

            return

        if admin not in configured_admins():

            self.reply({

                "type": "ADMIN_MODERATION_RESPONSE",

                "status": "ERROR",

                "code": 403,

                "message": "Administrator privileges are required.",

            })

            return

        target_username = request.get("username")

        if (not isinstance(target_username, str)
                or not auth.USERNAME_PATTERN.fullmatch(target_username)):

            self.reply({

                "type": "ADMIN_MODERATION_RESPONSE",

                "status": "ERROR",

                "code": 400,

                "message": "A valid username is required.",

            })

            return

        target_user = database.get_user(target_username)

        if target_user is None:

            self.reply({

                "type": "ADMIN_MODERATION_RESPONSE",

                "status": "ERROR",

                "code": 404,

                "message": "User not found.",

            })

            return

        if target_user["username"].casefold() == admin.casefold():

            self.reply({

                "type": "ADMIN_MODERATION_RESPONSE",

                "status": "ERROR",

                "code": 400,

                "message": "An administrator cannot moderate their own account.",

            })

            return

        action = "ban" if request_type == "ADMIN_BAN" else "kick"

        reason = request.get("reason", "")

        if not isinstance(reason, str) or len(reason) > MAX_MESSAGE_LENGTH:

            self.reply({

                "type": "ADMIN_MODERATION_RESPONSE",

                "status": "ERROR",

                "code": 400,

                "message": "The moderation reason is invalid.",

            })

            return

        if action == "ban":

            database.ban_user(target_user["username"], admin)

        with ACTIVE_CLIENTS_LOCK:

            target_connection = ACTIVE_CLIENTS.get(target_user["username"])

        if action == "kick" and target_connection is None:

            self.reply({

                "type": "ADMIN_MODERATION_RESPONSE",

                "status": "ERROR",

                "code": 404,

                "message": "User is not connected.",

            })

            return

        database.log_admin_action(
            action, admin, target=target_user["username"], detail=reason
        )

        disconnected = False

        if target_connection is not None:

            target_socket, target_send_lock = target_connection

            try:

                send_json(target_socket, target_send_lock, {

                    "type": "ADMIN_MODERATION_NOTICE",

                    "action": action,

                    "adminId": admin,

                    "reason": reason,

                })

            except (OSError, ConnectionError):

                pass

            try:

                target_socket.shutdown(2)

            except OSError:

                pass

            try:

                target_socket.close()

                disconnected = True

            except OSError:

                pass

        self.reply({

            "type": "ADMIN_MODERATION_RESPONSE",

            "status": "OK",

            "action": action,

            "username": target_user["username"],

            "disconnected": disconnected,

        })

    def handle_logout(self, request):

        username = self.authenticated_username(request)

        if username is None:

            self.reply({

                "type": "ERROR",

                "code": 401,

                "message": "Invalid or expired token.",

            })

            return

        self.reply({

            "type": "LOGOUT_RESPONSE",

            "status": "OK",

        })

        self.cleanup()
        self.close_after_request = True

    def cleanup(self):

        """Remove this connection and invalidate its session."""

        if self.username is None:

            return

        username = self.username

        token = self.token

        removed_connection = False
        with ACTIVE_CLIENTS_LOCK:

            current = ACTIVE_CLIENTS.get(username)

            # Do not remove a newer connection belonging to the same user.

            if current is not None and current[0] is self.request:

                ACTIVE_CLIENTS.pop(username, None)
                removed_connection = True

                # Lock order ACTIVE_CLIENTS -> ROOMS is the only nesting used.
                self.left_rooms = leave_all_rooms(username)

                with HEARTBEAT_LOCK:
                    HEARTBEAT_LAST_SEEN.pop(username, None)
                    HEARTBEAT_TOKENS.pop(username, None)

        if token:

            database.delete_session(token)

        rooms_left, self.left_rooms = self.left_rooms, []

        with self.file_transfer_lock:
            transfer_ids = list(self.file_transfers)
            self.file_transfers.clear()
            for transfer_id in transfer_ids:
                release_file_transfer_id(transfer_id)

        if removed_connection:
            clear_typing_states(username)

        for room_key in rooms_left:

            broadcast_room_event(room_key, "LEFT", username)

        self.username = None

        self.token = None

def remove_stale_connection(username, client_socket, token=None):
    """Atomically remove one timed-out or failed connection from presence."""
    left_rooms = []
    with ACTIVE_CLIENTS_LOCK:
        current = ACTIVE_CLIENTS.get(username)
        if current is None or current[0] is not client_socket:
            return
        ACTIVE_CLIENTS.pop(username, None)
        left_rooms = leave_all_rooms(username)
    clear_typing_states(username)
    with HEARTBEAT_LOCK:
        HEARTBEAT_LAST_SEEN.pop(username, None)
        if token is None:
            token = HEARTBEAT_TOKENS.pop(username, None)
        else:
            HEARTBEAT_TOKENS.pop(username, None)
    if token:
        database.delete_session(token)
    for room_key in left_rooms:
        broadcast_room_event(room_key, "LEFT", username)
    try:
        client_socket.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        client_socket.close()
    except OSError:
        pass


class ChatServer(socketserver.ThreadingTCPServer):

    """TCP server that handles clients in separate threads."""

    allow_reuse_address = True

    daemon_threads = True

    def __init__(self, server_address, request_handler_class):
        super().__init__(server_address, request_handler_class)
        self.ssl_context = None
        cert_file = os.environ.get("CHAT_TLS_CERT_FILE")
        key_file = os.environ.get("CHAT_TLS_KEY_FILE")
        if cert_file or key_file:
            if not cert_file or not key_file:
                raise ValueError("CHAT_TLS_CERT_FILE and CHAT_TLS_KEY_FILE must be set together")
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
            self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.stop_heartbeat = threading.Event()
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_monitor, name="chat-heartbeat-monitor", daemon=True
        )
        self.heartbeat_thread.start()
        self.typing_expiry_thread = threading.Thread(
            target=self._typing_expiry_monitor,
            name="chat-typing-expiry-monitor",
            daemon=True,
        )
        self.typing_expiry_thread.start()

    def get_request(self):
        """Accept a socket and upgrade it to TLS when certificate settings are present."""
        client_socket, client_address = super().get_request()
        if self.ssl_context is not None:
            try:
                client_socket = self.ssl_context.wrap_socket(
                    client_socket, server_side=True
                )
            except (ssl.SSLError, OSError):
                client_socket.close()
                raise
        return client_socket, client_address

    def _heartbeat_monitor(self):
        """Ping logged-in clients and remove silent or unresponsive presence."""
        while not self.stop_heartbeat.wait(min(HEARTBEAT_INTERVAL_SECONDS, 1.0)):
            expire_stale_file_transfers()
            now = datetime.now(timezone.utc).timestamp()
            with ACTIVE_CLIENTS_LOCK:
                clients = list(ACTIVE_CLIENTS.items())
            for username, (client_socket, send_lock) in clients:
                with HEARTBEAT_LOCK:
                    last_seen = HEARTBEAT_LAST_SEEN.get(username, now)
                if now - last_seen >= HEARTBEAT_TIMEOUT_SECONDS:
                    remove_stale_connection(username, client_socket)
                    continue
                try:
                    send_json(client_socket, send_lock, {"type": "PING"})
                except (OSError, ConnectionError):
                    remove_stale_connection(username, client_socket)

    def _typing_expiry_monitor(self):
        """Clear abandoned typing indicators promptly."""
        while not self.stop_heartbeat.wait(0.1):
            expire_stale_typing_states()

    def shutdown(self):
        self.stop_heartbeat.set()
        super().shutdown()
        self.heartbeat_thread.join(timeout=1)
        self.typing_expiry_thread.join(timeout=1)

def main():

    database.init_db()

    try:

        with ChatServer((HOST, PORT), ChatHandler) as server:

            print(f"Chat server listening on {HOST}:{PORT}")

            if server.ssl_context is None:
                print("WARNING: TLS is not enabled; set CHAT_TLS_CERT_FILE and CHAT_TLS_KEY_FILE.")
            else:
                print("TLS 1.2+ enabled for socket communication.")

            server.serve_forever()

    except OSError as error:

        print(f"Could not start the server: {error}")

        print("Check whether another application is using port 5000.")

if __name__ == "__main__":

    main()
