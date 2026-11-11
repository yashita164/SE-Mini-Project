"""Basic authenticated dashboard; chat screens are supplied by teammates."""

from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk
from typing import Any, Callable

from .client_core import ClientCore


class Dashboard(ttk.Frame):
    """Show account, connection state, online users and available rooms.

    ``on_navigate`` receives ``"private"`` or ``"room"`` and the selected
    username/room. ``on_logout`` is called when the user requests logout.
    """

    def __init__(
        self,
        parent: tk.Misc,
        client: ClientCore,
        *,
        on_navigate: Callable[[str, str | None], None],
        on_logout: Callable[[], None],
    ) -> None:
        super().__init__(parent, padding=16)
        self.client = client
        self.on_navigate = on_navigate
        self.on_logout = on_logout
        self._refresh_after_id: str | None = None

        header = ttk.Frame(self)
        header.pack(fill="x")
        self.username_label = ttk.Label(
            header, text=f"Logged in as {client.username or 'unknown'}",
            font=("", 14, "bold"),
        )
        self.username_label.pack(side="left")
        ttk.Button(header, text="Log out", command=self.on_logout).pack(side="right")

        self.connection_label = ttk.Label(self, text="Connection: connected")
        self.connection_label.pack(anchor="w", pady=(8, 12))

        lists = ttk.Frame(self)
        lists.pack(fill="both", expand=True)
        users_panel = ttk.LabelFrame(lists, text="Online users", padding=8)
        rooms_panel = ttk.LabelFrame(lists, text="Available rooms", padding=8)
        users_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
        rooms_panel.pack(side="left", fill="both", expand=True, padx=(6, 0))

        self.users_list = tk.Listbox(users_panel, exportselection=False)
        self.users_list.pack(fill="both", expand=True)
        ttk.Button(
            users_panel,
            text="Open private chat",
            command=self._open_private_chat,
        ).pack(fill="x", pady=(8, 0))

        self.rooms_list = tk.Listbox(rooms_panel, exportselection=False)
        self.rooms_list.pack(fill="both", expand=True)
        room_actions = ttk.Frame(rooms_panel)
        room_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(
            room_actions,
            text="Create room",
            command=self._create_room,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            room_actions,
            text="Open group chat",
            command=self._open_room_chat,
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        footer = ttk.Frame(self)
        footer.pack(fill="x", pady=(12, 0))
        self.status_label = ttk.Label(footer, text="")
        self.status_label.pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(
            footer,
            text="Send file",
            command=lambda: self.on_navigate("files", None),
        ).pack(side="right", padx=(0, 8))

        self.refresh()
        self._schedule_refresh()

    def handle_event(self, event: dict[str, Any]) -> None:
        """Apply a server or local connection event on the Tk main thread."""
        local_event = event.get("_event")
        if local_event == "connection":
            status = event.get("status", "unknown")
            self.connection_label.configure(text=f"Connection: {status}")
            if status == "error":
                self.status_label.configure(text=event.get("message", "Connection failed."))
            return
        if local_event in {"client_error", "file_transfer"}:
            message = event.get("message") or event.get("status", "")
            self.status_label.configure(text=str(message))
            return

        kind = event.get("type")
        if kind == "USER_LIST" and event.get("room") is None:
            self._replace_list(self.users_list, event.get("users", []))
            self.status_label.configure(text="Connected")
        elif kind == "ROOM_LIST":
            self._replace_list(
                self.rooms_list,
                [room.get("name", "") for room in event.get("rooms", [])],
            )
            self.status_label.configure(text="Connected")
        elif kind == "ROOM_EVENT" or (
            kind == "ROOM_RESPONSE" and event.get("status") == "OK"
        ):
            self.refresh()
        elif kind == "ROOM_RESPONSE":
            self.status_label.configure(
                text=event.get("message", "Room operation failed.")
            )
        elif kind == "ERROR":
            self.status_label.configure(text=event.get("message", "Server error."))

    def refresh(self) -> None:
        """Request the current global user list and room directory."""
        try:
            self.client.list_users()
            self.client.list_rooms()
            self.status_label.configure(text="Refreshing…")
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))

    def _replace_list(self, listbox: tk.Listbox, values: list[str]) -> None:
        selected = listbox.get(tk.ACTIVE) if listbox.size() else None
        listbox.delete(0, tk.END)
        for value in values:
            listbox.insert(tk.END, value)
        if selected in values:
            index = values.index(selected)
            listbox.selection_set(index)
            listbox.activate(index)

    def _open_private_chat(self) -> None:
        selection = self.users_list.curselection()
        if selection:
            self.on_navigate("private", self.users_list.get(selection[0]))
        else:
            self.status_label.configure(text="Select an online user first.")

    def _open_room_chat(self) -> None:
        selection = self.rooms_list.curselection()
        if selection:
            self.on_navigate("room", self.rooms_list.get(selection[0]))
        else:
            self.status_label.configure(text="Select a room first.")

    def _create_room(self) -> None:
        room_name = simpledialog.askstring(
            "Create room", "Room name:", parent=self.winfo_toplevel()
        )
        if room_name is None:
            return
        room_name = room_name.strip()
        if not room_name:
            self.status_label.configure(text="Room name is required.")
            return
        try:
            self.client.create_room(room_name)
            self.status_label.configure(text=f"Creating room {room_name}…")
        except (ConnectionError, RuntimeError) as error:
            self.status_label.configure(text=str(error))

    def _schedule_refresh(self) -> None:
        self._refresh_after_id = self.after(10_000, self._refresh_and_reschedule)

    def _refresh_and_reschedule(self) -> None:
        if self.winfo_exists():
            self.refresh()
            self._schedule_refresh()
