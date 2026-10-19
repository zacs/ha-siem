"""Plain-text alert titles and bodies."""

from custom_components.siem.core.messages import alert_message, alert_title, timeline_line


def test_alert_message_keeps_the_latest_lines():
    assert alert_title("verify", None) == "SIEM verify: the house"
    assert alert_title("alarm", "Kitchen") == "SIEM alarm: Kitchen"
    assert timeline_line("14:02", "Back Door", "An exterior door or window opened", 40) == "14:02 Back Door: An exterior door or window opened (+40)"
    assert timeline_line("14:05", "Alice arrived home", None, -60) == "14:05 Alice arrived home (-60)"
    lines = [f"line {i}" for i in range(8)]
    assert alert_message(41.6, "vacant", lines).splitlines() == ["Score 42, house vacant.", "line 3", "line 4", "line 5", "line 6", "line 7"]
    assert alert_message(20, "guest", [], again=True) == "Score 20, house guest, score doubled since the last alert."
