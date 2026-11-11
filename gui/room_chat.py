"""Room chat helpers for the GUI layer.

The backend remains the same: the GUI creates the same JSON requests the console
client uses, then displays the responses and push events produced by the server.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

import client
from .client_core import ClientCore

try:  # pragma: no cover - GUI is optional in headless CI.
    import tkinter as tk
    from tkinter import filedialog, simpledialog, ttk
except Exception:  # pragma: no cover
    tk = None
    filedialog = None
    simpledialog = None
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


class RoomChatView(ttk.Frame):
    """Integrated room directory and live group conversation."""

    def __init__(
        self,
        parent: tk.Misc,
        client: ClientCore,
        target: str | None,
        on_back: Callable[[], None],
    ) -> None:
        super().__init__(parent, padding=12)
        self.client = client
        self.on_back = on_back
        self._active_room = target or ""
        self._room_names: list[str] = []
        self._joined_rooms: set[str] = set()
        self._messages_by_room: dict[str, list[str]] = {}

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Button(header, text="< Back", command=on_back).pack(side="left")
        self.room_title = ttk.Label(
            header,
            text=f"Group chat{': ' + self._active_room if self._active_room else ''}",
            font=("", 13, "bold"),
        )
        self.room_title.pack(side="left", padx=12)
        ttk.Button(header, text="Refresh rooms", command=self.refresh_rooms).pack(
            side="right"
        )

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(10, 6))
        rooms_panel = ttk.LabelFrame(body, text="Available rooms", padding=8)
        rooms_panel.pack(side="left", fill="y", padx=(0, 8))
        self.rooms_list = tk.Listbox(rooms_panel, width=28, exportselection=False)
        self.rooms_list.pack(fill="both", expand=True)
        self.rooms_list.bind("<<ListboxSelect>>", self._select_room)

        room_actions = ttk.Frame(rooms_panel)
        room_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(room_actions, text="Create", command=self._create_room).pack(
            side="left", fill="x", expand=True, padx=(0, 3)
        )
        ttk.Button(room_actions, text="Join", command=self._join_room).pack(
            side="left", fill="x", expand=True, padx=3
        )
        ttk.Button(room_actions, text="Leave", command=self._leave_room).pack(
            side="left", fill="x", expand=True, padx=(3, 0)
        )

        conversation = ttk.Frame(body)
        conversation.pack(side="left", fill="both", expand=True)
        self.messages = tk.Text(
            conversation, wrap="word", state="disabled", height=12, padx=8, pady=6
        )
        scrollbar = ttk.Scrollbar(
            conversation, orient="vertical", command=self.messages.yview
        )
        self.messages.configure(yscrollcommand=scrollbar.set)
        self.messages.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        entry_row = ttk.Frame(self)
        entry_row.pack(fill="x")
        self.message_entry = ttk.Entry(entry_row)
        self.message_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.message_entry.bind("<Return>", self._send_from_keyboard)
        ttk.Button(entry_row, text="Send", command=self._send).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(entry_row, text="Send file", command=self._send_file).pack(
            side="left", padx=(8, 0)
        )

        self.status_label = ttk.Label(self, text="")
        self.status_label.pack(anchor="w", pady=(6, 0))
        if self._active_room:
            self._update_title()
        self.refresh_rooms()

    @staticmethod
    def _room_key(room: str) -> str:
        return room.casefold()

    def _update_title(self) -> None:
        title = f"Group chat: {self._active_room}" if self._active_room else "Group chat"
        self.room_title.configure(text=title)
        self._render_messages()

    def _render_messages(self) -> None:
        self.messages.configure(state="normal")
        self.messages.delete("1.0", tk.END)
        for line in self._messages_by_room.get(
            self._room_key(self._active_room), []
        ):
            self.messages.insert(tk.END, line + "\n")
        self.messages.configure(state="disabled")
        self.messages.see(tk.END)

    def _append_message(self, room: str, line: str) -> None:
        key = self._room_key(room)
        history = self._messages_by_room.setdefault(key, [])
        history.append(line)
        del history[:-500]
        if key == self._room_key(self._active_room):
            self.messages.configure(state="normal")
            self.messages.insert(tk.END, line + "\n")
            self.messages.configure(state="disabled")
            self.messages.see(tk.END)

    def _select_room(self, _event: tk.Event | None = None) -> None:
        selection = self.rooms_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self._room_names):
            return
        self._active_room = self._room_names[index]
        self._update_title()
        self._check_membership()

    def _check_membership(self) -> None:
        if not self._active_room:
            return
        try:
            self.client.list_users(self._active_room)
            self.status_label.configure(text="Checking room membership…")
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))

    def refresh_rooms(self) -> None:
        try:
            self.client.list_rooms()
            self.status_label.configure(text="Refreshing rooms…")
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))

    def _create_room(self) -> None:
        if simpledialog is None:
            self.status_label.configure(text="Room creation is unavailable.")
            return
        room = simpledialog.askstring(
            "Create room", "Room name:", parent=self.winfo_toplevel()
        )
        if room is None:
            return
        room = room.strip()
        if not room:
            self.status_label.configure(text="Room name is required.")
            return
        try:
            self.client.create_room(room)
            self._active_room = room
            self._update_title()
            self.status_label.configure(text=f"Creating room {room}…")
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))

    def _join_room(self) -> None:
        if not self._active_room:
            self.status_label.configure(text="Select a room first.")
            return
        try:
            self.client.join_room(self._active_room)
            self.status_label.configure(text=f"Joining {self._active_room}…")
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))

    def _leave_room(self) -> None:
        if not self._active_room:
            self.status_label.configure(text="Select a room first.")
            return
        try:
            self.client.leave_room(self._active_room)
            self.status_label.configure(text=f"Leaving {self._active_room}…")
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))

    def _send_from_keyboard(self, _event: tk.Event) -> str:
        self._send()
        return "break"

    def _send(self) -> None:
        room = self._active_room
        content = self.message_entry.get()
        if not room:
            self.status_label.configure(text="Select a room first.")
            return
        if self._room_key(room) not in self._joined_rooms:
            self.status_label.configure(text="Join this room before sending messages.")
            return
        if not content.strip():
            return
        try:
            self.client.send_room_message(room, content)
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))
            return
        username = self.client.username or "You"
        self._append_message(room, f"{username}: {content}")
        self.message_entry.delete(0, tk.END)
        self.status_label.configure(text="Sending…")

    def _send_file(self) -> None:
        room = self._active_room
        if not room:
            self.status_label.configure(text="Select a room first.")
            return
        if self._room_key(room) not in self._joined_rooms:
            self.status_label.configure(text="Join this room before sending files.")
            return
        if filedialog is None:
            self.status_label.configure(text="File selection is unavailable.")
            return
        path = filedialog.askopenfilename(parent=self.winfo_toplevel())
        if not path:
            return
        try:
            self.client.send_file(f"#{room}", Path(path))
            self.status_label.configure(text=f"Sending {Path(path).name}…")
        except (OSError, ValueError, RuntimeError, ConnectionError) as error:
            self.status_label.configure(text=str(error))

    def handle_event(self, event: dict[str, Any]) -> None:
        """Update room state and conversation from events on Tk's main thread."""
        local_event = event.get("_event")
        if local_event == "connection":
            if event.get("status") in {"disconnected", "error"}:
                self.status_label.configure(text="Disconnected from the server.")
            return
        if local_event == "client_error":
            self.status_label.configure(text=str(event.get("message", "Client error.")))
            return
        if local_event == "file_transfer":
            status = event.get("status")
            if status == "received":
                self.status_label.configure(
                    text=f"Received {event.get('filename', 'a file')} from "
                    f"{event.get('fromUser', 'a room member')}."
                )
            elif status == "error":
                self.status_label.configure(text=str(event.get("message", "File transfer failed.")))
            elif status == "sent":
                self.status_label.configure(text="File sent.")
            return

        kind = event.get("type")
        if kind == "ROOM_LIST":
            rooms = event.get("rooms", [])
            self._room_names = [
                room["name"] for room in rooms
                if isinstance(room, dict) and isinstance(room.get("name"), str)
            ]
            self.rooms_list.delete(0, tk.END)
            for room in rooms:
                if isinstance(room, dict) and isinstance(room.get("name"), str):
                    count = room.get("memberCount", 0)
                    self.rooms_list.insert(tk.END, f"{room['name']} ({count})")
            if self._active_room:
                for index, name in enumerate(self._room_names):
                    if self._room_key(name) == self._room_key(self._active_room):
                        self.rooms_list.selection_set(index)
                        self.rooms_list.activate(index)
                        self._active_room = name
                        self._check_membership()
                        break
            self._update_title()
            self.status_label.configure(text="Room list updated.")
        elif kind == "USER_LIST" and isinstance(event.get("room"), str):
            room = event["room"]
            self._joined_rooms.add(self._room_key(room))
            if self._room_key(room) == self._room_key(self._active_room):
                self.status_label.configure(text=f"You are a member of {room}.")
        elif kind == "ROOM_RESPONSE":
            if event.get("status") != "OK":
                message = str(event.get("message", "Room operation failed."))
                if event.get("code") == 403:
                    if self._active_room:
                        self._joined_rooms.discard(self._room_key(self._active_room))
                    self.status_label.configure(text="Join this room to continue.")
                elif event.get("code") == 409 and "already in this room" in message.lower():
                    self._check_membership()
                else:
                    self.status_label.configure(text=message)
                return
            action = event.get("action")
            room = event.get("room")
            if isinstance(room, str) and action in {"CREATE", "JOIN"}:
                self._joined_rooms.add(self._room_key(room))
                self._active_room = room
                self._update_title()
                self.status_label.configure(text=f"Joined {room}.")
                if action == "CREATE":
                    self.refresh_rooms()
            elif isinstance(room, str) and action == "LEAVE":
                self._joined_rooms.discard(self._room_key(room))
                self.status_label.configure(text=f"Left {room}.")
        elif kind == "ROOM_EVENT":
            room = event.get("room")
            if isinstance(room, str):
                verb = "joined" if event.get("event") == "JOINED" else "left"
                self._append_message(
                    room, f"{event.get('user', 'Someone')} {verb} the room."
                )
        elif kind == "NEW_MESSAGE" and isinstance(event.get("roomId"), str):
            room = event["roomId"]
            stamp = event.get("timestamp")
            time_text = ""
            if isinstance(stamp, str):
                try:
                    time_text = datetime.fromisoformat(
                        stamp.replace("Z", "+00:00")
                    ).astimezone(timezone.utc).strftime("%H:%M ")
                except ValueError:
                    pass
            self._append_message(
                room,
                f"{time_text}{event.get('fromUser', 'Someone')}: "
                f"{event.get('content', '')}",
            )
        elif kind in {"MESSAGE_DELIVERED", "MESSAGE_STORED"}:
            if not event.get("room") or self._room_key(str(event["room"])) == self._room_key(
                self._active_room
            ):
                self.status_label.configure(
                    text=(
                        "Message sent."
                        if kind == "MESSAGE_DELIVERED"
                        else "Message saved; no other room members are online."
                    )
                )
        elif kind in {"MESSAGE_ERROR", "ERROR"}:
            self.status_label.configure(
                text=str(event.get("message", "Message could not be sent."))
            )


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
    "RoomChatView",
    "RoomChatWindow",
    "RoomChatApp",
]
