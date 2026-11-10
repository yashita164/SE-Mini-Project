"""Private chat screen: one-to-one messages and stored history.

``ChatApplication`` builds this view with ``parent``, ``client``, ``target``
(the user chosen on the dashboard) and ``on_back``, and passes every server
event to :meth:`PrivateChatView.handle_event` on Tk's main thread. All
networking goes through the shared ``ClientCore``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from .client_core import ClientCore
from .private_chat_logic import (
    ack_text,
    format_history_row,
    format_line,
    is_message_from_partner,
    is_typing_from_partner,
    rows_for_conversation,
)

HISTORY_PAGE_SIZE = 200
MAX_AUTO_HISTORY_PAGES = 10
TYPING_IDLE_MS = 2000
PARTNER_TYPING_TIMEOUT_MS = 5000


class PrivateChatView(ttk.Frame):
    """Show a conversation with one user, with live messages and history."""

    def __init__(
        self,
        parent: tk.Misc,
        client: ClientCore,
        target: str | None,
        on_back: Callable[[], None],
    ) -> None:
        super().__init__(parent, padding=12)
        self.client = client
        self.partner = target or ""
        self.on_back = on_back
        self._me = client.username or ""
        self._next_before_id: int | None = None
        self._history_pages = 0
        self._seen_ids: set[str] = set()
        self._typing_sent = False
        self._typing_after_id: str | None = None
        self._partner_typing_after_id: str | None = None

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Button(header, text="< Back", command=self.on_back).pack(side="left")
        ttk.Label(
            header, text=f"Chat with {self.partner}", font=("", 13, "bold")
        ).pack(side="left", padx=12)
        self.older_button = ttk.Button(
            header, text="Load older messages", command=self._load_older,
            state="disabled",
        )
        self.older_button.pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(10, 6))
        self.text = tk.Text(
            body, wrap="word", state="disabled", height=10, padx=8, pady=6
        )
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.typing_label = ttk.Label(self, text="", foreground="#666666")
        self.typing_label.pack(anchor="w")

        entry_row = ttk.Frame(self)
        entry_row.pack(fill="x", pady=(4, 0))
        self.entry = ttk.Entry(entry_row)
        self.entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.entry.bind("<Return>", self._send_from_keyboard)
        self.entry.bind("<KeyRelease>", self._on_key)
        self.send_button = ttk.Button(entry_row, text="Send", command=self._send)
        self.send_button.pack(side="left", padx=(8, 0))

        self.status_label = ttk.Label(self, text="Loading history...")
        self.status_label.pack(anchor="w", pady=(6, 0))
        self.entry.focus_set()
        self._request_history(None)

    # ----- history -----

    def _request_history(self, before_id: int | None) -> None:
        try:
            self.client.request_history(limit=HISTORY_PAGE_SIZE, before_id=before_id)
        except (ConnectionError, RuntimeError) as error:
            self._set_status(str(error))

    def _load_older(self) -> None:
        if self._next_before_id is not None:
            self.older_button.configure(state="disabled")
            self.status_label.configure(text="Loading older messages...")
            self._request_history(self._next_before_id)

    def _show_history(self, event: dict[str, Any]) -> None:
        self._history_pages += 1
        rows = rows_for_conversation(
            event.get("messages", []), self._me, self.partner
        )
        rows = [row for row in rows if str(row.get("id")) not in self._seen_ids]
        for row in rows:
            self._seen_ids.add(str(row.get("id")))
        if rows:
            self._insert_top([format_history_row(row, self._me) for row in rows])
        next_id = event.get("nextBeforeId")
        self._next_before_id = next_id if isinstance(next_id, int) else None
        if (
            not rows and self._next_before_id is not None
            and self._history_pages < MAX_AUTO_HISTORY_PAGES
        ):
            # This page held nothing for this pair; keep looking further back.
            self._request_history(self._next_before_id)
            return
        self.older_button.configure(
            state="normal" if self._next_before_id is not None else "disabled"
        )
        self._set_status("" if rows or self._lines_shown() else "No earlier messages.")

    # ----- text box helpers -----

    def _lines_shown(self) -> bool:
        return bool(self.text.get("1.0", "end-1c").strip())

    def _insert_top(self, lines: list[str]) -> None:
        self.text.configure(state="normal")
        self.text.insert("1.0", "\n".join(lines) + "\n")
        self.text.configure(state="disabled")

    def _append(self, line: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        self.text.configure(state="disabled")
        self.text.see("end")

    def _set_status(self, message: str) -> None:
        self.status_label.configure(text=message)

    # ----- sending -----

    def _send_from_keyboard(self, _event: tk.Event) -> str:
        self._send()
        return "break"

    def _send(self) -> None:
        content = self.entry.get()
        if not content.strip():
            return
        try:
            self.client.send_private_message(self.partner, content)
        except (ConnectionError, RuntimeError) as error:
            self._set_status(str(error))
            return
        self._stop_typing()
        self._append(format_line(
            self._me, content, datetime.now(timezone.utc).isoformat(), self._me
        ))
        self.entry.delete(0, tk.END)
        self._set_status("Sending...")

    def _on_key(self, _event: tk.Event) -> None:
        if not self.entry.get():
            self._stop_typing()
            return
        if not self._typing_sent:
            self._send_typing(True)
        if self._typing_after_id is not None:
            self.after_cancel(self._typing_after_id)
        self._typing_after_id = self.after(TYPING_IDLE_MS, self._stop_typing)

    def _send_typing(self, is_typing: bool) -> None:
        try:
            self.client.send_typing(self.partner, is_typing)
            self._typing_sent = is_typing
        except (ConnectionError, RuntimeError):
            self._typing_sent = False

    def _stop_typing(self) -> None:
        if self._typing_after_id is not None:
            self.after_cancel(self._typing_after_id)
            self._typing_after_id = None
        if self._typing_sent:
            self._send_typing(False)

    # ----- server events -----

    def handle_event(self, event: dict[str, Any]) -> None:
        """Apply one server or local event on Tk's main thread."""
        local_event = event.get("_event")
        if local_event == "connection":
            if event.get("status") in {"disconnected", "error"}:
                self._set_status("Disconnected from the server.")
                self.send_button.configure(state="disabled")
            return
        if local_event == "client_error":
            self._set_status(str(event.get("message", "Client error.")))
            return

        kind = event.get("type")
        if kind == "HISTORY_RESPONSE":
            self._show_history(event)
        elif is_message_from_partner(event, self.partner):
            message_id = str(event.get("messageId", ""))
            if message_id and message_id in self._seen_ids:
                return
            if message_id:
                self._seen_ids.add(message_id)
            self._append(format_line(
                self.partner, str(event.get("content", "")),
                event.get("timestamp"), self._me,
            ))
            self.typing_label.configure(text="")
        elif is_typing_from_partner(event, self.partner):
            self._show_partner_typing(bool(event.get("isTyping")))
        else:
            status = ack_text(event)
            if status is not None:
                message_id = event.get("messageId")
                if message_id is not None:
                    self._seen_ids.add(str(message_id))
                self._set_status(status)
            elif kind == "ERROR":
                self._set_status(str(event.get("message", "Server error.")))

    def _show_partner_typing(self, is_typing: bool) -> None:
        if self._partner_typing_after_id is not None:
            self.after_cancel(self._partner_typing_after_id)
            self._partner_typing_after_id = None
        if is_typing:
            self.typing_label.configure(text=f"{self.partner} is typing...")
            self._partner_typing_after_id = self.after(
                PARTNER_TYPING_TIMEOUT_MS, lambda: self.typing_label.configure(text="")
            )
        else:
            self.typing_label.configure(text="")

    def destroy(self) -> None:
        self._stop_typing()
        if self._partner_typing_after_id is not None:
            self.after_cancel(self._partner_typing_after_id)
            self._partner_typing_after_id = None
        super().destroy()
