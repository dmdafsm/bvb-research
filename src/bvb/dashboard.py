"""Dashboard local (Streamlit). Pornire: `uv run bvb dashboard`.

Citeste copia `bvb_read.duckdb`, publicata la finalul fiecarei comenzi care scrie,
deci merge si in timpul colectarilor; cand apare o copie noua, se redeschide singur.
"""

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bvb import analytics, db, learning, portfolio, risk, valuation
from bvb.config import READ_PATH

st.set_page_config(page_title="BVB Research", page_icon=":material/monitoring:", layout="wide")

if not READ_PATH.exists():
    st.error(
        "Nu exista inca o copie a bazei pentru citire. Ruleaza o colectare (ex. `uv run bvb status`) "
        "sau `uv run bvb snapshot`."
    )
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


TIERS = {  # (segment, categorie) din fisa emitentului -> piata afisata
    ("Principal", "Premium"): "Principal Premium",
    ("Principal", "Standard"): "Principal Standard",
    ("Principal", "Int'l"): "Internațional",
    ("SMT", "AeRO Premium"): "AeRO Premium",
    ("SMT", "AeRO Standard"): "AeRO Standard",
    ("SMT", "AeRO Baza"): "AeRO Standard",
    ("SMT", "Intl-SMT"): "Internațional",
}


@st.cache_data(max_entries=1)
def instruments(version: float) -> pd.DataFrame:
    df = con.execute("""
        SELECT i.symbol, i.name, i.market, i.segment, i.category, i.sector, i.isin,
               i.market = 'DELISTED' AS delisted, p.last_trade
        FROM instruments i
        LEFT JOIN (SELECT symbol, max(date) AS last_trade FROM prices_eod GROUP BY 1) p USING (symbol)
        WHERE i.market <> 'INDEX' ORDER BY i.symbol""").df()
    df["tier"] = [
        "Delistate" if d else TIERS.get((s, c), "Altele")
        for d, s, c in zip(df["delisted"], df["segment"], df["category"], strict=True)
    ]
    df["sector"] = df["sector"].fillna("Nespecificat").str.capitalize()
    return df


@st.cache_data(max_entries=1)
def watchlist(version: float) -> list[str]:
    return [r[0] for r in con.execute("SELECT symbol FROM watchlist ORDER BY symbol").fetchall()]


def pct(x, digits=1):
    return f"{x:.{digits}%}" if x == x and x is not None else "–"


def static_table(df: pd.DataFrame, fmt=None, hide_index: bool = False) -> None:
    """Tabel mic, fara sortare, randat ca HTML (st.table): capetele au marimea textului,
    spre deosebire de grila st.dataframe."""
    sty = df.style.format(fmt, na_rep="–") if fmt else df.style.format(na_rep="–")
    if hide_index:
        sty = sty.hide(axis="index")
    st.table(sty)


def ron(x) -> str:
    """Suma scurta pentru carduri: 22.6 mld. / 2.8 mil. / 950.4 mii (ca restul cifrelor din pagina)."""
    if x is None or x != x:
        return "–"
    for div, unit in ((1e9, "mld."), (1e6, "mil."), (1e3, "mii")):
        if abs(x) >= div:
            return f"{x / div:,.1f} {unit}"
    return f"{x:,.0f}"


def normalized_chart(series: dict[str, pd.Series], title: str, log: bool = False):
    fig = go.Figure()
    for name, s in series.items():
        s = s.dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(x=s.index, y=s / s.iloc[0] * 100, name=name, mode="lines", line=dict(width=2)))
    st.subheader(title)
    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified",
        yaxis_type="log" if log else "linear",
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True)


# --- pagini ----------------------------------------------------------------------


