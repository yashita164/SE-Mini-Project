from __future__ import annotations

from pathlib import Path

from gui import files
from gui.app import ChatApplication
from gui.files import FilesView


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Path]] = []

    def send_file(self, destination: str, path: Path) -> None:
        self.sent.append((destination, path))


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, *, text: str) -> None:
        self.text = text


class FakeEntry:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value


def make_view(destination: str = "#General") -> FilesView:
    view = FilesView.__new__(FilesView)
    view.client = FakeClient()
    view.destination_entry = FakeEntry(destination)
    view.file_label = FakeLabel()
    view.status_label = FakeLabel()
    view.file_path = None
    view.winfo_toplevel = lambda: None
    return view


def test_send_file_uses_client_for_room_recipient(tmp_path):
    view = make_view()
    path = tmp_path / "attachment.txt"
    path.write_text("hello", encoding="utf-8")
    view.file_path = path

    view._send_file()

    assert view.client.sent == [("#General", path)]
    assert view.status_label.text.startswith("Sending attachment.txt")


def test_app_discovers_integrated_file_transfer_view():
    assert ChatApplication._discover_view("gui.files", "FilesView") is FilesView


def test_send_file_requires_recipient_and_selected_file():
    view = make_view(destination="  ")
    view._send_file()
    assert "recipient" in view.status_label.text

    view = make_view()
    view._send_file()
    assert view.status_label.text == "Choose a file first."


def test_choose_file_displays_selected_file(monkeypatch, tmp_path):
    view = make_view()
    path = tmp_path / "share.txt"
    path.write_text("data", encoding="utf-8")
    monkeypatch.setattr(
        files.filedialog, "askopenfilename", lambda **_kwargs: str(path)
    )

    view._choose_file()

    assert view.file_path == path
    assert view.file_label.text.startswith("share.txt")


def test_file_view_displays_incoming_transfer_location():
    view = make_view()

    view.handle_event({
        "_event": "file_transfer",
        "status": "received",
        "filename": "shared.txt",
        "fromUser": "bob",
        "path": "received_files\\shared.txt",
    })

    assert "shared.txt" in view.status_label.text
    assert "received_files" in view.status_label.text
