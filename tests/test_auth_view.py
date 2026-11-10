"""Focused unit tests for the authentication view's event and submit logic."""

from __future__ import annotations

from unittest.mock import Mock

from gui.auth_view import AuthView


class FakeWidget:
    def __init__(self, value=""):
        self.value = value
        self.options = {}
        self.deleted = False

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def get(self):
        return self.value

    def delete(self, *_args):
        self.deleted = True
        self.value = ""


class FakeClient:
    def __init__(self, connected=True):
        self.is_connected = connected
        self.connection_state = "connected" if connected else "disconnected"
        self.username = None
        self.login = Mock()
        self.register = Mock()
        self.connect = Mock()


def make_view(*, mode="login", username="alice", password="Secret123"):
    # Bypass Tk construction so these behavioral tests also run on headless CI.
    view = object.__new__(AuthView)
    view.client = FakeClient()
    view.on_authenticated = Mock()
    view._mode = mode
    view._request_pending = False
    view._reconnect_after_failure = False
    view.username_entry = FakeWidget(username)
    view.password_entry = FakeWidget(password)
    view.feedback_label = FakeWidget()
    view.heading = FakeWidget()
    view.subtitle = FakeWidget()
    view.submit_button = FakeWidget()
    view.mode_button = FakeWidget()
    view.connection_label = FakeWidget()
    view.after = Mock()
    return view


def test_login_submits_through_shared_client():
    view = make_view()

    view._submit()

    view.client.login.assert_called_once_with("alice", "Secret123")
    assert view._request_pending is True
    assert view.submit_button.options["state"] == "disabled"


def test_registration_submits_through_shared_client():
    view = make_view(mode="register")

    view._submit()

    view.client.register.assert_called_once_with("alice", "Secret123")
    view.client.login.assert_not_called()


def test_empty_fields_are_rejected_without_network_request():
    view = make_view(username="", password="")

    view._submit()

    view.client.login.assert_not_called()
    assert "both" in view.feedback_label.options["text"].lower()


def test_login_success_calls_callback_with_authenticated_username():
    view = make_view()

    view.handle_event({"type": "LOGIN_RESPONSE", "status": "OK", "userId": "alice"})

    view.on_authenticated.assert_called_once_with("alice")
    assert view._request_pending is False


def test_login_error_displays_server_message_and_waits_for_disconnect():
    view = make_view()
    view._request_pending = True

    view.handle_event({
        "type": "LOGIN_RESPONSE", "status": "ERROR", "message": "Invalid credentials."
    })

    assert view.feedback_label.options["text"] == "Invalid credentials."
    assert view.feedback_label.options["foreground"] == "#b42318"
    assert view._reconnect_after_failure is True
    view.on_authenticated.assert_not_called()


def test_disconnection_after_failed_login_reconnects_via_client_api():
    view = make_view()
    view._reconnect_after_failure = True

    view.handle_event({"_event": "connection", "status": "disconnected"})

    view.after.assert_called_once_with(0, view._connect_if_disconnected)


def test_registration_error_displays_server_message():
    view = make_view(mode="register")

    view.handle_event({
        "type": "REGISTER_RESPONSE", "status": "ERROR", "message": "Username already exists."
    })

    assert view.feedback_label.options["text"] == "Username already exists."
    assert view.feedback_label.options["foreground"] == "#b42318"


def test_registration_success_clears_password_and_switches_to_login():
    view = make_view(mode="register")

    view.handle_event({
        "type": "REGISTER_RESPONSE", "status": "OK", "message": "Registration successful."
    })

    assert view.password_entry.deleted is True
    assert view._mode == "login"
    assert view.feedback_label.options["text"] == "Registration successful."


def test_legacy_zero_argument_app_callback_remains_compatible():
    view = make_view()
    callback = Mock()
    callback.__signature__ = __import__("inspect").Signature()
    view.on_authenticated = callback

    view._notify_authenticated("alice")

    callback.assert_called_once_with()
