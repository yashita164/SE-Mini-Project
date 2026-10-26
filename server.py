

"""Threaded TCP server for the Team 5 chat application.

Protocol: newline-delimited JSON over TCP.

Development configuration: localhost, port 5000, no TLS.

"""

import json

import socketserver

import threading

from datetime import datetime, timezone

import auth

import database

HOST = "127.0.0.1"

PORT = 5000

MAX_REQUEST_BYTES = 16_384

MAX_MESSAGE_LENGTH = 4_000

# username -> (socket, socket-send lock)

ACTIVE_CLIENTS = {}

ACTIVE_CLIENTS_LOCK = threading.Lock()

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

class ChatHandler(socketserver.StreamRequestHandler):

    """Handle requests from one connected client."""

    def setup(self):

        super().setup()

        self.send_lock = threading.Lock()

        self.username = None

        self.token = None

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

                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):

                    self.reply({

                        "type": "ERROR",

                        "code": 400,

                        "message": "Invalid JSON request.",

                    })

                    continue

                try:

                    self.process_request(request)

                except (OSError, RuntimeError):

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

        elif request_type == "SEND_MESSAGE":

            self.handle_send_message(request)

        elif request_type == "HISTORY_REQUEST":

            self.handle_history(request)

        elif request_type == "TYPING":

            self.handle_typing(request)

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

        if self.username is not None:

            self.reply({

                "type": "LOGIN_RESPONSE",

                "status": "ERROR",

                "code": 409,

                "message": "This connection is already authenticated.",

            })

            return

        result = auth.login(

            request.get("username"),

            request.get("password"),

        )

        if result is None:

            self.reply({

                "type": "LOGIN_RESPONSE",

                "status": "ERROR",

                "code": 401,

                "message": "Invalid credentials.",

            })

            return

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
        """Forward a user's typing state to the intended online recipient."""
        sender = self.authenticated_username(request)

        if sender is None:
            self.reply({
                "type": "TYPING_RESPONSE",
                "status": "ERROR",
                "code": 401,
                "message": "Invalid or expired token.",
            })
            return

        recipient = request.get("toUser")
        is_typing = request.get("isTyping")

        if not isinstance(recipient, str) or not recipient.strip():
            self.reply({
                "type": "TYPING_RESPONSE",
                "status": "ERROR",
                "code": 400,
                "message": "A recipient username is required.",
            })
            return

        if not isinstance(is_typing, bool):
            self.reply({
                "type": "TYPING_RESPONSE",
                "status": "ERROR",
                "code": 400,
                "message": "isTyping must be a boolean.",
            })
            return

        recipient_user = database.get_user(recipient.strip())
        if recipient_user is None:
            self.reply({
                "type": "TYPING_RESPONSE",
                "status": "ERROR",
                "code": 404,
                "message": "Recipient not found.",
            })
            return

        recipient = recipient_user["username"]

        # Do not send a typing event back to the sender or to unrelated users.
        if recipient == sender:
            self.reply({
                "type": "TYPING_RESPONSE",
                "status": "OK",
            })
            return

        with ACTIVE_CLIENTS_LOCK:
            target = ACTIVE_CLIENTS.get(recipient)

        if target is not None:
            target_socket, target_lock = target
            try:
                send_json(target_socket, target_lock, {
                    "type": "TYPING_INDICATOR",
                    "fromUser": sender,
                    "isTyping": is_typing,
                })
            except (OSError, ConnectionError):
                # A disconnected recipient should not prevent the sender response.
                pass

        self.reply({
            "type": "TYPING_RESPONSE",
            "status": "OK",
        })

    def handle_send_message(self, request):

        sender = self.authenticated_username(request)

        if sender is None:

            self.reply({

                "type": "MESSAGE_ERROR",

                "code": 401,

                "message": "Invalid or expired token.",

            })

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

        messages = database.get_messages_for(username)

        self.reply({

            "type": "HISTORY_RESPONSE",

            "messages": messages,

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

    def cleanup(self):

        """Remove this connection and invalidate its session."""

        if self.username is None:

            return

        username = self.username

        token = self.token

        with ACTIVE_CLIENTS_LOCK:

            current = ACTIVE_CLIENTS.get(username)

            # Do not remove a newer connection belonging to the same user.

            if current is not None and current[0] is self.request:

                ACTIVE_CLIENTS.pop(username, None)

        if token:

            database.delete_session(token)

        self.username = None

        self.token = None

class ChatServer(socketserver.ThreadingTCPServer):

    """TCP server that handles clients in separate threads."""

    allow_reuse_address = True

    daemon_threads = True

def main():

    database.init_db()

    try:

        with ChatServer((HOST, PORT), ChatHandler) as server:

            print(f"Chat server listening on {HOST}:{PORT}")

            print("Development only: localhost binding; TLS is not enabled.")

            server.serve_forever()

    except OSError as error:

        print(f"Could not start the server: {error}")

        print("Check whether another application is using port 5000.")

if __name__ == "__main__":

    main()
