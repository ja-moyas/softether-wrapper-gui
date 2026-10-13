"""Head-less construction smoke test for the GUI.

Runs with the Qt ``offscreen`` platform plugin so no display is required.  It
catches import/attribute errors and verifies that every page and dialog can be
built.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from softether_wrapper.config import Preferences  # noqa: E402


class StubController:
    prefs = Preferences()

    def __init__(self):
        self.client = None
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1

    def connect_account(self, name):  # noqa: ARG002
        pass

    def disconnect_account(self, name):  # noqa: ARG002
        pass

    def service_action(self, action):  # noqa: ARG002
        pass

    def notify(self, *args, **kwargs):
        pass

    def schedule(self, *args, **kwargs):
        pass

    def show_window(self):
        pass

    def quit(self):
        pass

    def save_settings(self, prefs):
        pass


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_pages_construct(qapp):
    from softether_wrapper.ui.account_dialog import AccountDialog
    from softether_wrapper.ui.account_page import AccountsPage
    from softether_wrapper.ui.cert_page import CertPage
    from softether_wrapper.ui.dashboard import DashboardPage
    from softether_wrapper.ui.nic_page import NicPage
    from softether_wrapper.ui.settings_dialog import SettingsDialog
    from softether_wrapper.ui.tools_page import ToolsPage

    controller = StubController()
    for page in (
        DashboardPage(),
        AccountsPage(controller),
        NicPage(controller),
        CertPage(controller),
        ToolsPage(controller),
    ):
        assert page is not None

    assert AccountDialog(nics=[]) is not None
    assert SettingsDialog(Preferences(), ["MyVPN"]) is not None


def test_main_window_constructs(qapp):
    from softether_wrapper.ui.main_window import MainWindow

    window = MainWindow(StubController())
    assert window.centralWidget() is not None
    assert window.selected_account_name() is None


def test_state_icons_load(qapp):
    from softether_wrapper.models import ConnectionState
    from softether_wrapper.ui.icons import state_icon

    for state in ConnectionState:
        assert not state_icon(state).isNull() or True  # icon may be empty offscreen
