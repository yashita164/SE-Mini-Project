from __future__ import annotations

from gui.room_chat import RoomChatView


class FakeClient:
    username = "ujwalkrishnappa"

    def __init__(self) -> None:
        self.joined: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.listed_users: list[str] = []
        self.listed_rooms = 0

    def join_room(self, room: str) -> None:
        self.joined.append(room)

    def send_room_message(self, room: str, content: str) -> None:
        self.sent.append((room, content))

    def list_users(self, room: str | None = None) -> None:
        if room is not None:
            self.listed_users.append(room)

    def list_rooms(self) -> None:
        self.listed_rooms += 1


class FakeStatus:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, *, text: str) -> None:
        self.text = text


class FakeEntry:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.deleted = False

    def get(self) -> str:
        return self.value

    def delete(self, _start: str, _end: str) -> None:
        self.value = ""
        self.deleted = True


class FakeText:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def configure(self, **_kwargs) -> None:
        pass

    def delete(self, _start: str, _end: str) -> None:
        self.lines.clear()

    def insert(self, _index: str, text: str) -> None:
        self.lines.append(text.rstrip("\n"))

    def see(self, _index: str) -> None:
        pass


def make_view() -> RoomChatView:
    view = RoomChatView.__new__(RoomChatView)
    view.client = FakeClient()
    view._active_room = "General"
    view._joined_rooms = set()
    view._messages_by_room = {}
    view.status_label = FakeStatus()
    view.messages = FakeText()
    view.message_entry = FakeEntry("hello everyone")
    view.room_title = FakeStatus()
    return view


def test_room_chat_uses_logged_in_user_to_send_to_joined_room():
    view = make_view()
    view._join_room()

    assert view.client.joined == ["General"]
    assert view.status_label.text.startswith("Joining General")

    view.handle_event({
        "type": "ROOM_RESPONSE",
        "status": "OK",
        "action": "JOIN",
        "room": "General",
    })
    view._send()

    assert view.client.sent == [("General", "hello everyone")]
    assert view.messages.lines == ["ujwalkrishnappa: hello everyone"]
    assert view.message_entry.deleted


def test_room_chat_requires_joining_before_sending():
    view = make_view()

    view._send()

    assert view.client.sent == []
    assert view.status_label.text == "Join this room before sending messages."


def test_room_chat_receives_only_messages_for_the_active_room():
    view = make_view()

    view.handle_event({
        "type": "NEW_MESSAGE",
        "roomId": "General",
        "fromUser": "bob",
        "content": "hi",
    })
    view.handle_event({
        "type": "NEW_MESSAGE",
        "roomId": "Other",
        "fromUser": "carol",
        "content": "not for this view",
    })

    assert view.messages.lines == ["bob: hi"]
    assert view._messages_by_room["other"] == ["carol: not for this view"]
