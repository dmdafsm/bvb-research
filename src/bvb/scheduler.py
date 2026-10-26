"""Programarea rularilor in containerul de ingestie (ADR 0004).

Un singur proces care porneste comenzile una dupa alta, deci o singura
conexiune de scriere la DuckDB. Fiecare comanda ruleaza in propriul proces,
ca sa publice copia pentru citire la final.

Ceasul se verifica la fiecare minut (nu un singur sleep lung), ca o rulare
ratata cat timp calculatorul a dormit sa porneasca la trezire.
"""

import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")

# (zile ale saptamanii, 0 = luni; ora; minut; argumente bvb)
JOBS = [
    ((0, 1, 2, 3, 4), 19, 15, ["daily"]),  # dupa inchiderea sedintei (18:30) si publicarea sumarului
    ((5,), 10, 0, ["daily", "--full"]),  # sambata: istoric grafic, indici, fise emitenti
]
POLL_SECONDS = 60


def next_run(now: datetime, jobs=JOBS) -> tuple[datetime, list[str]]:
    """Urmatoarea rulare strict dupa `now`."""
    now = now.astimezone(TZ)
    best = None
    for days, hour, minute, args in jobs:
        for offset in range(8):
            day = (now + timedelta(days=offset)).date()
            if day.weekday() not in days:
                continue
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)
            if at > now:
                if best is None or at < best[0]:
                    best = (at, args)
                break
    if best is None:
        raise ValueError("Nicio rulare programata.")
    return best


def run(args: list[str], log=print) -> int:
    bvb = Path(sys.executable).with_name("bvb")
    log(f"{datetime.now(TZ):%Y-%m-%d %H:%M} porneste: bvb {' '.join(args)}")
    code = subprocess.run([str(bvb), *args], check=False).returncode
    log(f"{datetime.now(TZ):%Y-%m-%d %H:%M} gata: bvb {' '.join(args)} (cod {code})")
    return code


def loop(log=print) -> None:
    at, args = next_run(datetime.now(TZ))
    log(f"Urmatoarea rulare: {at:%a %Y-%m-%d %H:%M} bvb {' '.join(args)}")
    while True:
        time.sleep(POLL_SECONDS)
        now = datetime.now(TZ)
        if now < at:
            continue
        run(args, log)
        at, args = next_run(datetime.now(TZ))
        log(f"Urmatoarea rulare: {at:%a %Y-%m-%d %H:%M} bvb {' '.join(args)}")
