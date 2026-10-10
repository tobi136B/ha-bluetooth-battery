"""
Minimale HFP Audio Gateway Gegenstelle (nur Steuerkanal, ohne Ton).

Ein Kopfhörer (Hands-Free, HF) baut nach dem Verbinden die "Service Level
Connection" per AT Befehlen auf. Wir antworten wie ein Telefon (Audio Gateway,
AG) und werten dabei die Akkumeldungen aus:

* HFP 1.7 HF Indikator:    AT+BIEV=2,<0..100>
* Apple Erweiterung:        AT+IPHONEACCEV=<n>,1,<0..9>,...
* Plantronics/Android:      AT+XEVENT=BATTERY,<stufe>,<anzahl stufen>,...

Die Klasse ist bewusst ohne Ein-/Ausgabe gebaut (sans-IO) und damit gut testbar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

LOG = logging.getLogger(__name__)

# AG Merkmale für AT+BRSF: Bit 8 erweiterte Fehlercodes, Bit 10 HF Indikatoren.
# Bewusst ohne Dreiwegegespräche und Codec Aushandlung, damit der Kopfhörer
# keine Audioverbindung erwartet.
AG_FEATURES = (1 << 8) | (1 << 10)

# HF Indikator Nummer 2 = Akkustand (Bluetooth SIG Assigned Numbers)
HF_INDICATOR_BATTERY = 2

# Indikatoren für AT+CIND (Reihenfolge ist für +CIND? relevant)
CIND_DEFINITION = (
    '("service",(0,1)),("call",(0,1)),("callsetup",(0-3)),("callheld",(0-2)),'
    '("signal",(0-5)),("roam",(0,1)),("battchg",(0-5))'
)
CIND_VALUES = "1,0,0,0,5,0,5"

# Apple Merkmale für +XAPL: Bit 1 Akkumeldung, Bit 2 Dockstatus
XAPL_FEATURES = (1 << 1) | (1 << 2)

OK = "OK"
ERROR = "ERROR"


@dataclass(frozen=True)
class BatteryReport:
    level: int
    source: str


def _clamp_percent(value: float) -> int:
    return max(0, min(100, round(value)))


def parse_battery(command: str) -> BatteryReport | None:
    """Liest einen Akkustand aus einem AT Befehl, sonst None."""
    upper = command.upper()
    try:
        if upper.startswith("AT+BIEV="):
            indicator, value = command[8:].split(",")[:2]
            if int(indicator) == HF_INDICATOR_BATTERY:
                return BatteryReport(_clamp_percent(int(value)), "hfp")
        elif upper.startswith("AT+IPHONEACCEV="):
            fields = command[15:].split(",")
            count = int(fields[0])
            for index in range(count):
                key, value = int(fields[1 + 2 * index]), int(fields[2 + 2 * index])
                if key == 1:
                    # Apple Stufen 0..9 entsprechen 10..100 %
                    return BatteryReport(_clamp_percent((value + 1) * 10), "apple")
        elif upper.startswith("AT+XEVENT=BATTERY,"):
            fields = command[18:].split(",")
            level, levels = int(fields[0]), int(fields[1])
            if levels > 1:
                return BatteryReport(_clamp_percent(level * 100 / (levels - 1)), "xevent")
    except (ValueError, IndexError):
        LOG.debug("Akkumeldung nicht lesbar: %s", command)
    return None


class HfpAgSession:
    """Beantwortet die AT Befehle eines Kopfhörers und meldet Akkustände."""

    def __init__(self, on_battery: Callable[[BatteryReport], None]) -> None:
        self._on_battery = on_battery
        self._buffer = ""
        self.hf_features = 0
        self.slc_established = False

    def feed(self, data: bytes) -> bytes:
        """Verarbeitet empfangene Bytes und liefert die Antwort an den Kopfhörer."""
        self._buffer += data.decode("ascii", errors="ignore")
        responses: list[str] = []
        # Befehle enden mit CR, manche Geräte schicken zusätzlich LF
        while "\r" in self._buffer:
            line, self._buffer = self._buffer.split("\r", 1)
            line = line.strip()
            if line:
                LOG.debug("HF -> AG: %s", line)
                responses.extend(self._handle(line))
        if not responses:
            return b""
        payload = "".join(f"\r\n{response}\r\n" for response in responses)
        LOG.debug("AG -> HF: %s", " | ".join(responses))
        return payload.encode("ascii")

    def _handle(self, command: str) -> list[str]:
        report = parse_battery(command)
        if report is not None:
            self._on_battery(report)
            return [OK]

        upper = command.upper()
        if upper.startswith("AT+BRSF="):
            try:
                self.hf_features = int(command[8:])
            except ValueError:
                pass
            return [f"+BRSF: {AG_FEATURES}", OK]
        if upper == "AT+CIND=?":
            return [f"+CIND: {CIND_DEFINITION}", OK]
        if upper == "AT+CIND?":
            return [f"+CIND: {CIND_VALUES}", OK]
        if upper.startswith("AT+CMER="):
            self.slc_established = True
            return [OK]
        if upper == "AT+CHLD=?":
            return ["+CHLD: (0,1,2,3)", OK]
        if upper == "AT+BIND=?":
            return [f"+BIND: ({HF_INDICATOR_BATTERY})", OK]
        if upper == "AT+BIND?":
            return [f"+BIND: {HF_INDICATOR_BATTERY},1", OK]
        if upper.startswith("AT+XAPL="):
            return [f"+XAPL=iPhone,{XAPL_FEATURES}", OK]
        if upper == "AT+COPS?":
            return ['+COPS: 0,0,"Home Assistant"', OK]
        # Alles, was eine Audioverbindung oder einen Anruf auslösen würde, ablehnen
        if upper.startswith(("ATD", "ATA", "AT+BCC", "AT+BVRA", "AT+BLDN")):
            return [ERROR]
        # Übrige Befehle (AT+BAC, AT+CLIP, AT+VGS, AT+NREC, ...) einfach bestätigen
        return [OK]