def pick_issuer() -> str | None:
    """Filtre in bara laterala, apoi alegerea emitentului din lista ramasa."""
    inst = instruments(VERSION)
    watch = watchlist(VERSION)
    status = st.sidebar.segmented_control("Emitenti", ["Listati", "Delistati", "Toti"], default="Listati") or "Listati"
    if status == "Listati":
        inst = inst[~inst["delisted"]]
    elif status == "Delistati":
        inst = inst[inst["delisted"]].sort_values("last_trade", ascending=False)
    if watch and st.sidebar.toggle("Doar lista de urmarire"):
        inst = inst[inst["symbol"].isin(watch)]
    if status == "Listati":
        tiers = [t for t in dict.fromkeys(TIERS.values()) if t in set(inst["tier"])]
        chosen = st.sidebar.multiselect("Piata", tiers, placeholder="Toate pietele")
        if chosen:
            inst = inst[inst["tier"].isin(chosen)]
        sectors = sorted(inst["sector"].unique())
        chosen = st.sidebar.multiselect("Sector", sectors, placeholder="Toate sectoarele")
        if chosen:
            inst = inst[inst["sector"].isin(chosen)]
    elif status == "Delistati" and len(inst):
        first, last = int(inst["last_trade"].min().year), int(inst["last_trade"].max().year)
        since = st.sidebar.slider("Ultima tranzactie din", first, last, max(first, last - 10))
        inst = inst[inst["last_trade"].dt.year >= since]

    if inst.empty:
        st.sidebar.warning("Niciun emitent pentru filtrele alese.")
        return None
    labels = {
        r.symbol: f"{r.symbol} — {r.name}" + (f" (delistat {r.last_trade:%Y})" if r.delisted else "")
        for r in inst.itertuples()
    }
    options = list(labels)
    default = next((s for s in [*watch, "TLV"] if s in labels), options[0])
    st.sidebar.caption(f"{len(options)} emitenti")
    return st.sidebar.selectbox("Emitent", options, index=options.index(default), format_func=labels.get)


