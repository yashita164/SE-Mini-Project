"""Tkinter application shell for the chat client's shared communication layer.

Screen factories are injected so assigned feature modules can be added without
changing socket handling. Factories receive ``parent`` and ``client`` keyword
arguments; authentication additionally receives ``on_authenticated``.
"""

from __future__ import annotations

import importlib
import importlib.util
import queue
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from .client_core import ClientCore
from .dashboard import Dashboard

ViewFactory = Callable[..., tk.Widget]


class ChatApplication:
    """Own the Tk root, client, navigation, event polling and shutdown."""

    def __init__(
        self,
        root: tk.Tk | None = None,
        client: ClientCore | None = None,
        *,
        auth_view_factory: ViewFactory | None = None,
        private_chat_factory: ViewFactory | None = None,
        room_chat_factory: ViewFactory | None = None,
        file_view_factory: ViewFactory | None = None,
    ) -> None:
        self.root = root or tk.Tk()
        self.root.title("Team 5 Chat")
        self.root.geometry("760x520")
        self.root.minsize(560, 380)
        self.client = client or ClientCore()
        self._auth_view_factory = auth_view_factory or self._discover_auth_view()
        self._feature_factories = {
            "private": private_chat_factory or self._discover_view(
                "gui.private_chat", "PrivateChatView"
            ),
            "room": room_chat_factory or self._discover_view(
                "gui.room_chat", "RoomChatView"
            ),
            "files": file_view_factory or self._discover_view(
                "gui.files", "FilesView"
            ),
        }
        self._closing = False
        self._placeholder_connection_label: ttk.Label | None = None
        self._placeholder_message_label: ttk.Label | None = None

        self.view_container = ttk.Frame(self.root)
        self.view_container.pack(fill="both", expand=True)
        self._current_view: tk.Widget | None = None
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.show_authentication()
        self.client.connect()
        self.root.after(50, self._poll_events)

    @staticmethod
    def _discover_auth_view() -> ViewFactory | None:
        """Load the assigned AuthView when its module is present."""
        return ChatApplication._discover_view("gui.auth_view", "AuthView")

    @staticmethod
    def _discover_view(module_name: str, class_name: str) -> ViewFactory | None:
        """Load an optional teammate-provided screen by its documented class."""
        if importlib.util.find_spec(module_name) is None:
            return None
        module = importlib.import_module(module_name)
        return getattr(module, class_name, None)

    def show_authentication(self) -> None:
        """Display the assigned authentication view or an integration prompt."""
        self._clear_view()
        if self._auth_view_factory is None:
            self._placeholder_connection_label = None
            self._placeholder_message_label = None
            view = ttk.Frame(self.view_container, padding=24)
            ttk.Label(
                view,
                text=(
                    "The authentication screen is not integrated yet.\n"
                    "Add gui.auth_view.AuthView to enable login and registration."
                ),
                justify="center",
            ).pack(expand=True)
            self._placeholder_connection_label = ttk.Label(
                view,
                text="Connection state: " + self.client.connection_state,
            )
            self._placeholder_connection_label.pack(pady=(0, 8))
            self._placeholder_message_label = ttk.Label(view, text="", wraplength=500)
            self._placeholder_message_label.pack(pady=(0, 12))
            ttk.Button(
                view,
                text="Connect",
                command=self._connect_if_disconnected,
            ).pack()
            self._set_view(view)
            return

        view = self._auth_view_factory(
            parent=self.view_container,
            client=self.client,
            on_authenticated=self.show_dashboard,
        )
        self._set_view(view)

    def show_dashboard(self) -> None:
        """Navigate to the dashboard after a successful login."""
        if not self.client.is_authenticated:
            return
        self._clear_view()
        dashboard = Dashboard(
            self.view_container,
            self.client,
            on_navigate=self.navigate,
            on_logout=self._logout,
        )
        self._set_view(dashboard)

    def navigate(self, destination: str, target: str | None = None) -> None:
        """Open an injected private/room screen or an integration placeholder."""
        factory = self._feature_factories.get(destination)
        self._clear_view()
        if factory is None:
            view = ttk.Frame(self.view_container, padding=24)
            title = {
                "private": "Private chat",
                "room": "Group chat",
                "files": "File transfer",
            }.get(destination, destination)
            ttk.Label(
                view,
                text=f"{title} screen is supplied by a teammate and is not integrated yet.",
                wraplength=500,
            ).pack(pady=(0, 12))
            if target:
                ttk.Label(view, text=f"Selected: {target}").pack(pady=(0, 12))
            ttk.Button(
                view, text="Back to dashboard", command=self.show_dashboard
            ).pack()
            self._set_view(view)
            return
        view = factory(
            parent=self.view_container,
            client=self.client,
            target=target,
            on_back=self.show_dashboard,
        )
        self._set_view(view)

    def _logout(self) -> None:
        try:
            self.client.logout()
        except (ConnectionError, RuntimeError) as error:
            self._show_client_error(str(error))

    def _connect_if_disconnected(self) -> None:
        if self.client.connection_state == "disconnected":
            self.client.connect()

    def _show_client_error(self, message: str) -> None:
        self._clear_view()
        view = ttk.Frame(self.view_container, padding=24)
        ttk.Label(view, text=message, wraplength=500).pack(pady=(0, 12))
        ttk.Button(
            view, text="Return to authentication", command=self.show_authentication
        ).pack()
        self._set_view(view)

    def _poll_events(self) -> None:
        """Drain socket events on Tk's main thread and schedule the next poll."""
        if self._closing:
            return
        for _ in range(500):
            try:
                event = self.client.events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)
        self.root.after(50, self._poll_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        if self._current_view is not None:
            handler = getattr(self._current_view, "handle_event", None)
            if callable(handler):
                handler(event)

        if event.get("type") == "LOGIN_RESPONSE":
            if event.get("status") == "OK":
                if not isinstance(self._current_view, Dashboard):
                    self.show_dashboard()
        elif event.get("type") == "LOGOUT_RESPONSE":
            self.client.disconnect()
            self.show_authentication()
            self.client.connect()
        elif (
            event.get("_event") == "connection"
            and self._placeholder_connection_label is not None
        ):
            status = event.get("status", "unknown")
            self._placeholder_connection_label.configure(
                text=f"Connection state: {status}"
            )
            if status == "error" and self._placeholder_message_label is not None:
                self._placeholder_message_label.configure(
                    text=event.get("message", "Could not connect to server.")
                )
        elif (
            event.get("_event") == "connection"
            and event.get("status") == "disconnected"
            and not self.client.is_authenticated
        ):
            if isinstance(self._current_view, Dashboard):
                self.show_authentication()

    def _clear_view(self) -> None:
        if self._current_view is not None:
            self._current_view.destroy()
            self._current_view = None
        self._placeholder_connection_label = None
        self._placeholder_message_label = None

    def _set_view(self, view: tk.Widget) -> None:
        self._current_view = view
        view.pack(fill="both", expand=True)

    def close(self) -> None:
        """Stop the client threads/socket and destroy the Tk application."""
        if self._closing:
            return
        self._closing = True
        self.client.close()
        self.root.destroy()

    def run(self) -> None:
        """Enter Tk's main event loop."""
        self.root.mainloop()


def main() -> None:
    """Launch the GUI application."""
    ChatApplication().run()


if __name__ == "__main__":
    main()
