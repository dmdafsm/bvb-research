"""Dashboard local (Streamlit). Pornire: `uv run bvb dashboard`.

Citeste copia `bvb_read.duckdb`, publicata la finalul fiecarei comenzi care scrie,
deci merge si in timpul colectarilor; cand apare o copie noua, se redeschide singur.
"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bvb import analytics, db, portfolio, risk, valuation
from bvb.config import READ_PATH

st.set_page_config(page_title="BVB Research", layout="wide")

if not READ_PATH.exists():
    st.error("Nu exista inca o copie a bazei pentru citire. Ruleaza o colectare (ex. `uv run bvb status`) "
             "sau `uv run bvb snapshot`.")
    st.stop()

VERSION = READ_PATH.stat().st_mtime  # cheia cache-urilor: se schimba la fiecare copie noua


@st.cache_resource
def _holder() -> dict:
    return {"version": None, "con": None}


def connection(version: float):
    """O singura conexiune pe proces; la o copie noua inchidem explicit conexiunea veche
    (DuckDB refoloseste instanta deschisa pentru aceeasi cale, deci n-ar vedea copia noua)."""
    h = _holder()
    if h["version"] != version:
        if h["con"] is not None:
            h["con"].close()
        h["con"] = db.connect(READ_PATH, read_only=True)
        h["version"] = version
    return h["con"]


con = connection(VERSION)


@st.cache_data(max_entries=1)
def instruments(version: float) -> pd.DataFrame:
    return con.execute("""
        SELECT symbol, name, market, sector, isin FROM instruments
        WHERE market <> 'INDEX' ORDER BY symbol""").df()


@st.cache_data(max_entries=1)
def watchlist(version: float) -> list[str]:
    return [r[0] for r in con.execute("SELECT symbol FROM watchlist ORDER BY symbol").fetchall()]


def pct(x, digits=1):
    return f"{x:.{digits}%}" if x == x and x is not None else "–"


def normalized_chart(series: dict[str, pd.Series], title: str, log: bool = False):
    fig = go.Figure()
    for name, s in series.items():
        s = s.dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(x=s.index, y=s / s.iloc[0] * 100, name=name, mode="lines"))
    fig.update_layout(title=title, height=420, margin=dict(l=10, r=10, t=40, b=10),
                      yaxis_type="log" if log else "linear", legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)


# --- pagini ----------------------------------------------------------------------

def page_stock():
    inst = instruments(VERSION)
    labels = {r.symbol: f"{r.symbol} — {r.name}" for r in inst.itertuples()}
    default = watchlist(VERSION)[0] if watchlist(VERSION) else "TLV"
    symbol = st.sidebar.selectbox("Emitent", list(labels), index=list(labels).index(default) if default in labels else 0,
                                  format_func=labels.get)
    years = st.sidebar.select_slider("Perioada grafic (ani)", options=[1, 3, 5, 10, 20, 30], value=5)

    try:
        rep = analytics.stock_report(con, symbol)
    except ValueError as e:
        st.warning(str(e))
        return
    i = rep["info"]
    st.title(f"{symbol} — {i['name']}")
    st.caption(f"{i['isin']} · {i['market']} · {i['segment']} {i['category']} · {i['activity']}")
    c = st.columns(5)
    c[0].metric("Ultimul pret", f"{i['last_close']}", help=str(i["last_date"]))
    c[1].metric("Capitalizare", f"{i['market_cap'] / 1e6:,.0f} mil." if i["market_cap"] else "–")
    c[2].metric("Randament dividend 12 luni", pct(i["div_yield_12m"]))
    c[3].metric("Zile cu tranzactii (1 an)", pct(i["pct_days_traded_1y"], 0))
    c[4].metric("Valoare medie zilnica", f"{i['adv_value_1y'] / 1e3:,.0f} mii")

    start = date.today() - timedelta(days=365 * years)
    tr = analytics.series(con, [symbol], start=start)[symbol]
    px = analytics.series(con, [symbol], field="adj_close", start=start)[symbol]
    bench = analytics.benchmark_series(con, start=start)
    normalized_chart({f"{symbol} randament total": tr, f"{symbol} pret ajustat": px, "BET-TR": bench},
                     "Evolutie (baza 100)", log=years >= 10)

    w = rep["windows"].T
    show = pd.DataFrame({
        "Randament total/an": w["cagr"].map(pct), "Pret/an": w["price_cagr"].map(pct),
        "BET-TR/an": w["bench_cagr"].map(pct), "Volatilitate": w["volatility"].map(pct),
        "Sharpe": w["sharpe"].map(lambda x: f"{x:.2f}"), "Max drawdown": w["max_drawdown"].map(pct),
        "Beta": w["beta"].map(lambda x: f"{x:.2f}"),
    })
    st.subheader("Randament si risc")
    st.dataframe(show, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Date financiare (individuale)")
        f = valuation.fundamentals(con, symbol)
        if f.empty:
            st.info("Nu exista situatii financiare pe data.gov.ro pentru acest CUI.")
        else:
            f = f.tail(8)
            tbl = pd.DataFrame({
                "Cifra afaceri (mil.)": f["revenue"] / 1e6, "Profit net (mil.)": f["net_profit"] / 1e6,
                "Capitaluri (mil.)": f["equity"] / 1e6, "ROE": f["roe"].map(pct), "Marja neta": f["net_margin"].map(pct),
                "Datorii/capitaluri": f["debt_to_equity"].round(2), "Payout": f["payout"].map(pct),
            }).T
            st.dataframe(tbl, use_container_width=True)
            m = valuation.current_multiples(con, [symbol])
            if len(m):
                r = m.iloc[0]
                st.caption(f"Exercitiul {r['fiscal_year']}: P/E {r['pe']:.1f} · P/B {r['pb']:.2f} · "
                           f"P/S {r['ps']:.2f} · P/E vs. ultimii 10 ani: percentila {pct(r['pe_pctile_10y'], 0)}")
            hist = valuation.multiples_history(con, symbol)
            if len(hist):
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=hist.index, y=hist["pe"], name="P/E"))
                fig.add_trace(go.Scatter(x=hist.index, y=hist["pb"], name="P/B", yaxis="y2"))
                fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10), title="Multipli istorici",
                                  yaxis2=dict(overlaying="y", side="right"), legend=dict(orientation="h"))
                st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Dividende")
        st.dataframe(rep["dividends"], use_container_width=True, hide_index=True)
        st.subheader("Calendar")
        cal = con.execute("SELECT date, kind, event FROM calendar WHERE symbol = ? AND date >= current_date "
                          "ORDER BY date", [symbol]).df()
        st.dataframe(cal, use_container_width=True, hide_index=True)

    st.subheader("Rapoarte curente")
    cats = ["toate"] + [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM reports WHERE symbol = ? ORDER BY 1", [symbol]).fetchall()]
    cat = st.selectbox("Categorie", cats)
    rows = con.execute(
        "SELECT published, category, title, url_ro FROM reports WHERE symbol = ? AND (? = 'toate' OR category = ?) "
        "ORDER BY published DESC LIMIT 100", [symbol, cat, cat]).df()
    st.dataframe(rows, use_container_width=True, hide_index=True,
                 column_config={"url_ro": st.column_config.LinkColumn("PDF")})
    st.subheader("Stiri")
    news = con.execute("SELECT published, source, title, url FROM news WHERE list_contains(symbols, ?) "
                       "ORDER BY published DESC LIMIT 30", [symbol]).df()
    st.dataframe(news, use_container_width=True, hide_index=True,
                 column_config={"url": st.column_config.LinkColumn("Link")})


@st.cache_data(max_entries=8)
def screen_table(market: str, years: int, version: float) -> pd.DataFrame:
    df = analytics.screen(con, market, years)
    val = valuation.current_multiples(con, list(df.index))
    if len(val):
        df = df.join(val[["pe", "pb", "roe", "net_margin", "debt_to_equity", "pe_pctile_10y"]])
    return df


def page_screen():
    st.title("Screener")
    market = st.sidebar.selectbox("Piata", ["REGS", "XRS1", "XRSI"])
    years = st.sidebar.select_slider("Fereastra (ani)", options=[1, 3, 5, 10], value=3)
    min_traded = st.sidebar.slider("Minim zile cu tranzactii (1 an)", 0.0, 1.0, 0.8, 0.05)
    df = screen_table(market, years, VERSION)
    df = df[df["pct_days_traded"].fillna(0) >= min_traded]
    st.caption(f"{len(df)} actiuni · randament total vs BET-TR · multipli pe ultimul exercitiu (situatii individuale)")
    pct_cols = ["cagr", "volatility", "max_drawdown", "div_yield", "pct_days_traded", "roe", "net_margin", "pe_pctile_10y"]
    st.dataframe(df.style.format({c: "{:.1%}" for c in pct_cols if c in df} |
                                 {c: "{:,.2f}" for c in df.columns if c not in pct_cols}, na_rep="–"),
                 use_container_width=True, height=700)


def page_portfolio():
    st.title("Portofoliu")
    text = st.sidebar.text_input("Ponderi", value=", ".join(f"{s}" for s in watchlist(VERSION)[:5]) or "TLV, SNP, H2O")
    value = st.sidebar.number_input("Valoare (RON)", value=100_000, step=10_000)
    start = st.sidebar.date_input("Start backtest", value=date(2020, 1, 1))
    rebalance = st.sidebar.selectbox("Rebalansare", ["none", "monthly", "quarterly", "yearly"], index=2)
    fee = st.sidebar.number_input("Comision", value=0.0025, step=0.0005, format="%.4f")
    weights = portfolio.parse_weights(text)
    if not weights:
        st.info("Introdu simboluri, ex. 'TLV=0.4, SNP=0.3, H2O=0.3'.")
        return
    try:
        res = portfolio.backtest(con, portfolio.Config(weights=weights, start=start, capital=value,
                                                       rebalance=rebalance, fee=fee))
    except ValueError as e:
        st.error(str(e))
        return
    for n in res.notes:
        st.warning(n)
    m = res.metrics
    c = st.columns(5)
    c[0].metric("Valoare finala", f"{m['final_value']:,.0f}")
    c[1].metric("CAGR", pct(m["cagr"]))
    c[2].metric("Volatilitate", pct(m["volatility"]))
    c[3].metric("Max drawdown", pct(m["max_drawdown"]))
    c[4].metric("Sharpe", f"{m['sharpe']:.2f}")
    st.caption(f"BET-TR: valoare finala {res.benchmark.iloc[-1]:,.0f} · CAGR {pct(m['bench_cagr'])} · "
               f"volatilitate {pct(m['bench_volatility'])} · max drawdown {pct(m['bench_max_drawdown'])}")
    normalized_chart({"Portofoliu": res.nav, "BET-TR": res.benchmark}, "Backtest (baza 100)")
    st.dataframe(portfolio.yearly_returns(res).map(pct), use_container_width=True)

    st.header("Risc (ultimii 3 ani)")
    try:
        r = risk.report(con, weights, value=value)
    except ValueError as e:
        st.warning(str(e))
        return
    v = r.var.copy()
    v.index = [f"{x:.0%}" for x in v.index]
    st.dataframe(v.style.format({c: "{:.2%}" for c in v.columns if not c.endswith("_ron")} |
                                {c: "{:,.0f}" for c in v.columns if c.endswith("_ron")}), use_container_width=True)
    st.dataframe(r.positions.style.format({"weight": "{:.1%}", "volatility": "{:.1%}", "beta_weekly": "{:.2f}",
                                           "risk_contribution": "{:.1%}", "pct_days_traded": "{:.0%}",
                                           "days_to_liquidate": "{:.1f}"}), use_container_width=True)
    left, right = st.columns(2)
    with left:
        st.subheader("Corelatii (saptamanal)")
        st.dataframe(r.correlation.style.format("{:.2f}"))
    with right:
        st.subheader("Scenarii de stres")
        st.dataframe(r.stress.style.format({"portfolio": "{:.1%}", "benchmark": "{:.1%}"}), hide_index=True)
    cc = r.concentration
    st.caption(f"HHI {cc['hhi']:.3f} (≈{cc['effective_n']:.1f} pozitii) · stat ≥50%: {pct(cc['state_controlled'], 0)} · "
               f"vandabil in 1/5/20 zile: {pct(cc['liquidatable_1d'], 0)} / {pct(cc['liquidatable_5d'], 0)} / "
               f"{pct(cc['liquidatable_20d'], 0)}")


def page_events():
    st.title("Calendar si anunturi")
    only_watch = st.sidebar.checkbox("Doar lista de urmarire", value=bool(watchlist(VERSION)))
    days = st.sidebar.slider("Zile", 7, 90, 30)
    cond = "symbol IN (SELECT symbol FROM watchlist)" if only_watch else "1=1"
    st.subheader("Urmeaza")
    st.dataframe(con.execute(f"""
        SELECT date, symbol, kind, event FROM calendar WHERE {cond} AND date BETWEEN current_date AND current_date + ?
        UNION ALL
        SELECT ex_date, symbol, 'ex-dividend', 'Dividend ' || amount FROM dividends
        WHERE {cond} AND ex_date BETWEEN current_date AND current_date + ?
        ORDER BY 1, 2""", [days, days]).df(), use_container_width=True, hide_index=True)
    st.subheader("Anunturi recente")
    st.dataframe(con.execute(f"""
        SELECT published, symbol, category, title, url_ro FROM reports
        WHERE {cond} AND published > now() - to_days(?) ORDER BY published DESC LIMIT 300""", [days]).df(),
        use_container_width=True, hide_index=True, column_config={"url_ro": st.column_config.LinkColumn("PDF")})
    st.subheader("Stiri")
    st.dataframe(con.execute(f"""
        SELECT published, array_to_string(symbols, ',') AS symbols, title, url FROM news
        WHERE len(symbols) > 0 AND {'list_has_any(symbols, (SELECT list(symbol) FROM watchlist))' if only_watch else '1=1'}
          AND published > now() - to_days(?) ORDER BY published DESC""", [days]).df(),
        use_container_width=True, hide_index=True, column_config={"url": st.column_config.LinkColumn("Link")})


PAGES = {"Emitent": page_stock, "Screener": page_screen, "Portofoliu": page_portfolio, "Calendar si anunturi": page_events}
choice = st.sidebar.radio("Pagina", list(PAGES))
PAGES[choice]()
from datetime import datetime as _dt

st.sidebar.caption(f"Date actualizate: {_dt.fromtimestamp(VERSION):%d.%m.%Y %H:%M}")
st.sidebar.caption("Date: bvb.ro (uz personal), data.gov.ro (CC-BY 4.0). Nu reprezinta recomandari de investitii.")