def page_stock():
    symbol = pick_issuer()
    if symbol is None:
        return
    years = st.sidebar.select_slider("Perioada grafic (ani)", options=[1, 3, 5, 10, 20, 30], value=5)

    try:
        rep = analytics.stock_report(con, symbol)
    except ValueError as e:
        st.warning(str(e))
        return
    i = rep["info"]
    st.title(f"{symbol} — {i['name']}")
    tier = " ".join(x for x in (i["segment"], i["category"]) if x)
    st.caption(" · ".join(x for x in (i["isin"], i["market"], tier, i["activity"]) if x))
    c = st.columns(5)
    c[0].metric("Ultimul pret", f"{i['last_close']}", help=str(i["last_date"]), border=True)
    c[1].metric("Capitalizare", ron(i["market_cap"]) if i["market_cap"] else "–", border=True)
    c[2].metric(
        "Dividend 12 luni", pct(i["div_yield_12m"]), help="Randament din dividende, ultimele 12 luni", border=True
    )
    c[3].metric("Zile tranzactionate", pct(i["pct_days_traded_1y"], 0), help="Ultimul an", border=True)
    c[4].metric("Rulaj mediu/zi", ron(i["adv_value_1y"]), help="Valoare medie zilnica, ultimul an (RON)", border=True)

    start = date.today() - timedelta(days=365 * years)
    tr = analytics.series(con, [symbol], start=start)[symbol]
    px = analytics.series(con, [symbol], field="adj_close", start=start)[symbol]
    bench = analytics.benchmark_series(con, start=start)
    normalized_chart(
        {f"{symbol} randament total": tr, f"{symbol} pret ajustat": px, "BET-TR": bench},
        "Evolutie (baza 100)",
        log=years >= 10,
    )

    w = rep["windows"].T
    show = pd.DataFrame(
        {
            "Randament total/an": w["cagr"].map(pct),
            "Pret/an": w["price_cagr"].map(pct),
            "BET-TR/an": w["bench_cagr"].map(pct),
            "Volatilitate": w["volatility"].map(pct),
            "Sharpe": w["sharpe"].map(lambda x: f"{x:.2f}"),
            "Max drawdown": w["max_drawdown"].map(pct),
            "Beta": w["beta"].map(lambda x: f"{x:.2f}"),
        }
    )
    st.subheader("Randament si risc", help="Randamente anualizate pe ferestre; BET-TR include dividendele.")
    static_table(show)

    left, right = st.columns(2)
    with left:
        st.subheader("Date financiare (individuale)")
        f = valuation.fundamentals(con, symbol)
        if f.empty:
            st.info("Nu exista situatii financiare pe data.gov.ro pentru acest CUI.")
        else:
            f = f.tail(8)
            tbl = pd.DataFrame(
                {
                    "Cifra afaceri (mil.)": f["revenue"] / 1e6,
                    "Profit net (mil.)": f["net_profit"] / 1e6,
                    "Capitaluri (mil.)": f["equity"] / 1e6,
                    "ROE": f["roe"].map(pct),
                    "Marja neta": f["net_margin"].map(pct),
                    "Datorii/capitaluri": f["debt_to_equity"].round(2),
                    "Payout": f["payout"].map(pct),
                }
            ).T
            static_table(tbl, fmt=lambda v: f"{v:,.1f}" if isinstance(v, float) else v)
            m = valuation.current_multiples(con, [symbol])
            if len(m):
                r = m.iloc[0]
                st.caption(
                    f"Exercitiul {r['fiscal_year']}: P/E {r['pe']:.1f} · P/B {r['pb']:.2f} · "
                    f"P/S {r['ps']:.2f} · P/E vs. ultimii 10 ani: percentila {pct(r['pe_pctile_10y'], 0)}"
                )
            hist = valuation.multiples_history(con, symbol)
            if len(hist):
                # cate un grafic pe multiplu: scale diferite, fara a doua axa
                for tab, (col, name) in zip(st.tabs(["P/E", "P/B"]), [("pe", "P/E"), ("pb", "P/B")], strict=True):
                    fig = go.Figure(go.Scatter(x=hist.index, y=hist[col], name=name, line=dict(width=2)))
                    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified")
                    tab.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Dividende")
        divs = rep["dividends"].rename(
            columns={"fiscal_year": "Exercitiu", "amount": "RON/actiune", "ex_date": "Data ex", "pay_date": "Plata"}
        )
        static_table(divs, fmt={"RON/actiune": "{:.4f}", "Exercitiu": "{:.0f}"}, hide_index=True)
        st.subheader("Calendar")
        cal = con.execute(
            "SELECT date, kind, event FROM calendar WHERE symbol = ? AND date >= current_date ORDER BY date", [symbol]
        ).df()
        static_table(cal.rename(columns={"date": "Data", "kind": "Tip", "event": "Eveniment"}), hide_index=True)

    st.subheader("Rapoarte curente")
    cats = ["toate"] + [
        r[0]
        for r in con.execute("SELECT DISTINCT category FROM reports WHERE symbol = ? ORDER BY 1", [symbol]).fetchall()
    ]
    cat = st.selectbox("Categorie", cats)
    rows = con.execute(
        "SELECT published, category, title, url_ro FROM reports WHERE symbol = ? AND (? = 'toate' OR category = ?) "
        "ORDER BY published DESC LIMIT 100",
        [symbol, cat, cat],
    ).df()
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        row_height=40,
        column_config={
            "published": st.column_config.DatetimeColumn("Publicat", format="DD.MM.YYYY HH:mm"),
            "category": "Categorie",
            "title": st.column_config.TextColumn("Titlu", width="large"),
            "url_ro": st.column_config.LinkColumn("PDF", display_text="deschide"),
        },
    )
    st.subheader("Stiri")
    news = con.execute(
        "SELECT published, source, title, url FROM news WHERE list_contains(symbols, ?) "
        "ORDER BY published DESC LIMIT 30",
        [symbol],
    ).df()
    st.dataframe(
        news,
        use_container_width=True,
        hide_index=True,
        row_height=40,
        column_config={
            "published": st.column_config.DatetimeColumn("Publicat", format="DD.MM.YYYY HH:mm"),
            "source": "Sursa",
            "title": st.column_config.TextColumn("Titlu", width="large"),
            "url": st.column_config.LinkColumn("Link", display_text="deschide"),
        },
    )


@st.cache_data(max_entries=8)
def screen_table(market: str, years: int, version: float) -> pd.DataFrame:
    df = analytics.screen(con, market, years)
    val = valuation.current_multiples(con, list(df.index))
    if len(val):
        df = df.join(val[["pe", "pb", "roe", "net_margin", "debt_to_equity", "pe_pctile_10y"]])
    return df


