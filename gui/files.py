"""File selection and file-transfer helpers for the GUI chat client."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import client

try:  # pragma: no cover - GUI is optional in headless CI.
    import tkinter as tk
    from tkinter import filedialog
except Exception:  # pragma: no cover
    tk = None
    filedialog = None

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


__all__ = [
    "FileTransferPanel",
    "MAX_FILE_SIZE",
    "select_file",
    "send_file",
    "send_file_to_target",
    "validate_file",
]
