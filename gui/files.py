"""File selection and file-transfer helpers for the GUI chat client."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import client
from .client_core import ClientCore

try:  # pragma: no cover - GUI is optional in headless CI.
    import tkinter as tk
    from tkinter import filedialog, ttk
except Exception:  # pragma: no cover
    tk = None
    filedialog = None
    ttk = None

MAX_FILE_SIZE = getattr(client, "MAX_FILE_SIZE", 1024 * 1024)


def validate_file(filepath: str | Path, max_size: int | None = None) -> Tuple[Path | None, str | None]:
    """Return a normalized file path or a validation error string."""
    candidate = Path(filepath).expanduser() if filepath not in (None, "") else None
    if candidate is None:
        return None, "No file selected."
    if not candidate.exists() or not candidate.is_file():
        return None, f"File not found: {candidate}"
    limit = MAX_FILE_SIZE if max_size is None else max_size
    size = candidate.stat().st_size
    if size > limit:
        return None, f"File exceeds the configured limit ({limit} bytes)."
    return candidate, None


def select_file(title: str = "Select a file", initialdir: str | None = None) -> str | None:
    """Open a file-open dialog if Tkinter is available; otherwise return None."""
    if tk is None or filedialog is None:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.update()
        selected = filedialog.askopenfilename(title=title, initialdir=initialdir)
        return selected or None
    except Exception:  # pragma: no cover - headless environment or missing display.
        return None
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def send_file_to_target(sock, send_lock, responses, stop_event, token, target, filepath):
    """Send a file to a username or room using the existing client protocol."""
    path, error = validate_file(filepath)
    if error:
        return {"type": "FILE_ERROR", "message": error}
    if target is None or not str(target).strip():
        return {"type": "FILE_ERROR", "message": "A recipient is required."}
    try:
        client.send_file(sock, send_lock, responses, stop_event, token, str(target), str(path))
        return {"type": "FILE_SENT", "recipient": str(target), "filename": path.name}
    except Exception as exc:  # pragma: no cover
        return {"type": "FILE_ERROR", "message": str(exc)}


def send_file(sock, send_lock, responses, stop_event, token, recipient, filepath):
    """Compatibility wrapper expected by the rest of the codebase."""
    return send_file_to_target(sock, send_lock, responses, stop_event, token, recipient, filepath)


class FileTransferPanel:
    """Minimal helper for a GUI file transfer panel.

    The actual transport still uses the existing console client implementation, so
    the backend protocol is unchanged.
    """

    def __init__(self, sock=None, send_lock=None, responses=None, stop_event=None, token=None):
        self.sock = sock
        self.send_lock = send_lock
        self.responses = responses
        self.stop_event = stop_event
        self.token = token

    def choose_file(self, title: str = "Select a file") -> str | None:
        return select_file(title=title)

    def send(self, recipient: str, filepath: str | Path):
        if self.sock is None:
            raise ValueError("A socket connection is required before sending files.")
        return send_file_to_target(
            self.sock,
            self.send_lock,
            self.responses,
            self.stop_event,
            self.token,
            recipient,
            str(filepath),
        )


class FilesView(ttk.Frame):
    """Choose a file and send it to a user or room through the shared client."""

    def __init__(
        self,
        parent: tk.Misc,
        client: ClientCore,
        target: str | None,
        on_back: Callable[[], None],
    ) -> None:
        super().__init__(parent, padding=16)
        self.client = client
        self.on_back = on_back
        self.file_path: Path | None = None

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Button(header, text="< Back", command=on_back).pack(side="left")
        ttk.Label(
            header, text="File transfer", font=("", 14, "bold")
        ).pack(side="left", padx=12)

        form = ttk.LabelFrame(self, text="Send a file", padding=16)
        form.pack(fill="x", pady=(16, 0))
        ttk.Label(
            form, text="Recipient username or room (use #room):"
        ).grid(row=0, column=0, sticky="w")
        self.destination_entry = ttk.Entry(form)
        self.destination_entry.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12)
        )
        if target:
            self.destination_entry.insert(0, target)

        self.file_label = ttk.Label(form, text="No file selected.", wraplength=500)
        self.file_label.grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Button(form, text="Choose file…", command=self._choose_file).grid(
            row=2, column=1, sticky="e", padx=(8, 0), pady=(0, 8)
        )
        ttk.Button(form, text="Send file", command=self._send_file).grid(
            row=3, column=1, sticky="e"
        )
        form.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(self, text="")
        self.status_label.pack(anchor="w", pady=(12, 0))

    def _choose_file(self) -> None:
        if filedialog is None:
            self.status_label.configure(text="File selection is unavailable.")
            return
        selected = filedialog.askopenfilename(parent=self.winfo_toplevel())
        if not selected:
            return
        try:
            path, error = validate_file(selected)
        except OSError as error:
            self.status_label.configure(text=f"Could not inspect file: {error}")
            return
        if error:
            self.file_path = None
            self.file_label.configure(text="No file selected.")
            self.status_label.configure(text=error)
            return
        self.file_path = path
        self.file_label.configure(text=f"{path.name} ({path.stat().st_size:,} bytes)")
        self.status_label.configure(text="")

    def _send_file(self) -> None:
        destination = self.destination_entry.get().strip()
        if not destination:
            self.status_label.configure(
                text="Enter a username or #room as the recipient."
            )
            return
        if self.file_path is None:
            self.status_label.configure(text="Choose a file first.")
            return
        try:
            path, error = validate_file(self.file_path)
        except OSError as error:
            self.status_label.configure(text=f"Could not inspect file: {error}")
            return
        if error:
            self.file_path = None
            self.file_label.configure(text="No file selected.")
            self.status_label.configure(text=error)
            return
        try:
            self.client.send_file(destination, path)
        except (ConnectionError, OSError, RuntimeError, ValueError) as error:
            self.status_label.configure(text=str(error))
            return
        self.status_label.configure(text=f"Sending {path.name} to {destination}…")

    def handle_event(self, event: dict[str, Any]) -> None:
        """Display asynchronous file-transfer results from ``ClientCore``."""
        if event.get("_event") == "connection":
            if event.get("status") in {"disconnected", "error"}:
                self.status_label.configure(text="Disconnected from the server.")
            return
        if event.get("_event") == "client_error":
            self.status_label.configure(
                text=str(event.get("message", "Client error."))
            )
            return
        if event.get("_event") == "file_transfer":
            status = event.get("status")
            if status == "received":
                self.status_label.configure(
                    text=f"Received {event.get('filename', 'a file')} from "
                    f"{event.get('fromUser', 'a user')}; saved to {event.get('path', '')}."
                )
            elif status == "sent":
                self.status_label.configure(
                    text=f"Sent {Path(event.get('path', '')).name}."
                )
            elif status == "error":
                self.status_label.configure(
                    text=str(event.get("message", "File transfer failed."))
                )
            elif status == "receiving":
                self.status_label.configure(
                    text=f"Receiving {event.get('filename', 'a file')}…"
                )
            return
        if event.get("type") == "ERROR":
            self.status_label.configure(
                text=str(event.get("message", "Server error."))
            )


__all__ = [
    "FileTransferPanel",
    "FilesView",
    "MAX_FILE_SIZE",
    "select_file",
    "send_file",
    "send_file_to_target",
    "validate_file",
]