# coloana -> (eticheta, format, procent?, explicatie)
SCREEN_COLUMNS = {
    "cagr": (
        "Randament/an",
        "%.1f%%",
        True,
        "Randament total anualizat (cu dividende reinvestite) pe fereastra aleasa",
    ),
    "volatility": ("Volatilitate", "%.1f%%", True, "Abaterea standard anualizata a randamentelor zilnice"),
    "sharpe": ("Sharpe", "%.2f", False, "Randament pe unitate de risc (fara rata fara risc)"),
    "max_drawdown": ("Max drawdown", "%.1f%%", True, "Cea mai mare scadere de la un varf la un minim"),
    "beta": ("Beta", "%.2f", False, "Sensibilitatea fata de BET-TR (1 = se misca la fel ca indicele)"),
    "market_cap_mn": ("Capitalizare (mil.)", "%,.0f", False, "Capitalizare bursiera, milioane RON"),
    "div_yield": ("Dividend 12 luni", "%.1f%%", True, "Dividende brute din ultimele 12 luni / pretul curent"),
    "adv_value_k": ("Rulaj/zi (mii)", "%,.0f", False, "Valoarea medie tranzactionata pe zi, ultimul an, mii RON"),
    "pct_days_traded": ("Zile tranz.", "%.0f%%", True, "Procentul sedintelor din ultimul an cu cel putin o tranzactie"),
    "pe": ("P/E", "%.1f", False, "Capitalizare / profit net, ultimul exercitiu disponibil (situatii individuale)"),
    "pb": ("P/B", "%.2f", False, "Capitalizare / capitaluri proprii, ultimul exercitiu"),
    "roe": ("ROE", "%.1f%%", True, "Profit net / capitaluri proprii medii"),
    "net_margin": ("Marja neta", "%.1f%%", True, "Profit net / cifra de afaceri"),
    "debt_to_equity": ("Datorii/cap.", "%.2f", False, "Datorii totale / capitaluri proprii"),
    "pe_pctile_10y": (
        "P/E percentila 10 ani",
        "%.0f%%",
        True,
        "Pozitia P/E-ului actual in istoricul pe 10 ani (0% = cel mai ieftin)",
    ),
}


def page_screen():
    st.title("Screener")
    market = st.sidebar.selectbox(
        "Piata",
        ["REGS", "XRS1", "XRSI"],
        format_func={"REGS": "Principala", "XRS1": "AeRO", "XRSI": "Internationala (SMT)"}.get,
    )
    years = st.sidebar.select_slider("Fereastra (ani)", options=[1, 3, 5, 10], value=3)
    min_traded = st.sidebar.slider(
        "Minim zile cu tranzactii (1 an)", 0.0, 1.0, 0.8, 0.05, help="Exclude actiunile nelichide."
    )
    df = screen_table(market, years, VERSION)
    df = df[df["pct_days_traded"].fillna(0) >= min_traded]
    cols = [c for c in SCREEN_COLUMNS if c in df]
    sort_by = st.sidebar.selectbox("Sorteaza dupa", cols, format_func=lambda c: SCREEN_COLUMNS[c][0])
    ascending = st.sidebar.toggle("Crescator", value=sort_by in ("volatility", "pe", "pb", "debt_to_equity"))
    df = df[cols].sort_values(sort_by, ascending=ascending, na_position="last")
    shown = df.copy()
    for c in cols:
        if SCREEN_COLUMNS[c][2]:
            shown[c] = shown[c] * 100
    st.caption(f"{len(df)} actiuni · randament total vs BET-TR · multipli pe ultimul exercitiu (situatii individuale)")
    st.dataframe(
        shown,
        use_container_width=True,
        height="content",  # fara bara de derulare interioara: pagina se deruleaza
        row_height=40,
        column_config={"_index": st.column_config.TextColumn("Simbol", pinned=True)}
        | {
            c: st.column_config.NumberColumn(label, format=fmt, help=explain)
            for c, (label, fmt, _, explain) in SCREEN_COLUMNS.items()
            if c in cols
        },
    )


REBALANCE = {"none": "Fara", "monthly": "Lunar", "quarterly": "Trimestrial", "yearly": "Anual"}


