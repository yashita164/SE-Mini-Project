from __future__ import annotations

from gui import dashboard
from gui.dashboard import Dashboard


class FakeStatusLabel:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, *, text: str) -> None:
        self.text = text


class FakeClient:
    def __init__(self) -> None:
        self.created_rooms: list[str] = []

    def create_room(self, room_name: str) -> None:
        self.created_rooms.append(room_name)


def make_dashboard() -> Dashboard:
    view = Dashboard.__new__(Dashboard)
    view.client = FakeClient()
    view.status_label = FakeStatusLabel()
    view.winfo_toplevel = lambda: None
    return view


def test_create_room_trims_name_and_sends_request(monkeypatch):
    view = make_dashboard()
    monkeypatch.setattr(
        dashboard.simpledialog, "askstring", lambda *args, **kwargs: "  General  "
    )

    view._create_room()

    assert view.client.created_rooms == ["General"]
    assert view.status_label.text == "Creating room General…"


def test_create_room_ignores_cancel_and_rejects_empty_name(monkeypatch):
    view = make_dashboard()
    monkeypatch.setattr(
        dashboard.simpledialog, "askstring", lambda *args, **kwargs: None
    )
    view._create_room()
    assert view.client.created_rooms == []

    monkeypatch.setattr(
        dashboard.simpledialog, "askstring", lambda *args, **kwargs: "   "
    )
    view._create_room()
    assert view.client.created_rooms == []
    assert view.status_label.text == "Room name is required."


def test_room_creation_error_is_shown_on_dashboard():
    view = make_dashboard()

    view.handle_event({
        "type": "ROOM_RESPONSE",
        "status": "ERROR",
        "message": "A room with that name already exists.",
    })

    assert view.status_label.text == "A room with that name already exists."
