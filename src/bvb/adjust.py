"""Preturi ajustate: pentru evenimente de capital si pentru dividende (total return).

Evenimente de capital (acțiuni gratuite, splituri, consolidari, majorari):
  le citim din seria ajustata a graficului BVB: unde raportul adj_close/close
  sare intre doua zile, BVB a aplicat un factor (ratio = k_azi / k_ieri).
  BVB nu ajusteaza (consecvent) pentru dividende cash; un salt care cade exact
  pe o data ex-dividend si nu are modificare de capital asociata e tratat ca
  dividend si scos, ca sa nu fie numarat de doua ori.
Dividende: factor P_ex / (P_ex + D) aplicat inainte de data ex, P_ex = prima
  inchidere de la data ex, D = dividend brut pe actiune; randamentul total din
  ziua ex devine (P_ex + D) / P_anterior.

  adj_close = close * cap_factor              (randament din pret)
  tr_close  = close * cap_factor * div_factor (randament total, dividende brute reinvestite)
"""

from datetime import date

import numpy as np
import pandas as pd

JUMP_TOL = 0.005          # variatie relativa minima a lui adj/close considerata eveniment
ADJ_TICK = 1e-4           # BVB rotunjeste preturile ajustate la 4 zecimale
CAPITAL_WINDOW_DAYS = 10  # data inregistrare capital la max. atatea zile de salt
DERIVED_MIN_RATIO = 0.05  # modificari de capital mai mici sunt ignorate la derivare
DERIVED_CONFIRM_TOL = 0.25  # saltul de pret trebuie sa fie in +/-25% din raportul actiunilor
DERIVED_CONFIRM_TOL_SUSPENDED = 0.5
SUSPENSION_DAYS = 20        # pauza de tranzactionare considerata suspendare
SUSPICIOUS_MOVE = 0.4       # variatie zilnica (si persistenta) raportata ca suspecta
SUSPICIOUS_PERSIST_DAYS = 5
T2_SINCE = date(2014, 10, 6)  # trecerea la decontare T+2: data ex = inregistrare - 1 zi lucratoare


def estimate_ex_date(record_date: date, trading_days: pd.DatetimeIndex) -> date | None:
    """Data ex estimata din data de inregistrare, pe calendarul zilelor de tranzactionare."""
    lag = 1 if record_date >= T2_SINCE else 2
    pos = trading_days.searchsorted(pd.Timestamp(record_date))  # prima zi >= record_date
    idx = pos - lag
    return trading_days[idx].date() if 0 <= idx < len(trading_days) else None