def page_portfolio():
    st.title("Portofoliu")
    text = st.sidebar.text_input(
        "Ponderi",
        value=", ".join(watchlist(VERSION)[:5]) or "TLV, SNP, H2O",
        help="Simboluri separate prin virgula, optional cu pondere: 'TLV=0.4, SNP=0.3, H2O'. "
        "Simbolurile fara pondere impart egal restul.",
    )
    value = st.sidebar.number_input("Valoare (RON)", value=100_000, step=10_000, help="Capitalul initial investit.")
    start = st.sidebar.date_input(
        "Start backtest",
        value=date(2020, 1, 1),
        help="Daca o actiune nu era listata atunci, startul se muta la prima zi cu preturi pentru toate.",
    )
    rebalance = st.sidebar.selectbox(
        "Rebalansare",
        list(REBALANCE),
        index=2,
        format_func=REBALANCE.get,
        help="Cat de des se readuc pozitiile la ponderile tinta. 'Fara' lasa ponderile sa evolueze; "
        "banii dintr-o actiune delistata raman atunci necheltuiti.",
    )
    dividends = st.sidebar.selectbox(
        "Dividende",
        ["drip", "cash"],
        format_func={"drip": "Reinvestite in actiune", "cash": "Pastrate ca numerar"}.get,
        help="Dividendele nete (dupa impozitul istoric pe dividende) se reinvestesc la data ex sau raman cash.",
    )
    fee = st.sidebar.number_input(
        "Comision",
        value=0.0025,
        step=0.0005,
        format="%.4f",
        help="Fractie din valoarea fiecarei tranzactii (0.0025 = 0,25%).",
    )
    weights = portfolio.parse_weights(text)
    if not weights:
        st.info("Introdu simboluri, ex. 'TLV=0.4, SNP=0.3, H2O=0.3'.")
        return
    try:
        res = portfolio.backtest(
            con,
            portfolio.Config(
                weights=weights, start=start, capital=value, rebalance=rebalance, fee=fee, dividends=dividends
            ),
        )
    except ValueError as e:
        st.error(str(e))
        return
    for n in res.notes:
        st.warning(n)

    m = res.metrics
    st.subheader(
        "Rezultat backtest",
        help="Simulare istorica: cumparare la inchidere, comisioane, impozit pe dividende si rebalansare. "
        "Diferenta fata de BET-TR apare sub fiecare valoare.",
    )
    c = st.columns(5)
    c[0].metric(
        "Valoare finala",
        ron(m["final_value"]),
        delta=ron(m["final_value"] - res.benchmark.iloc[-1]),
        help="Valoarea portofoliului la final. Diferenta: fata de aceeasi suma investita in BET-TR.",
        border=True,
    )
    c[1].metric(
        "CAGR",
        pct(m["cagr"]),
        delta=f"{(m['cagr'] - m['bench_cagr']) * 100:+.1f} pp",
        help="Randamentul mediu anual compus. Diferenta in puncte procentuale fata de BET-TR.",
        border=True,
    )
    c[2].metric(
        "Volatilitate",
        pct(m["volatility"]),
        delta=f"{(m['volatility'] - m['bench_volatility']) * 100:+.1f} pp",
        delta_color="inverse",
        help="Abaterea standard anualizata a randamentelor zilnice: cat de mult variaza valoarea.",
        border=True,
    )
    c[3].metric(
        "Max drawdown",
        pct(m["max_drawdown"]),
        delta=f"{(m['max_drawdown'] - m['bench_max_drawdown']) * 100:+.1f} pp",
        help="Cea mai mare scadere de la un varf la minimul urmator.",
        border=True,
    )
    c[4].metric(
        "Sharpe",
        f"{m['sharpe']:.2f}",
        help="Randament pe unitate de risc (randament anual / volatilitate, fara rata fara risc). Peste 1 e bun.",
        border=True,
    )
    normalized_chart({"Portofoliu": res.nav, "BET-TR": res.benchmark}, "Evolutie (baza 100)")
    st.subheader(
        "Randament pe ani",
        help="Pe ani calendaristici; primul si ultimul an pot fi partiali.",
    )
    static_table(portfolio.yearly_returns(res).rename(columns={"portofoliu": "Portofoliu"}), fmt=pct)

    st.header(":material/shield: Risc (ultimii 3 ani)")
    st.caption("Ponderile de azi aplicate pe istoricul ultimilor 3 ani.")
    try:
        r = risk.report(con, weights, value=value)
    except ValueError as e:
        st.warning(str(e))
        return
    for n in r.notes:
        st.info(n)
    cc = r.concentration
    st.subheader(
        "Concentrare si lichiditate",
        help="Cat de dependent e portofoliul de cateva pozitii si cat de repede poate fi vandut.",
    )
    c = st.columns(4)
    c[0].metric(
        "Pozitii efective",
        f"{cc['effective_n']:.1f}",
        help=f"1 / HHI (HHI = {cc['hhi']:.3f}). Cate pozitii egale ar avea aceeasi concentrare.",
        border=True,
    )
    c[1].metric(
        "Control de stat",
        pct(cc["state_controlled"], 0),
        help="Ponderea companiilor in care statul detine cel putin 50%.",
        border=True,
    )
    c[2].metric(
        "Cel mai mare sector",
        pct(cc["max_sector_weight"], 0),
        help=f"Sectorul: {str(cc['max_sector']).capitalize()}",
        border=True,
    )
    c[3].metric(
        "Vandabil in 5 zile",
        pct(cc["liquidatable_5d"], 0),
        help="Fractia din portofoliu care poate fi vanduta in 5 sedinte la cel mult 20% din rulajul zilnic mediu. "
        f"1 zi: {pct(cc['liquidatable_1d'], 0)} · 20 zile: {pct(cc['liquidatable_20d'], 0)}.",
        border=True,
    )

    st.subheader(
        "Pierdere posibila intr-o zi (VaR / CVaR)",
        help="VaR: pierderea zilnica depasita doar in 5% (sau 1%) din zile. CVaR: pierderea medie in acele zile rele. "
        "Istoric = din zilele reale; parametric = presupunand distributie normala.",
    )
    v = r.var
    var_tbl = pd.DataFrame(
        {
            "VaR istoric": v["hist_var"].map(lambda x: pct(x, 2)),
            "CVaR istoric": v["hist_cvar"].map(lambda x: pct(x, 2)),
            "VaR parametric": v["param_var"].map(lambda x: pct(x, 2)),
            "CVaR parametric": v["param_cvar"].map(lambda x: pct(x, 2)),
            "VaR istoric (RON)": v["hist_var_ron"].map(ron),
            "CVaR istoric (RON)": v["hist_cvar_ron"].map(ron),
        }
    )
    var_tbl.index = [f"Incredere {x:.0%}" for x in v.index]
    static_table(var_tbl)

    st.subheader(
        "Pozitii",
        help="Pondere: tinta din portofoliu. Contributie la risc: cat din volatilitatea portofoliului vine din pozitie "
        "(suma = 100%). Beta: sensibilitatea fata de BET-TR, pe randamente saptamanale. "
        "Zile pentru vanzare: la 20% din rulajul zilnic mediu.",
    )
    pos = r.positions.rename(
        columns={
            "weight": "Pondere",
            "volatility": "Volatilitate",
            "beta_weekly": "Beta",
            "risk_contribution": "Contributie la risc",
            "pct_days_traded": "Zile tranzactionate",
            "days_to_liquidate": "Zile pentru vanzare",
        }
    )
    static_table(
        pos,
        fmt={
            "Pondere": "{:.1%}",
            "Volatilitate": "{:.1%}",
            "Beta": "{:.2f}",
            "Contributie la risc": "{:.1%}",
            "Zile tranzactionate": "{:.0%}",
            "Zile pentru vanzare": "{:.1f}",
        },
    )
    left, right = st.columns(2)
    with left:
        st.subheader(
            "Corelatii",
            help="Corelatia randamentelor saptamanale: 1 = se misca identic, 0 = independent, -1 = opus. "
            "Corelatii mici intre pozitii inseamna diversificare mai buna.",
        )
        static_table(r.correlation, fmt="{:.2f}")
    with right:
        st.subheader(
            "Scenarii de stres",
            help="Cum s-ar fi comportat portofoliul in crize trecute (de la varf la minimul BET) si la scaderi "
            "ipotetice ale BET-TR, estimate prin beta. Actiunile nelistate atunci sunt aproximate prin beta.",
        )
        stress = r.stress.rename(
            columns={
                "scenario": "Scenariu",
                "portfolio": "Portofoliu",
                "benchmark": "BET-TR",
                "proxied": "Aproximate prin beta",
            }
        ).drop(columns=["start", "end"])
        static_table(stress, fmt={"Portofoliu": "{:.1%}", "BET-TR": "{:.1%}"}, hide_index=True)


