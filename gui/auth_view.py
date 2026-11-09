"""Login and registration view for the Tk chat application.

The view deliberately delegates all networking to ``ClientCore``. Incoming
protocol and lifecycle events are delivered by ``ChatApplication`` through
:meth:`handle_event` on Tk's main thread.
"""

from __future__ import annotations

import inspect
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from .client_core import ClientCore


class AuthView(ttk.Frame):
    """Provide login and registration using the application's shared client."""

    def __init__(
        self,
        parent: tk.Misc,
        client: ClientCore,
        on_authenticated: Callable[..., None],
    ) -> None:
        super().__init__(parent, padding=28)
        self.client = client
        self.on_authenticated = on_authenticated
        self._mode = "login"
        self._request_pending = False
        self._reconnect_after_failure = False
        self._show_password = tk.BooleanVar(master=self, value=False)

        content = ttk.Frame(self)
        content.pack(fill="both", expand=True)

        ttk.Label(
            content, text="TEAM 5 CHAT", font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="center", pady=(8, 4))
        self.heading = ttk.Label(
            content, text="Welcome back", font=("TkDefaultFont", 22, "bold")
        )
        self.heading.pack(anchor="center", pady=(0, 4))
        self.subtitle = ttk.Label(
            content, text="Sign in to continue to your conversations."
        )
        self.subtitle.pack(anchor="center", pady=(0, 22))

        form = ttk.Frame(content)
        form.pack(fill="x", padx=30)
        ttk.Label(form, text="Username").pack(anchor="w", pady=(0, 5))
        self.username_entry = ttk.Entry(form)
        self.username_entry.pack(fill="x", ipady=5, pady=(0, 14))
        self.username_entry.bind("<Return>", self._submit_from_keyboard)

        ttk.Label(form, text="Password").pack(anchor="w", pady=(0, 5))
        password_row = ttk.Frame(form)
        password_row.pack(fill="x", pady=(0, 7))
        password_row.columnconfigure(0, weight=1)
        self.password_entry = ttk.Entry(password_row, show="•")
        self.password_entry.grid(row=0, column=0, sticky="ew", ipady=5)
        self.password_entry.bind("<Return>", self._submit_from_keyboard)
        self.visibility_button = ttk.Checkbutton(
            password_row,
            text="Show",
            variable=self._show_password,
            command=self._toggle_password,
        )
        self.visibility_button.grid(row=0, column=1, padx=(8, 0))

        self.feedback_label = ttk.Label(
            form, text="", wraplength=420, justify="center"
        )
        self.feedback_label.pack(fill="x", pady=(8, 8))
        self.submit_button = ttk.Button(
            form, text="Log in", command=self._submit
        )
        self.submit_button.pack(fill="x", ipady=5)
        self.mode_button = ttk.Button(
            form,
            text="Need an account? Register",
            command=self._toggle_mode,
            style="Link.TButton",
        )
        self.mode_button.pack(pady=(12, 0))

        self.connection_label = ttk.Label(
            content, text=self._connection_message(), foreground="#666666"
        )
        self.connection_label.pack(anchor="center", pady=(18, 0))
        self.username_entry.focus_set()

    def _connection_message(self) -> str:
        state = getattr(self.client, "connection_state", "unknown")
        return f"Server connection: {state}"

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self._show_password.get() else "•")
        self.visibility_button.configure(
            text="Hide" if self._show_password.get() else "Show"
        )

    def _toggle_mode(self) -> None:
        self._mode = "register" if self._mode == "login" else "login"
        registering = self._mode == "register"
        self.heading.configure(text="Create your account" if registering else "Welcome back")
        self.subtitle.configure(
            text=(
                "Create an account to start chatting."
                if registering
                else "Sign in to continue to your conversations."
            )
        )
        self.submit_button.configure(text="Create account" if registering else "Log in")
        self.mode_button.configure(
            text=(
                "Already have an account? Log in"
                if registering
                else "Need an account? Register"
            )
        )
        self.feedback_label.configure(text="")

    def _submit_from_keyboard(self, _event: tk.Event[Any]) -> str:
        self._submit()
        return "break"

    def _submit(self) -> None:
        if self._request_pending:
            return
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        if not username or not password:
            self._show_feedback("Enter both your username and password.", error=True)
            return
        if not getattr(self.client, "is_connected", False):
            self._show_feedback(
                "Not connected to the server. Reconnecting…", error=True
            )
            self._connect_if_disconnected()
            return

        try:
            if self._mode == "register":
                self.client.register(username, password)
            else:
                self.client.login(username, password)
        except (ConnectionError, RuntimeError, OSError) as error:
            self._show_feedback(str(error), error=True)
            return

        self._request_pending = True
        self.submit_button.configure(state="disabled")
        self.mode_button.configure(state="disabled")
        self._show_feedback(
            "Creating your account…" if self._mode == "register" else "Signing in…"
        )

    def _connect_if_disconnected(self) -> None:
        if getattr(self.client, "connection_state", None) == "disconnected":
            try:
                self.client.connect()
            except (ConnectionError, RuntimeError, OSError) as error:
                self._show_feedback(f"Could not connect: {error}", error=True)

    def _finish_request(self) -> None:
        self._request_pending = False
        self.submit_button.configure(state="normal")
        self.mode_button.configure(state="normal")

    def _show_feedback(self, message: str, *, error: bool = False) -> None:
        self.feedback_label.configure(
            text=message,
            foreground="#b42318" if error else "#167044",
        )

    def handle_event(self, event: dict[str, Any]) -> None:
        """Handle queued client/server events on Tk's main thread."""
        kind = event.get("type")
        if kind == "REGISTER_RESPONSE":
            self._finish_request()
            if event.get("status") == "OK":
                self.password_entry.delete(0, tk.END)
                if self._mode == "register":
                    self._toggle_mode()
                self._show_feedback(
                    event.get("message") or "Registration successful. You can now log in."
                )
            else:
                self._show_feedback(
                    event.get("message") or "Registration failed. Please try again.",
                    error=True,
                )
            return

        if kind == "LOGIN_RESPONSE":
            self._finish_request()
            if event.get("status") == "OK":
                username = event.get("userId") or getattr(self.client, "username", None)
                if not username:
                    self._show_feedback(
                        "The server authenticated the session but did not return a username.",
                        error=True,
                    )
                    return
                self._show_feedback("Login successful.")
                self._notify_authenticated(str(username))
            else:
                self._reconnect_after_failure = True
                self._show_feedback(
                    event.get("message") or "Login failed. Check your credentials.",
                    error=True,
                )
                # Some client implementations may already have observed EOF by
                # the time this queued response is handled.
                self._connect_if_disconnected()
            return

        local_event = event.get("_event")
        if local_event == "connection":
            status = event.get("status", "unknown")
            self.connection_label.configure(text=f"Server connection: {status}")
            if status == "error":
                self._show_feedback(
                    event.get("message") or "Could not connect to the server.",
                    error=True,
                )
            elif status == "connected" and not self._request_pending:
                # Preserve any current feedback while reflecting reconnection.
                pass
            elif status == "disconnected" and self._reconnect_after_failure:
                self._reconnect_after_failure = False
                self.after(0, self._connect_if_disconnected)
            return

        if local_event == "client_error":
            self._finish_request()
            self._show_feedback(
                event.get("message") or "A client communication error occurred.",
                error=True,
            )

    def _notify_authenticated(self, username: str) -> None:
        """Call the documented username callback, tolerating the app's legacy no-arg hook."""
        try:
            signature = inspect.signature(self.on_authenticated)
        except (TypeError, ValueError):
            self.on_authenticated(username)
            return
        try:
            signature.bind(username)
        except TypeError:
            # ChatApplication.show_dashboard currently has a legacy no-arg
            # signature. Keep that integration working without changing app.py.
            signature.bind()
            self.on_authenticated()
        else:
            self.on_authenticated(username)
