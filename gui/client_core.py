"""Thread-safe client layer for the existing newline-delimited JSON protocol.

All server events are placed on :attr:`ClientCore.events`. Network reads happen
on one background thread; callers such as Tkinter applications should drain the
queue from their own event loop.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import socket
import ssl
import threading
import time
import uuid
from pathlib import Path
from typing import Any


MAX_FILE_SIZE = 1024 * 1024
FILE_CHUNK_SIZE = 8_192
MAX_SERVER_LINE_BYTES = 4_194_304
MAX_INCOMING_FILE_TRANSFERS = 8
DOWNLOAD_DIR = Path("received_files")
FILE_RESPONSE_TIMEOUT_SECONDS = 10.0
_FILE_REPLY_TYPES = {"FILE_READY", "FILE_CHUNK_ACK", "FILE_SENT", "FILE_ERROR"}


class ClientCore:
    """Communicate with ``server.py`` without blocking the GUI thread.

    Connection events use ``{"_event": "connection", "status": ...}``.
    Other local errors use ``{"_event": "client_error", ...}``. Ordinary
    server protocol messages are forwarded unchanged as dictionaries with a
    ``type``. Incoming file frames are validated and reconstructed on the
    reader thread, then reported as ``file_transfer`` local events.
    Public request methods send asynchronously; their responses arrive in
    :attr:`events`.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        *,
        connect_timeout: float = 5.0,
        tls_enabled: bool | None = None,
        ca_file: str | os.PathLike[str] | None = None,
    ) -> None:
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        if tls_enabled is None:
            tls_enabled = os.environ.get(
                "CHAT_TLS_ENABLED", "0"
            ).lower() in {"1", "true", "yes", "on"}
        self.tls_enabled = tls_enabled
        self.ca_file = ca_file or os.environ.get("CHAT_TLS_CA_FILE")

        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._state_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._file_workers_lock = threading.Lock()
        self._file_workers: set[threading.Thread] = set()
        self._file_send_lock = threading.Lock()
        self._file_response_lock = threading.Lock()
        self._file_response_queues: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._socket: socket.socket | ssl.SSLSocket | None = None
        self._state = "disconnected"
        self._username: str | None = None
        self._token: str | None = None
        self._generation = 0
        self._stop_event = threading.Event()
        self._connect_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None

    @property
    def connection_state(self) -> str:
        """Return ``disconnected``, ``connecting``, ``connected`` or ``closing``."""
        with self._state_lock:
            return self._state

    @property
    def is_connected(self) -> bool:
        return self.connection_state == "connected"

    @property
    def is_authenticated(self) -> bool:
        with self._state_lock:
            return self._state == "connected" and self._token is not None

    @property
    def username(self) -> str | None:
        with self._state_lock:
            return self._username

    def connect(self) -> bool:
        """Begin a connection attempt on a worker thread.

        Returns ``False`` if a connection is already active or being attempted.
        Completion and failures are reported through :attr:`events`.
        """
        with self._state_lock:
            if self._state != "disconnected":
                return False
            self._generation += 1
            generation = self._generation
            self._stop_event = threading.Event()
            stop_event = self._stop_event
            self._state = "connecting"
            worker = threading.Thread(
                target=self._connect_worker,
                args=(generation, stop_event),
                name="chat-client-connect",
                daemon=True,
            )
            self._connect_thread = worker
        self.events.put({"_event": "connection", "status": "connecting"})
        worker.start()
        return True

    def _connect_worker(
        self, generation: int, stop_event: threading.Event
    ) -> None:
        client_socket: socket.socket | ssl.SSLSocket | None = None
        try:
            client_socket = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout
            )
            if self.tls_enabled:
                context = ssl.create_default_context()
                if self.ca_file:
                    context.load_verify_locations(cafile=self.ca_file)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                client_socket = context.wrap_socket(
                    client_socket, server_hostname=self.host
                )
            client_socket.settimeout(None)
        except (OSError, ssl.SSLError, ValueError) as error:
            if client_socket is not None:
                client_socket.close()
            with self._state_lock:
                current = generation == self._generation
                if current:
                    self._state = "disconnected"
                    self._connect_thread = None
            if current and not stop_event.is_set():
                self.events.put({
                    "_event": "connection",
                    "status": "error",
                    "message": str(error),
                })
            return

        with self._state_lock:
            if generation != self._generation or stop_event.is_set():
                client_socket.close()
                return
            self._socket = client_socket
            self._state = "connected"
            self._connect_thread = None
            reader = threading.Thread(
                target=self._read_messages,
                args=(client_socket, generation, stop_event),
                name="chat-client-reader",
                daemon=True,
            )
            self._reader_thread = reader
        self.events.put({"_event": "connection", "status": "connected"})
        reader.start()

    def _read_messages(
        self,
        client_socket: socket.socket | ssl.SSLSocket,
        generation: int,
        stop_event: threading.Event,
    ) -> None:
        try:
            incoming_files: dict[str, dict[str, Any]] = {}
            with client_socket.makefile("rb") as stream:
                while not stop_event.is_set():
                    line = stream.readline(MAX_SERVER_LINE_BYTES + 1)
                    if not line:
                        break
                    if len(line) > MAX_SERVER_LINE_BYTES or not line.endswith(b"\n"):
                        self.events.put({
                            "_event": "client_error",
                            "message": "Server response was oversized or improperly framed.",
                        })
                        break
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError) as error:
                        self.events.put({
                            "_event": "client_error",
                            "message": f"Invalid server response: {error}",
                        })
                        continue
                    if not isinstance(message, dict):
                        self.events.put({
                            "_event": "client_error",
                            "message": "Server response was not a JSON object.",
                        })
                        continue
                    with self._state_lock:
                        if (
                            generation != self._generation
                            or self._socket is not client_socket
                        ):
                            break
                    self._handle_server_message(
                        message, client_socket, generation, stop_event,
                        incoming_files,
                    )
        except (OSError, ConnectionError, ValueError) as error:
            if not stop_event.is_set():
                self.events.put({
                    "_event": "client_error",
                    "message": f"Connection read failed: {error}",
                })
        finally:
            self._finish_connection(client_socket, generation, stop_event)

    def _handle_server_message(
        self,
        message: dict[str, Any],
        client_socket: socket.socket | ssl.SSLSocket,
        generation: int,
        stop_event: threading.Event,
        incoming_files: dict[str, dict[str, Any]],
    ) -> None:
        kind = message.get("type")
        if kind == "PING":
            try:
                self._send_payload(
                    {"type": "PONG"},
                    client_socket=client_socket,
                    generation=generation,
                    stop_event=stop_event,
                )
            except (OSError, ConnectionError, RuntimeError) as error:
                self.events.put({
                    "_event": "client_error",
                    "message": f"Could not answer server heartbeat: {error}",
                })
            return

        if kind in {
            "FILE_RECEIVE_START", "FILE_RECEIVE_CHUNK", "FILE_RECEIVE_END"
        }:
            self._handle_received_file(message, incoming_files)
            return

        with self._state_lock:
            if generation != self._generation or self._socket is not client_socket:
                return
            if kind == "LOGIN_RESPONSE":
                if message.get("status") == "OK":
                    self._username = message.get("userId")
                    self._token = message.get("token")
                else:
                    self._username = None
                    self._token = None
            elif kind == "LOGOUT_RESPONSE":
                self._username = None
                self._token = None

        if kind in _FILE_REPLY_TYPES:
            transfer_id = message.get("transferId")
            with self._file_response_lock:
                if isinstance(transfer_id, str):
                    target = self._file_response_queues.get(transfer_id)
                    if target is not None:
                        target.put(message)
                elif kind == "FILE_ERROR":
                    for target in self._file_response_queues.values():
                        target.put(message)
        self.events.put(message)

    def _handle_received_file(
        self,
        message: dict[str, Any],
        incoming_files: dict[str, dict[str, Any]],
    ) -> None:
        """Validate, reconstruct and save one existing-protocol file transfer."""
        kind = message.get("type")
        transfer_id = message.get("transferId")
        if not isinstance(transfer_id, str) or not transfer_id:
            self._emit_file_error(transfer_id, "Invalid file transfer ID.")
            return

        if kind == "FILE_RECEIVE_START":
            filename = message.get("filename")
            size = message.get("size")
            checksum = message.get("sha256")
            if (
                not isinstance(filename, str)
                or not filename
                or filename in {".", ".."}
                or Path(filename).name != filename
                or "/" in filename
                or "\\" in filename
                or ":" in filename
                or any(ord(char) < 32 for char in filename)
                or not isinstance(size, int)
                or isinstance(size, bool)
                or not 0 <= size <= MAX_FILE_SIZE
                or not isinstance(checksum, str)
                or len(checksum) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in checksum)
            ):
                self._emit_file_error(transfer_id, "Invalid file metadata.")
                return
            if (
                transfer_id not in incoming_files
                and len(incoming_files) >= MAX_INCOMING_FILE_TRANSFERS
            ):
                self._emit_file_error(
                    transfer_id, "Too many concurrent incoming file transfers."
                )
                return
            incoming_files[transfer_id] = {
                "filename": filename,
                "size": size,
                "sha256": checksum.lower(),
                "fromUser": message.get("fromUser", "unknown"),
                "data": bytearray(),
            }
            self.events.put({
                "_event": "file_transfer",
                "status": "receiving",
                "transferId": transfer_id,
                "filename": filename,
            })
            return

        transfer = incoming_files.get(transfer_id)
        if transfer is None:
            return
        if kind == "FILE_RECEIVE_CHUNK":
            try:
                encoded = message.get("data")
                if not isinstance(encoded, str):
                    raise ValueError("File chunk was not Base64 text.")
                chunk = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error) as error:
                incoming_files.pop(transfer_id, None)
                self._emit_file_error(transfer_id, str(error))
                return
            if (
                len(chunk) > FILE_CHUNK_SIZE
                or len(transfer["data"]) + len(chunk) > transfer["size"]
            ):
                incoming_files.pop(transfer_id, None)
                self._emit_file_error(
                    transfer_id, "Incoming file exceeded its declared size."
                )
                return
            transfer["data"].extend(chunk)
            return

        incoming_files.pop(transfer_id, None)
        data = bytes(transfer["data"])
        if (
            len(data) != transfer["size"]
            or hashlib.sha256(data).hexdigest() != transfer["sha256"]
        ):
            self._emit_file_error(
                transfer_id, "Incoming file failed size or SHA-256 verification."
            )
            return
        try:
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            destination = DOWNLOAD_DIR / transfer["filename"]
            if destination.exists():
                destination = DOWNLOAD_DIR / (
                    f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}"
                )
            destination.write_bytes(data)
        except OSError as error:
            self._emit_file_error(
                transfer_id, f"Could not save incoming file: {error}"
            )
            return
        self.events.put({
            "_event": "file_transfer",
            "status": "received",
            "transferId": transfer_id,
            "path": str(destination),
            "filename": transfer["filename"],
            "fromUser": transfer["fromUser"],
            "size": len(data),
            "sha256": transfer["sha256"],
        })

    def _emit_file_error(self, transfer_id: Any, message: str) -> None:
        self.events.put({
            "_event": "file_transfer",
            "status": "error",
            "transferId": transfer_id,
            "message": message,
        })

    def _finish_connection(
        self,
        client_socket: socket.socket | ssl.SSLSocket,
        generation: int,
        stop_event: threading.Event,
    ) -> None:
        try:
            client_socket.close()
        except OSError:
            pass
        with self._state_lock:
            if generation != self._generation or self._socket is not client_socket:
                return
            self._socket = None
            self._state = "disconnected"
            self._username = None
            self._token = None
            self._reader_thread = None
            stop_event.set()
        self.events.put({"_event": "connection", "status": "disconnected"})

    def disconnect(self) -> None:
        """Close the socket and stop the reader without waiting on GUI reads."""
        with self._state_lock:
            was_active = self._state != "disconnected" or self._socket is not None
            if was_active:
                self._state = "closing"
                self._generation += 1
            client_socket = self._socket
            reader = self._reader_thread
            connector = self._connect_thread
            stop_event = self._stop_event
            with self._file_workers_lock:
                file_workers = tuple(self._file_workers)
            self._socket = None
            self._username = None
            self._token = None
            stop_event.set()

        if client_socket is not None:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client_socket.close()
            except OSError:
                pass
        with self._state_lock:
            self._state = "disconnected"
        if was_active:
            self.events.put({"_event": "connection", "status": "disconnected"})
        current_thread = threading.current_thread()
        for worker in (reader, connector, *file_workers):
            if worker is not None and worker is not current_thread:
                worker.join(timeout=1.0)

    close = disconnect

    def send_request(
        self, request: dict[str, Any], *, authenticated: bool = False
    ) -> None:
        """Send a protocol request; attach the active token when requested."""
        if not isinstance(request, dict):
            raise TypeError("request must be a dictionary")
        payload = dict(request)
        if authenticated:
            with self._state_lock:
                token = self._token
            if token is None:
                raise RuntimeError("This request requires an authenticated session.")
            payload["token"] = token
        self._send_payload(payload)

    def _send_payload(
        self,
        payload: dict[str, Any],
        *,
        client_socket: socket.socket | ssl.SSLSocket | None = None,
        generation: int | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        with self._state_lock:
            target = self._socket if client_socket is None else client_socket
            current_generation = self._generation
            current_stop_event = self._stop_event
            if (
                target is None
                or self._state != "connected"
                or self._socket is not target
                or (generation is not None and generation != current_generation)
            ):
                raise ConnectionError("Not connected to the chat server.")
        data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        try:
            with self._send_lock:
                target.sendall(data)
        except (OSError, ConnectionError):
            self._finish_connection(
                target,
                current_generation,
                stop_event or current_stop_event,
            )
            raise

    def register(self, username: str, password: str) -> None:
        self.send_request({
            "type": "REGISTER_REQUEST",
            "username": username,
            "password": password,
        })

    def login(self, username: str, password: str) -> None:
        self.send_request({
            "type": "LOGIN_REQUEST",
            "username": username,
            "password": password,
        })

    def send_private_message(self, recipient: str, content: str) -> None:
        self.send_request({
            "type": "SEND_MESSAGE",
            "toUser": recipient,
            "content": content,
        }, authenticated=True)

    def send_room_message(self, room: str, content: str) -> None:
        self.send_request({
            "type": "SEND_MESSAGE",
            "roomId": room,
            "content": content,
        }, authenticated=True)

    def send_typing(
        self, destination: str, is_typing: bool, *, room: bool = False
    ) -> None:
        self.send_request({
            "type": "TYPING",
            "roomId" if room else "toUser": destination,
            "isTyping": is_typing,
        }, authenticated=True)

    def create_room(self, room: str) -> None:
        self._room_request("CREATE_ROOM", room)

    def join_room(self, room: str) -> None:
        self._room_request("JOIN_ROOM", room)

    def leave_room(self, room: str) -> None:
        self._room_request("LEAVE_ROOM", room)

    def _room_request(self, kind: str, room: str) -> None:
        self.send_request({"type": kind, "room": room}, authenticated=True)

    def list_rooms(self) -> None:
        self.send_request({"type": "LIST_ROOMS"}, authenticated=True)

    def list_users(self, room: str | None = None) -> None:
        request: dict[str, Any] = {"type": "LIST_USERS"}
        if room is not None:
            request["room"] = room
        self.send_request(request, authenticated=True)

    def request_history(
        self, *, limit: int = 50, before_id: int | None = None
    ) -> None:
        request: dict[str, Any] = {"type": "HISTORY_REQUEST", "limit": limit}
        if before_id is not None:
            request["beforeId"] = before_id
        self.send_request(request, authenticated=True)

    def logout(self) -> None:
        self.send_request({"type": "LOGOUT_REQUEST"}, authenticated=True)

    def send_file(self, destination: str, filepath: str | os.PathLike[str]) -> str:
        """Start a background file upload to a user or a ``#room``."""
        if not isinstance(destination, str):
            raise TypeError("destination must be a username or #room string")
        with self._state_lock:
            token = self._token
            client_socket = self._socket
            generation = self._generation
            stop_event = self._stop_event
            if token is None or client_socket is None:
                raise RuntimeError("File transfer requires an authenticated session.")
            transfer_id = str(uuid.uuid4())
            worker = threading.Thread(
                target=self._send_file_worker,
                args=(
                    transfer_id, token, destination, Path(filepath).expanduser(),
                    client_socket, generation, stop_event,
                ),
                name=f"chat-file-send-{transfer_id[:8]}",
                daemon=True,
            )
            with self._file_workers_lock:
                self._file_workers.add(worker)
                try:
                    worker.start()
                except RuntimeError:
                    self._file_workers.remove(worker)
                    raise
        return transfer_id

    def _send_file_worker(
        self,
        transfer_id: str,
        token: str,
        destination: str,
        path: Path,
        client_socket: socket.socket | ssl.SSLSocket,
        generation: int,
        stop_event: threading.Event,
    ) -> None:
        with self._file_send_lock:
            self._send_file_transaction(
                transfer_id,
                token,
                destination,
                path,
                client_socket,
                generation,
                stop_event,
            )

    def _send_file_transaction(
        self,
        transfer_id: str,
        token: str,
        destination: str,
        path: Path,
        client_socket: socket.socket | ssl.SSLSocket,
        generation: int,
        stop_event: threading.Event,
    ) -> None:
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._file_response_lock:
            self._file_response_queues[transfer_id] = response_queue
        try:
            if not path.is_file():
                raise OSError(f"File does not exist: {path}")
            with path.open("rb") as source:
                data = source.read(MAX_FILE_SIZE + 1)
            if len(data) > MAX_FILE_SIZE:
                raise ValueError(f"File exceeds the {MAX_FILE_SIZE}-byte limit.")
            target = destination.strip()
            if target.startswith("#"):
                destination_field = {"roomId": target[1:]}
            else:
                destination_field = {"toUser": target}
            if not next(iter(destination_field.values())):
                raise ValueError("A recipient username or #room is required.")
            start = {
                "type": "FILE_START",
                "token": token,
                **destination_field,
                "filename": path.name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "transferId": transfer_id,
            }
            self._send_payload(
                start, client_socket=client_socket, generation=generation,
                stop_event=stop_event,
            )
            response = self._wait_file_response(
                response_queue, {"FILE_READY"}, transfer_id, stop_event
            )
            if response.get("type") == "FILE_ERROR":
                raise RuntimeError(response.get("message", "File transfer rejected."))

            chunks = [
                data[offset:offset + FILE_CHUNK_SIZE]
                for offset in range(0, len(data), FILE_CHUNK_SIZE)
            ] or [b""]
            for index, chunk in enumerate(chunks):
                final = index == len(chunks) - 1
                self._send_payload(
                    {
                        "type": "FILE_CHUNK",
                        "token": token,
                        "transferId": transfer_id,
                        "data": base64.b64encode(chunk).decode("ascii"),
                        "final": final,
                    },
                    client_socket=client_socket,
                    generation=generation,
                    stop_event=stop_event,
                )
                expected = {"FILE_SENT"} if final else {"FILE_CHUNK_ACK"}
                response = self._wait_file_response(
                    response_queue, expected, transfer_id, stop_event
                )
                if response.get("type") == "FILE_ERROR":
                    raise RuntimeError(response.get("message", "File transfer failed."))
            self.events.put({
                "_event": "file_transfer",
                "status": "sent",
                "transferId": transfer_id,
                "path": str(path),
            })
        except (OSError, ValueError, RuntimeError, ConnectionError) as error:
            self.events.put({
                "_event": "file_transfer",
                "status": "error",
                "transferId": transfer_id,
                "path": str(path),
                "message": str(error),
            })
        finally:
            with self._file_response_lock:
                self._file_response_queues.pop(transfer_id, None)
            with self._file_workers_lock:
                self._file_workers.discard(threading.current_thread())

    def _wait_file_response(
        self,
        responses: queue.Queue[dict[str, Any]],
        expected: set[str],
        transfer_id: str,
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + FILE_RESPONSE_TIMEOUT_SECONDS
        while not stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for the file-transfer response.")
            try:
                response = responses.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if response.get("type") == "FILE_ERROR":
                raise RuntimeError(response.get("message", "File transfer failed."))
            if response.get("transferId") != transfer_id:
                continue
            if response.get("type") in expected:
                return response
        raise ConnectionError("Connection closed during file transfer.")