EVENT_COLUMNS = {
    "date": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
    "symbol": "Simbol",
    "kind": "Tip",
    "event": st.column_config.TextColumn("Eveniment", width="large"),
    "published": st.column_config.DatetimeColumn("Publicat", format="DD.MM.YYYY HH:mm"),
    "category": "Categorie",
    "symbols": "Simboluri",
    "title": st.column_config.TextColumn("Titlu", width="large"),
    "url_ro": st.column_config.LinkColumn("PDF", display_text="deschide"),
    "url": st.column_config.LinkColumn("Link", display_text="deschide"),
}


def page_events():
    st.title("Calendar si anunturi")
    only_watch = st.sidebar.checkbox("Doar lista de urmarire", value=bool(watchlist(VERSION)))
    days = st.sidebar.slider("Zile", 7, 90, 30)
    cond = "symbol IN (SELECT symbol FROM watchlist)" if only_watch else "1=1"
    st.subheader("Urmeaza")
    st.dataframe(
        con.execute(
            f"""
        SELECT date, symbol, kind, event FROM calendar WHERE {cond} AND date BETWEEN current_date AND current_date + ?
        UNION ALL
        SELECT ex_date, symbol, 'ex-dividend', 'Dividend ' || amount FROM dividends
        WHERE {cond} AND ex_date BETWEEN current_date AND current_date + ?
        ORDER BY 1, 2""",
            [days, days],
        ).df(),
        use_container_width=True,
        hide_index=True,
        row_height=40,
        column_config=EVENT_COLUMNS,
    )
    st.subheader("Anunturi recente")
    st.dataframe(
        con.execute(
            f"""
        SELECT published, symbol, category, title, url_ro FROM reports
        WHERE {cond} AND published > now() - to_days(?) ORDER BY published DESC LIMIT 300""",
            [days],
        ).df(),
        use_container_width=True,
        hide_index=True,
        row_height=40,
        column_config=EVENT_COLUMNS,
    )
    st.subheader("Stiri")
    news_cond = "list_has_any(symbols, (SELECT list(symbol) FROM watchlist))" if only_watch else "1=1"
    st.dataframe(
        con.execute(
            f"""
        SELECT published, array_to_string(symbols, ',') AS symbols, title, url FROM news
        WHERE len(symbols) > 0 AND {news_cond}
          AND published > now() - to_days(?) ORDER BY published DESC""",
            [days],
        ).df(),
        use_container_width=True,
        hide_index=True,
        row_height=40,
        column_config=EVENT_COLUMNS,
    )