def capital_events(prices: pd.DataFrame, dividends: pd.DataFrame, capital: pd.DataFrame) -> pd.DataFrame:
    """Evenimente de capital: salturile din factorul BVB, clasificate 'capital' |
    'dividend' | 'unknown', plus 'capital_derived' din modificarile de capital neajustate de BVB.

    prices: date (index), close, bvb_adj (adj_close din graficul BVB)
    """
    valid = prices[["close", "bvb_adj"]].dropna()
    k = valid["bvb_adj"] / valid["close"]
    ratio = k / k.shift(1)
    # Pe preturi mici, rotunjirea lui bvb_adj produce variatii false ale lui k.
    rounding = 3 * ADJ_TICK / np.minimum(valid["bvb_adj"], valid["bvb_adj"].shift(1))
    jumps = ratio[(ratio - 1).abs() > np.maximum(JUMP_TOL, rounding)]

    ex_dates = set(dividends["ex_date"].dropna())
    cap_dates = [d for d in capital["record_date"].dropna()] if len(capital) else []
    jump_dates = [day.date() for day in jumps.index]
    rows = []
    for day, r in jumps.items():
        d = day.date()
        has_cap = any(abs((c - d).days) <= CAPITAL_WINDOW_DAYS for c in cap_dates)
        kind = "capital" if has_cap else ("dividend" if d in ex_dates else "unknown")
        rows.append({"date": d, "ratio": float(r), "kind": kind})

    # Modificari de capital pe care BVB nu le-a ajustat: raportul actiunilor,
    # acceptat doar daca saltul de pret din ziua ex il confirma.
    # Candidati pentru data ex: estimata din data de inregistrare si, pentru
    # consolidari cu suspendare, prima zi de tranzactionare dupa data modificarii.
    closes = prices["close"].dropna()
    for c in capital.itertuples():
        before, after = getattr(c, "shares_before", None), getattr(c, "shares_after", None)
        if not before or not after or pd.isna(before) or pd.isna(after):
            continue
        share_ratio = after / before
        if abs(share_ratio - 1) <= DERIVED_MIN_RATIO:
            continue
        anchors = [d for d in (c.record_date, getattr(c, "change_date", None)) if d is not None and pd.notna(d)]
        if any(abs((a - j).days) <= CAPITAL_WINDOW_DAYS for a in anchors for j in jump_dates):
            continue
        candidates = []
        if pd.notna(c.record_date):
            candidates.append(estimate_ex_date(c.record_date, closes.index))
        if len(anchors) == 2:
            candidates.append(anchors[1])
        for ex in candidates:
            if ex is None:
                continue
            pos = closes.index.searchsorted(pd.Timestamp(ex))
            if pos == 0 or pos >= len(closes):
                continue
            price_ratio = closes.iloc[pos - 1] / closes.iloc[pos]
            # Dupa o suspendare lunga pretul s-a putut misca si din cauza pietei.
            gap = (closes.index[pos] - closes.index[pos - 1]).days
            tol = DERIVED_CONFIRM_TOL_SUSPENDED if gap > SUSPENSION_DAYS else DERIVED_CONFIRM_TOL
            if abs(np.log(price_ratio / share_ratio)) <= np.log(1 + tol):
                rows.append({"date": closes.index[pos].date(), "ratio": float(share_ratio), "kind": "capital_derived"})
                break
    return pd.DataFrame(rows, columns=["date", "ratio", "kind"]).sort_values("date", ignore_index=True)


