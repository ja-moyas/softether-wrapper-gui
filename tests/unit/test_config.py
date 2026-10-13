from PySide6.QtCore import QSettings

from softether_wrapper.config import ConfigStore, Preferences


def _store(tmp_path):
    settings = QSettings(str(tmp_path / "config.ini"), QSettings.Format.IniFormat)
    return ConfigStore(settings)


def test_defaults(tmp_path):
    prefs = _store(tmp_path).load()
    assert prefs.monitor_interval_ms == 3000
    assert prefs.notifications is True
    assert prefs.tap_interface == "vpn_vpn0"


def test_roundtrip(tmp_path):
    store = _store(tmp_path)
    original = Preferences(
        monitor_interval_ms=5000,
        notifications=False,
        hide_on_close=False,
        autostart=False,
        default_account="MyVPN",
        tap_interface="vpn_vpn1",
        show_ip=False,
        helper_retry_ms=7000,
    )
    store.save(original)
    loaded = store.load()
    assert loaded.monitor_interval_ms == 5000
    assert loaded.notifications is False
    assert loaded.default_account == "MyVPN"
    assert loaded.tap_interface == "vpn_vpn1"
    assert loaded.show_ip is False
    assert loaded.helper_retry_ms == 7000
