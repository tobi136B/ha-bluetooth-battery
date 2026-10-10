"""Tests für die HFP Auswertung (ohne Bluetooth Hardware)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bt_battery"))

from bt_battery.hfp import AG_FEATURES, HfpAgSession, parse_battery  # noqa: E402


def test_parse_biev_battery() -> None:
    report = parse_battery("AT+BIEV=2,73")
    assert report is not None and report.level == 73 and report.source == "hfp"


def test_parse_biev_other_indicator_is_ignored() -> None:
    assert parse_battery("AT+BIEV=1,1") is None


def test_parse_apple_battery() -> None:
    report = parse_battery("AT+IPHONEACCEV=2,1,6,2,0")
    assert report is not None and report.level == 70 and report.source == "apple"


def test_parse_apple_battery_second_key() -> None:
    report = parse_battery("AT+IPHONEACCEV=2,2,0,1,9")
    assert report is not None and report.level == 100


def test_parse_xevent_battery() -> None:
    report = parse_battery("AT+XEVENT=BATTERY,3,5,10,0")
    assert report is not None and report.level == 75


def test_parse_garbage() -> None:
    assert parse_battery("AT+BIEV=x") is None
    assert parse_battery("AT+IPHONEACCEV=1,1") is None


def test_service_level_connection_and_battery() -> None:
    reports = []
    session = HfpAgSession(reports.append)

    assert session.feed(b"AT+BRSF=959\r") == f"\r\n+BRSF: {AG_FEATURES}\r\n\r\nOK\r\n".encode()
    assert b"+CIND: (" in session.feed(b"AT+CIND=?\r")
    assert b"+CIND: 1,0,0,0,5,0,5" in session.feed(b"AT+CIND?\r")
    assert session.feed(b"AT+CMER=3,0,0,1\r") == b"\r\nOK\r\n"
    assert session.slc_established
    assert b"+BIND: (2)" in session.feed(b"AT+BIND=?\r")
    assert b"+XAPL=iPhone,6" in session.feed(b"AT+XAPL=05AC-1234-0100,10\r")

    # Zwei Befehle in einem Paket, einer davon über zwei Pakete verteilt
    session.feed(b"AT+IPHONEACCEV=1,1,4\rAT+BIE")
    session.feed(b"V=2,55\r")
    assert [r.level for r in reports] == [50, 55]


def test_audio_and_calls_are_rejected() -> None:
    session = HfpAgSession(lambda _: None)
    assert session.feed(b"AT+BCC\r") == b"\r\nERROR\r\n"
    assert session.feed(b"ATD123;\r") == b"\r\nERROR\r\n"
    assert session.feed(b"AT+VGS=10\r") == b"\r\nOK\r\n"