def adjust(prices: pd.DataFrame, dividends: pd.DataFrame, capital: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """-> (DataFrame cu close, cap_factor, div_factor, adj_close, tr_close; diagnostic)"""
    prices = prices.sort_index()
    days = prices.index
    events = capital_events(prices, dividends, capital)
    cap_events = events[events["kind"] != "dividend"]

    cap_factor = pd.Series(1.0, index=days)
    for e in cap_events.itertuples():
        cap_factor[days < pd.Timestamp(e.date)] /= e.ratio

    div_factor = pd.Series(1.0, index=days)
    skipped, used = 0, []
    for d in dividends.itertuples():
        ex = d.ex_date if pd.notna(d.ex_date) else (
            estimate_ex_date(d.record_date, days) if pd.notna(d.record_date) else None)
        if ex is None or not d.amount or d.amount <= 0:
            skipped += 1
            continue
        closes = prices["close"].dropna()
        before = closes[closes.index < pd.Timestamp(ex)]
        on_after = closes[closes.index >= pd.Timestamp(ex)]
        if before.empty or on_after.empty:
            skipped += 1
            continue
        # Randament total pe ziua ex: (P_ex + D) / P_anterior. Factorul
        # P_ex / (P_ex + D) e exact si pentru dividende mari fata de pret.
        p_ex = on_after.iloc[0] * cap_factor[on_after.index[0]] / cap_factor[before.index[-1]]
        m = p_ex / (p_ex + d.amount)
        div_factor[days < pd.Timestamp(ex)] *= m
        used.append({"ex_date": ex, "amount": d.amount, "prev_close": before.iloc[-1],
                     "yield": d.amount / before.iloc[-1]})

    out = pd.DataFrame({"close": prices["close"], "cap_factor": cap_factor, "div_factor": div_factor})
    out["adj_close"] = out["close"] * out["cap_factor"]
    out["tr_close"] = out["adj_close"] * out["div_factor"]

    # Salturi mari care persista in randamentul total = evenimente lipsa sau erori
    # de date (varfurile care revin in cateva zile sunt doar lipsa de lichiditate).
    tr = out["tr_close"]
    ret = tr / tr.shift(1) - 1
    persist = tr.shift(-SUSPICIOUS_PERSIST_DAYS) / tr.shift(1)
    suspicious = ret[(ret.abs() > SUSPICIOUS_MOVE) & (np.log(persist).abs() > np.log(1 + SUSPICIOUS_MOVE))]
    diag = {
        "events": events,
        "dividends_used": pd.DataFrame(used),
        "dividends_skipped": skipped,
        "suspicious_moves": [(i.date(), round(float(v), 3)) for i, v in suspicious.items()],
    }
    return out, diag


PRICES_SQL = """
SELECT p.date, p.close, h.adj_close AS bvb_adj
FROM prices p
LEFT JOIN prices_eod h ON h.symbol = p.symbol AND h.date = p.date AND h.source = 'bvb_hist'
WHERE p.symbol = ? AND p.close > 0
ORDER BY p.date
"""


def load(con, symbol: str):
    prices = con.execute(PRICES_SQL, [symbol]).df()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.set_index("date")
    dividends = con.execute(
        "SELECT ex_date, record_date, amount FROM dividends WHERE symbol = ?", [symbol]).df()
    for col in ("ex_date", "record_date"):
        dividends[col] = [d.date() if pd.notna(d) else None for d in pd.to_datetime(dividends[col])]
    capital = con.execute(
        "SELECT record_date, change_date, shares_before, shares_after FROM capital_changes WHERE symbol = ?",
        [symbol]).df()
    for col in ("record_date", "change_date"):
        capital[col] = [d.date() if pd.notna(d) else None for d in pd.to_datetime(capital[col])]
    return prices, dividends, capital


def run(con, symbols: list[str], log=print) -> pd.DataFrame:
    """Recalculeaza `prices_adj` si `adjust_events` pentru simboluri; intoarce un rezumat."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices_adj (
            date DATE, symbol VARCHAR, close DOUBLE, cap_factor DOUBLE, div_factor DOUBLE,
            adj_close DOUBLE, tr_close DOUBLE, PRIMARY KEY (date, symbol))
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS adjust_events (
            symbol VARCHAR, date DATE, kind VARCHAR, ratio DOUBLE)
    """)
    summary = []
    for symbol in symbols:
        prices, dividends, capital = load(con, symbol)
        if prices.empty:
            continue
        out, diag = adjust(prices, dividends, capital)
        out = out.reset_index().assign(symbol=symbol)
        con.execute("DELETE FROM prices_adj WHERE symbol = ?", [symbol])
        con.execute("DELETE FROM adjust_events WHERE symbol = ?", [symbol])
        con.register("_adj", out)
        con.execute("""INSERT INTO prices_adj SELECT date::DATE, symbol, close, cap_factor, div_factor,
                       adj_close, tr_close FROM _adj""")
        con.unregister("_adj")
        ev = diag["events"].assign(symbol=symbol)
        if len(ev):
            con.register("_ev", ev)
            con.execute("INSERT INTO adjust_events SELECT symbol, date, kind, ratio FROM _ev")
            con.unregister("_ev")
        kinds = diag["events"]["kind"].value_counts().to_dict()
        summary.append({
            "symbol": symbol,
            "days": len(out),
            "capital": kinds.get("capital", 0),
            "derived": kinds.get("capital_derived", 0),
            "dividend_jumps": kinds.get("dividend", 0),
            "unknown": kinds.get("unknown", 0),
            "dividends": len(diag["dividends_used"]),
            "div_skipped": diag["dividends_skipped"],
            "max_div_yield": round(float(diag["dividends_used"]["yield"].max()), 3) if len(diag["dividends_used"]) else np.nan,
            "suspicious": len(diag["suspicious_moves"]),
        })
    return pd.DataFrame(summary)
