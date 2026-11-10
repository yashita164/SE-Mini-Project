"""Room chat helpers for the GUI layer.

The backend remains the same: the GUI creates the same JSON requests the console
client uses, then displays the responses and push events produced by the server.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Optional

import client

try:  # pragma: no cover - GUI is optional in headless CI.
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None
    ttk = None


class RoomChatController:
    """Thin controller around the existing room-message protocol."""

    def __init__(self, sock=None, send_lock=None, responses=None, stop_event=None, token=None):
        self.sock = sock
        self.send_lock = send_lock
        self.responses = responses
        self.stop_event = stop_event
        self.token = token
        self.rooms: List[dict[str, Any]] = []
        self.message_log: List[str] = []
        self.event_handlers: list[Callable[[dict[str, Any]], None]] = []

    def add_event_handler(self, callback: Callable[[dict[str, Any]], None]) -> None:
        if callable(callback):
            self.event_handlers.append(callback)

    def _notify(self, message: dict[str, Any]) -> None:
        for callback in list(self.event_handlers):
            try:
                callback(message)
            except Exception:  # pragma: no cover
                pass

    def set_token(self, token: str | None) -> None:
        self.token = token

    def refresh_rooms(self):
        """List available rooms from the server."""
        if self.sock is None or self.token is None:
            return []
        client.send_json(self.sock, self.send_lock, {"type": "LIST_ROOMS", "token": self.token})
        response = client.wait_for_response(self.responses, "ROOM_LIST", self.stop_event, timeout=10)
        if response is None:
            return []
        rooms = response.get("rooms", [])
        self.rooms = list(rooms)
        self._notify({"type": "ROOMS_UPDATED", "rooms": self.rooms})
        return self.rooms

    def create_room(self, room_name: str):
        if self.sock is None or self.token is None:
            return {"type": "ROOM_RESPONSE", "status": "ERROR", "code": 401, "message": "Not authenticated."}
        client.send_json(self.sock, self.send_lock, {"type": "CREATE_ROOM", "token": self.token, "room": room_name})
        response = client.wait_for_response(self.responses, "ROOM_RESPONSE", self.stop_event, timeout=10)
        self._notify(response or {"type": "ROOM_RESPONSE", "status": "ERROR", "message": "No response"})
        return response

    def join_room(self, room_name: str):
        if self.sock is None or self.token is None:
            return {"type": "ROOM_RESPONSE", "status": "ERROR", "code": 401, "message": "Not authenticated."}
        client.send_json(self.sock, self.send_lock, {"type": "JOIN_ROOM", "token": self.token, "room": room_name})
        response = client.wait_for_response(self.responses, "ROOM_RESPONSE", self.stop_event, timeout=10)
        self._notify(response or {"type": "ROOM_RESPONSE", "status": "ERROR", "message": "No response"})
        return response

    def leave_room(self, room_name: str):
        if self.sock is None or self.token is None:
            return {"type": "ROOM_RESPONSE", "status": "ERROR", "code": 401, "message": "Not authenticated."}
        client.send_json(self.sock, self.send_lock, {"type": "LEAVE_ROOM", "token": self.token, "room": room_name})
        response = client.wait_for_response(self.responses, "ROOM_RESPONSE", self.stop_event, timeout=10)
        self._notify(response or {"type": "ROOM_RESPONSE", "status": "ERROR", "message": "No response"})
        return response

    def list_users(self, room_name: str | None = None):
        if self.sock is None or self.token is None:
            return {"type": "USER_LIST", "users": []}
        payload = {"type": "LIST_USERS", "token": self.token}
        if room_name:
            payload["room"] = room_name
        client.send_json(self.sock, self.send_lock, payload)
        response = client.wait_for_response(self.responses, "USER_LIST", self.stop_event, timeout=10)
        if response is None:
            return {"type": "USER_LIST", "users": []}
        return response

    def send_room_message(self, room_name: str, content: str):
        if self.sock is None or self.token is None:
            return {"type": "MESSAGE_ERROR", "code": 401, "message": "Not authenticated."}
        if not room_name:
            return {"type": "MESSAGE_ERROR", "code": 400, "message": "Room is required."}
        if not isinstance(content, str) or not content.strip():
            return {"type": "MESSAGE_ERROR", "code": 400, "message": "Message content is required."}
        client.send_json(self.sock, self.send_lock, {
            "type": "SEND_MESSAGE",
            "token": self.token,
            "roomId": room_name,
            "content": content,
        })
        response = client.wait_for_message_result(self.responses, self.stop_event, timeout=10)
        self._notify(response or {"type": "MESSAGE_ERROR", "message": "No response"})
        return response or {"type": "MESSAGE_ERROR", "message": "No response"}

    def handle_event(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if kind in {"NEW_MESSAGE", "ROOM_EVENT"}:
            text = client.format_incoming(message)
            self.message_log.append(text)
            self._notify(message)


class RoomChatWindow:
    """Simple Tkinter room chat panel.

    This is intentionally small and uses the same backend request types as the
    console client, without changing server behavior.
    """

    def __init__(self, controller: Optional[RoomChatController] = None):
        self.controller = controller or RoomChatController()
        self.root = None
        self.rooms_list = None
        self.messages_box = None
        self.room_entry = None
        self.message_entry = None
        self.target_entry = None
        if tk is not None:
            self._build_window()

    def _build_window(self) -> None:
        self.root = tk.Tk()
        self.root.title("Room Chat")
        self.root.geometry("760x500")

        left = ttk.Frame(self.root, padding=8)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)

        ttk.Label(left, text="Rooms").pack(anchor="w")
        self.rooms_list = tk.Listbox(left, width=24, height=18)
        self.rooms_list.pack(fill="both", expand=True)

        button_row = ttk.Frame(left)
        button_row.pack(fill="x", pady=(6, 0))
        ttk.Button(button_row, text="Refresh", command=self.refresh_rooms).pack(side="left", padx=(0, 4))
        ttk.Button(button_row, text="Create", command=self.create_selected_room).pack(side="left", padx=(0, 4))
        ttk.Button(button_row, text="Join", command=self.join_selected_room).pack(side="left", padx=(0, 4))
        ttk.Button(button_row, text="Leave", command=self.leave_selected_room).pack(side="left")

        right = ttk.Frame(self.root, padding=8)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(right, text="Messages").pack(anchor="w")
        self.messages_box = tk.Text(right, height=18, state="disabled", wrap="word")
        self.messages_box.pack(fill="both", expand=True, pady=(0, 8))

        form = ttk.Frame(right)
        form.pack(fill="x")

        ttk.Label(form, text="Room").grid(row=0, column=0, sticky="w")
        self.room_entry = ttk.Entry(form)
        self.room_entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))

        ttk.Label(form, text="Message").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.message_entry = ttk.Entry(form)
        self.message_entry.grid(row=1, column=1, sticky="ew", padx=(6, 8), pady=(8, 0))

        ttk.Label(form, text="Send to").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.target_entry = ttk.Entry(form)
        self.target_entry.grid(row=2, column=1, sticky="ew", padx=(6, 8), pady=(8, 0))

        form.columnconfigure(1, weight=1)

        action_row = ttk.Frame(right)
        action_row.pack(fill="x", pady=(8, 0))
        ttk.Button(action_row, text="Send Room Message", command=self.send_room_message).pack(side="left", padx=(0, 8))
        ttk.Button(action_row, text="Send File", command=self.send_file).pack(side="left")

    def append_message(self, text: str) -> None:
        if self.messages_box is None:
            return
        self.messages_box.configure(state="normal")
        self.messages_box.insert("end", text + "\n")
        self.messages_box.see("end")
        self.messages_box.configure(state="disabled")

    def refresh_rooms(self) -> list[dict[str, Any]]:
        rooms = self.controller.refresh_rooms()
        if self.rooms_list is not None:
            self.rooms_list.delete(0, "end")
            for room in rooms:
                name = room.get("name", "?")
                members = room.get("memberCount", 0)
                self.rooms_list.insert("end", f"{name} ({members})")
        return rooms

    def create_selected_room(self) -> Any:
        room_name = self.room_entry.get().strip() if self.room_entry is not None else ""
        if not room_name:
            room_name = self._selected_room_name()
        if not room_name:
            return {"type": "ROOM_RESPONSE", "status": "ERROR", "code": 400, "message": "Room name required."}
        return self.controller.create_room(room_name)

    def join_selected_room(self) -> Any:
        room_name = self.room_entry.get().strip() if self.room_entry is not None else ""
        if not room_name:
            room_name = self._selected_room_name()
        if not room_name:
            return {"type": "ROOM_RESPONSE", "status": "ERROR", "code": 400, "message": "Room name required."}
        return self.controller.join_room(room_name)

    def leave_selected_room(self) -> Any:
        room_name = self.room_entry.get().strip() if self.room_entry is not None else ""
        if not room_name:
            room_name = self._selected_room_name()
        if not room_name:
            return {"type": "ROOM_RESPONSE", "status": "ERROR", "code": 400, "message": "Room name required."}
        return self.controller.leave_room(room_name)

    def send_room_message(self) -> Any:
        room_name = self.room_entry.get().strip() if self.room_entry is not None else ""
        if not room_name:
            room_name = self._selected_room_name()
        content = self.message_entry.get().strip() if self.message_entry is not None else ""
        response = self.controller.send_room_message(room_name, content)
        if response and response.get("type") == "MESSAGE_DELIVERED":
            self.append_message(f"[you -> room {room_name}] {content}")
        elif response and response.get("type") == "MESSAGE_STORED":
            self.append_message(f"[stored -> room {room_name}] {content}")
        return response

    def send_file(self) -> Any:
        if self.target_entry is not None:
            recipient = self.target_entry.get().strip()
        else:
            recipient = ""
        if not recipient:
            recipient = self._selected_room_name() or ""
        path = self._select_file_path()
        if not path:
            return {"type": "FILE_ERROR", "message": "No file selected."}
        if self.controller.sock is None:
            return {"type": "FILE_ERROR", "message": "A connection is required."}
        from gui.files import send_file_to_target

        response = send_file_to_target(
            self.controller.sock,
            self.controller.send_lock,
            self.controller.responses,
            self.controller.stop_event,
            self.controller.token,
            recipient,
            path,
        )
        self.append_message(f"[file -> {recipient}] {path}")
        return response

    def _selected_room_name(self) -> str:
        if self.rooms_list is None or self.rooms_list.size() == 0:
            return ""
        index = self.rooms_list.curselection()
        if not index:
            return ""
        value = self.rooms_list.get(index[0])
        if " (" in value:
            return value.split(" (", 1)[0]
        return value

    def _select_file_path(self):
        from gui.files import select_file

        return select_file(title="Select a file to send")

    def mainloop(self) -> None:
        if self.root is not None:
            self.root.mainloop()


RoomChatApp = RoomChatWindow

__all__ = [
    "RoomChatController",
    "RoomChatWindow",
    "RoomChatApp",
]