def page_learning():
    st.title("Invatare")
    st.caption(
        "Conceptele si metodologia din spatele cifrelor din dashboard. Formulele descriu calculul facut "
        "de aplicatie, cu conventiile si limitele lui; linkurile duc la explicatii mai largi."
    )
    query = st.sidebar.text_input("Cauta", placeholder="ex. beta, dividend, VaR")
    pages = st.sidebar.multiselect("Folosite pe pagina", learning.PAGES, placeholder="Toate paginile")
    found = learning.search(query, pages)
    if not found:
        st.info("Niciun concept pentru cautarea aleasa.")
        return
    groups = learning.by_topic(found)
    st.markdown(" · ".join(f"[{topic}](#{_anchor(topic)})" for topic in groups))
    for topic, concepts in groups.items():
        st.subheader(topic, anchor=_anchor(topic))
        for c in concepts:
            with st.expander(c.title, expanded=bool(query)):
                st.markdown(c.summary)
                for formula in c.formulas:
                    st.latex(formula)
                if c.method:
                    st.markdown(f"**Cum se calculeaza aici.** {c.method}")
                st.caption("Apare pe: " + ", ".join(c.pages))
                if c.links:
                    st.markdown("Mai mult: " + " · ".join(f"[{label}]({url})" for label, url in c.links))


def _anchor(text: str) -> str:
    return text.lower().replace(" ", "-")


nav = st.navigation(
    [
        st.Page(page_stock, title="Emitent", icon=":material/apartment:", url_path="emitent", default=True),
        st.Page(page_screen, title="Screener", icon=":material/filter_list:", url_path="screener"),
        st.Page(page_portfolio, title="Portofoliu", icon=":material/pie_chart:", url_path="portofoliu"),
        st.Page(page_events, title="Calendar si anunturi", icon=":material/event:", url_path="calendar"),
        st.Page(page_learning, title="Invatare", icon=":material/school:", url_path="invatare"),
    ]
)
nav.run()
st.sidebar.caption(f"Date actualizate: {datetime.fromtimestamp(VERSION):%d.%m.%Y %H:%M}")
st.sidebar.caption("Date: bvb.ro (uz personal), data.gov.ro (CC-BY 4.0). Nu reprezinta recomandari de investitii.")
