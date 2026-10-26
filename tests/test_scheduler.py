from datetime import datetime

from bvb.scheduler import TZ, next_run


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_weekday_evening():
    # luni 2026-10-26 la 10:00 -> aceeasi zi la 19:15
    assert next_run(at(2026, 10, 26, 10, 0)) == (at(2026, 10, 26, 19, 15), ["daily"])


def test_after_run_moves_to_next_day():
    assert next_run(at(2026, 10, 26, 19, 15)) == (at(2026, 10, 27, 19, 15), ["daily"])


def test_friday_evening_then_saturday_full():
    assert next_run(at(2026, 10, 30, 20, 0)) == (at(2026, 10, 31, 10, 0), ["daily", "--full"])


def test_saturday_after_full_waits_for_monday():
    assert next_run(at(2026, 10, 31, 10, 0)) == (at(2026, 11, 2, 19, 15), ["daily"])


def test_utc_input_is_converted():
    # 17:00 UTC = 19:00 la Bucuresti (EET, dupa schimbarea orei din 25 octombrie)
    utc = datetime.fromisoformat("2026-10-26T17:00:00+00:00")
    assert next_run(utc)[0] == at(2026, 10, 26, 19, 15)
