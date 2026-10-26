from datetime import date

import pandas as pd
import pytest

from bvb.adjust import adjust, capital_events, estimate_ex_date


def make_prices(closes, bvb_adj):
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame({"close": closes, "bvb_adj": bvb_adj}, index=idx)


NO_DIV = pd.DataFrame({"ex_date": [], "record_date": [], "amount": []})
NO_CAP = pd.DataFrame({"record_date": [], "change_date": []})


def test_bonus_shares_from_bvb_factor():
    # Actiuni gratuite 1:1 in ziua 3: pretul se injumatateste, BVB ajusteaza istoricul.
    prices = make_prices([10, 10, 5, 5], [5, 5, 5, 5])
    capital = pd.DataFrame({"record_date": [date(2024, 1, 4)], "change_date": [date(2024, 1, 5)]})
    out, diag = adjust(prices, NO_DIV, capital)
    assert list(out["adj_close"]) == [5, 5, 5, 5]
    assert list(diag["events"]["kind"]) == ["capital"]
    assert diag["suspicious_moves"] == []


def test_consolidation_raises_old_prices():
    prices = make_prices([2, 2, 20, 20], [20, 20, 20, 20])
    out, _ = adjust(prices, NO_DIV, NO_CAP)
    assert list(out["adj_close"]) == pytest.approx([20, 20, 20, 20])


def test_dividend_total_return():
    prices = make_prices([10, 10, 9, 9], [10, 10, 9, 9])
    divs = pd.DataFrame({"ex_date": [date(2024, 1, 3)], "record_date": [date(2024, 1, 4)], "amount": [1.0]})
    out, diag = adjust(prices, divs, NO_CAP)
    assert list(out["adj_close"]) == [10, 10, 9, 9]           # pretul nu se ajusteaza
    assert list(out["tr_close"]) == pytest.approx([9, 9, 9, 9])  # randament total 0 pe ziua ex
    assert diag["dividends_used"].loc[0, "yield"] == pytest.approx(0.1)


def test_bvb_dividend_jump_not_double_counted():
    # BVB a ajustat si pentru dividend (salt pe data ex, fara modificare de capital).
    prices = make_prices([10, 10, 9, 9], [9, 9, 9, 9])
    divs = pd.DataFrame({"ex_date": [date(2024, 1, 3)], "record_date": [None], "amount": [1.0]})
    events = capital_events(prices, divs, NO_CAP)
    assert list(events["kind"]) == ["dividend"]
    out, _ = adjust(prices, divs, NO_CAP)
    assert list(out["adj_close"]) == [10, 10, 9, 9]
    assert list(out["tr_close"]) == pytest.approx([9, 9, 9, 9])


def test_estimate_ex_date_t2_and_t3():
    days = pd.bdate_range("2014-09-01", "2014-10-31")
    assert estimate_ex_date(date(2014, 10, 15), days) == date(2014, 10, 14)  # T+2: o zi inainte
    assert estimate_ex_date(date(2014, 9, 17), days) == date(2014, 9, 15)    # T+3: doua zile inainte


def test_capital_change_missed_by_bvb_is_derived_when_price_confirms():
    # 1 -> 2 actiuni, BVB nu a ajustat; pretul se injumatateste pe data ex.
    prices = make_prices([10, 10, 5, 5], [10, 10, 5, 5])
    capital = pd.DataFrame({"record_date": [date(2024, 1, 4)], "change_date": [None],
                            "shares_before": [100], "shares_after": [200]})
    out, diag = adjust(prices, NO_DIV, capital)
    assert list(diag["events"]["kind"]) == ["capital_derived"]
    assert list(out["adj_close"]) == pytest.approx([5, 5, 5, 5])


def test_capital_change_not_derived_without_price_confirmation():
    prices = make_prices([10, 10, 10, 10], [10, 10, 10, 10])
    capital = pd.DataFrame({"record_date": [date(2024, 1, 4)], "change_date": [None],
                            "shares_before": [100], "shares_after": [200]})
    out, diag = adjust(prices, NO_DIV, capital)
    assert diag["events"].empty
    assert list(out["adj_close"]) == [10, 10, 10, 10]


def test_large_special_dividend_total_return():
    # FP 2023: dividend 1,7225 la pret 1,984; a doua zi 0,381 -> randament total ~ +6%.
    prices = make_prices([1.984, 0.381], [1.984, 0.381])
    divs = pd.DataFrame({"ex_date": [date(2024, 1, 2)], "record_date": [None], "amount": [1.7225]})
    out, _ = adjust(prices, divs, NO_CAP)
    assert out["tr_close"].iloc[1] / out["tr_close"].iloc[0] == pytest.approx((0.381 + 1.7225) / 1.984)


def test_consolidation_after_suspension_uses_change_date():
    # Inregistrare mult inainte, tranzactionarea reia dupa data modificarii (BRD 2005).
    prices = make_prices([5, 5, 5, 10, 10], [5, 5, 5, 10, 10])
    capital = pd.DataFrame({"record_date": [date(2023, 12, 1)], "change_date": [date(2024, 1, 4)],
                            "shares_before": [200], "shares_after": [100]})
    out, diag = adjust(prices, NO_DIV, capital)
    assert list(diag["events"]["kind"]) == ["capital_derived"]
    assert list(out["adj_close"]) == pytest.approx([10, 10, 10, 10, 10])
