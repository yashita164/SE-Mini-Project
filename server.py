"""Threaded TCP server for the Team 5 chat application.

Protocol: newline-delimited JSON over TCP.

Development configuration: localhost, port 5000, no TLS.

"""

import base64
import hashlib
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
MAX_FILE_SIZE = 1024 * 1024  # 1 MiB; documented default for CHAT-F-030
FILE_CHUNK_SIZE = 8_192  # Base64 JSON request remains below MAX_REQUEST_BYTES

# username -> (socket, socket-send lock)

ACTIVE_CLIENTS = {}

ACTIVE_CLIENTS_LOCK = threading.Lock()

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
        self.file_transfers = {}

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

        elif request_type == "FILE_START":

            self.handle_file_start(request)

        elif request_type == "FILE_CHUNK":

            self.handle_file_chunk(request)

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
        filename = request.get("filename")
        size = request.get("size")
        checksum = request.get("sha256")
        transfer_id = request.get("transferId")

        if not isinstance(recipient, str) or not recipient.strip():
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Recipient is required."})
            return
        if (not isinstance(filename, str) or not filename.strip()
                or filename in {".", ".."} or "/" in filename or "\\" in filename):
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid filename."})
            return
        if (not isinstance(size, int) or isinstance(size, bool)
                or size < 0 or size > MAX_FILE_SIZE):
            self.reply({"type": "FILE_ERROR", "code": 413,
                        "message": f"File exceeds the configured limit of {MAX_FILE_SIZE} bytes."})
            return
        if (not isinstance(checksum, str) or len(checksum) != 64
                or any(ch not in "0123456789abcdefABCDEF" for ch in checksum)):
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid SHA-256 checksum."})
            return
        if not isinstance(transfer_id, str) or not transfer_id or len(transfer_id) > 64:
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid transfer ID."})
            return
        if transfer_id in self.file_transfers:
            self.reply({"type": "FILE_ERROR", "code": 409,
                        "message": "Transfer ID already exists."})
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

        self.file_transfers[transfer_id] = {
            "sender": sender,
            "recipient": recipient,
            "filename": filename,
            "size": size,
            "sha256": checksum.lower(),
            "data": bytearray(),
        }
        self.reply({"type": "FILE_READY", "transferId": transfer_id})

    def handle_file_chunk(self, request):
        """Collect chunks, verify SHA-256, and forward the intact file."""
        sender = self.authenticated_username(request)
        if sender is None:
            self.reply({"type": "FILE_ERROR", "code": 401,
                        "message": "Authentication required."})
            return

        transfer_id = request.get("transferId")
        transfer = self.file_transfers.get(transfer_id)
        encoded = request.get("data")
        final = request.get("final")
        if transfer is None or transfer["sender"] != sender:
            self.reply({"type": "FILE_ERROR", "code": 404,
                        "message": "Transfer not found."})
            return
        if not isinstance(encoded, str) or not isinstance(final, bool):
            self.file_transfers.pop(transfer_id, None)
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid file chunk."})
            return
        try:
            chunk = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            self.file_transfers.pop(transfer_id, None)
            self.reply({"type": "FILE_ERROR", "code": 400,
                        "message": "Invalid Base64 chunk."})
            return
        if len(chunk) > FILE_CHUNK_SIZE:
            self.file_transfers.pop(transfer_id, None)
            self.reply({"type": "FILE_ERROR", "code": 413,
                        "message": "Chunk exceeds the configured limit."})
            return

        transfer["data"].extend(chunk)
        if len(transfer["data"]) > transfer["size"]:
            self.file_transfers.pop(transfer_id, None)
            self.reply({"type": "FILE_ERROR", "code": 413,
                        "message": "Received more data than declared."})
            return
        if not final:
            self.reply({"type": "FILE_CHUNK_ACK", "transferId": transfer_id})
            return

        self.file_transfers.pop(transfer_id, None)
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
            target = ACTIVE_CLIENTS.get(transfer["recipient"])
        if target is None:
            self.reply({"type": "FILE_ERROR", "code": 404,
                        "message": "Recipient went offline."})
            return
        target_socket, target_lock = target
        try:
            with target_lock:
                def send_event(payload):
                    data = (json.dumps(payload, ensure_ascii=False,
                                       separators=(",", ":")) + "\n").encode("utf-8")
                    target_socket.sendall(data)

                send_event({"type": "FILE_RECEIVE_START", "transferId": transfer_id,
                            "fromUser": sender, "filename": transfer["filename"],
                            "size": len(file_data), "sha256": checksum})
                # Even empty files are represented by START and END, with no chunks.
                for offset in range(0, len(file_data), FILE_CHUNK_SIZE):
                    send_event({"type": "FILE_RECEIVE_CHUNK", "transferId": transfer_id,
                                "data": base64.b64encode(
                                    file_data[offset:offset + FILE_CHUNK_SIZE]
                                ).decode("ascii")})
                send_event({"type": "FILE_RECEIVE_END", "transferId": transfer_id})
        except (OSError, ConnectionError):
            self.reply({"type": "FILE_ERROR", "code": 503,
                        "message": "File delivery failed."})
            return

        self.reply({"type": "FILE_SENT", "transferId": transfer_id,
                    "filename": transfer["filename"], "size": len(file_data),
                    "sha256": checksum})

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
