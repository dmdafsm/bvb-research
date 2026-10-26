import pandas as pd
import typer

from bvb import adjust, db
from bvb.ingest import bvb_history, bvb_summary, issuer, reports, yahoo
from bvb.reconcile import reconcile as reconcile_prices

app = typer.Typer(help="Instrument de analiza BVB (uz personal).", no_args_is_help=True)
ingest_app = typer.Typer(help="Colectare date.", no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")


@app.command()
def init_db():
    """Creeaza baza de date si schema."""
    db.connect().close()
    typer.echo(f"OK: {db.DB_PATH}")


@ingest_app.command("bvb")
def ingest_bvb(
    days: int = typer.Option(30, help="Cate sedinte inapoi (BVB ofera maxim ~30 de zile)."),
    full: bool = typer.Option(
        False, help="Parcurge toata fereastra si umple golurile (nu se opreste la prima zi existenta)."
    ),
    refresh: bool = typer.Option(False, help="Re-descarca si zilele deja existente."),
):
    """Preturi EOD din sumarul zilnic BVB (toate actiunile)."""
    con = db.connect()
    have = (
        set()
        if refresh
        else {r[0] for r in con.execute("SELECT DISTINCT date FROM prices_eod WHERE source = 'bvb'").fetchall()}
    )
    total, sessions = 0, 0
    try:
        for day, html in bvb_summary.fetch_sessions(days, known=have, walk_known=full):
            bvb_summary.save_raw(day, html)
            n = bvb_summary.store(con, day, bvb_summary.parse_summary(html))
            typer.echo(f"{day}: {n} simboluri")
            total += n
            sessions += n > 0
    except Exception as e:
        db.log_ingest(con, "bvb_summary", {"days": days}, "error", total, repr(e))
        raise
    db.log_ingest(con, "bvb_summary", {"days": days}, "ok", total, f"{sessions} sedinte")
    typer.echo(f"Total: {sessions} sedinte noi, {total} randuri")


@ingest_app.command("yahoo")
def ingest_yahoo(
    symbols: list[str] = typer.Argument(None, help="Simboluri; implicit actiunile de pe piata reglementata."),
    all_markets: bool = typer.Option(False, "--all", help="Include si AeRO / alte piete."),
    retry_missing: bool = typer.Option(False, help="Reincearca simbolurile negasite anterior."),
    refresh: bool = typer.Option(False, help="Re-descarca si simbolurile deja descarcate."),
):
    """Istoric complet din Yahoo Finance (implicit doar simbolurile neincercate inca)."""
    con = db.connect()
    if not symbols:
        where = ["1=1" if all_markets else "market = 'REGS'"]
        tried = []
        if refresh:
            tried.append("yahoo <> ''")
        if retry_missing:
            tried.append("yahoo = ''")
        where.append("(" + " OR ".join(["yahoo IS NULL", *tried]) + ")")
        symbols = [
            r[0]
            for r in con.execute(
                f"SELECT symbol FROM instruments WHERE {' AND '.join(where)} ORDER BY symbol"
            ).fetchall()
        ]
    if not symbols:
        typer.echo("Niciun simbol. Ruleaza intai `bvb ingest bvb`.")
        raise typer.Exit(1)
    counts = yahoo.ingest(con, symbols, log=typer.echo)
    found = sum(1 for n in counts.values() if n)
    db.log_ingest(con, "yahoo", {"symbols": len(symbols)}, "ok", sum(counts.values()), f"{found} gasite")
    typer.echo(f"Total: {found} gasite pe Yahoo din {len(counts)} incercate ({len(symbols)} cerute)")


@ingest_app.command("history")
def ingest_history(
    symbols: list[str] = typer.Argument(None, help="Simboluri; implicit toate din `instruments`."),
):
    """Istoric complet (brut + ajustat) din graficul BVB."""
    con = db.connect()
    if not symbols:
        symbols = [
            r[0]
            for r in con.execute("SELECT symbol FROM instruments WHERE market <> 'DELISTED' ORDER BY symbol").fetchall()
        ]
    if not symbols:
        typer.echo("Niciun simbol. Ruleaza intai `bvb ingest bvb`.")
        raise typer.Exit(1)
    counts = bvb_history.ingest(con, symbols, log=typer.echo)
    found = sum(1 for n in counts.values() if n)
    db.log_ingest(con, "bvb_history", {"symbols": len(symbols)}, "ok", sum(counts.values()), f"{found} cu date")
    typer.echo(f"Total: {found}/{len(symbols)} simboluri, {sum(counts.values())} randuri")


@ingest_app.command("indices")
def ingest_indices(
    indices: list[str] = typer.Argument(None, help="Indici; implicit lista din bvb_history.INDICES."),
):
    """Istoric indici BVB (BET, BET-TR etc.) din graficul BVB."""
    con = db.connect()
    indices = indices or bvb_history.INDICES
    con.executemany(
        "INSERT INTO instruments (symbol, market) VALUES (?, 'INDEX') "
        "ON CONFLICT (symbol) DO UPDATE SET market = 'INDEX'",
        [[i] for i in indices],
    )
    counts = bvb_history.ingest(con, indices, log=typer.echo)
    db.log_ingest(con, "bvb_indices", {"indices": indices}, "ok", sum(counts.values()))


@ingest_app.command("metadata")
def ingest_metadata():
    """Sector, industrie si moneda pentru toate instrumentele (API grafic BVB)."""
    con = db.connect()
    symbols = [
        r[0]
        for r in con.execute("SELECT symbol FROM instruments WHERE market <> 'DELISTED' ORDER BY symbol").fetchall()
    ]
    n = bvb_history.ingest_metadata(con, symbols, log=typer.echo)
    db.log_ingest(con, "metadata", {"symbols": len(symbols)}, "ok", n)
    typer.echo(f"Total: {n}/{len(symbols)}")


@ingest_app.command("fundamentals")
def ingest_fundamentals(
    years: str = typer.Option("2008-2100", help="Interval de ani, ex. 2019-2025."),
    uu: bool = typer.Option(True, help="Include formatul prescurtat (fisiere mari, ~80 MB/an, citite in flux)."),
):
    """Situatii financiare anuale individuale de pe data.gov.ro (CC-BY 4.0)."""
    import httpx

    from bvb.ingest import datagov

    con = db.connect()
    by_cui = {}
    for sym, cui in con.execute(
        "SELECT symbol, cui FROM instruments WHERE cui IS NOT NULL AND market <> 'INDEX'"
    ).fetchall():
        by_cui.setdefault(cui.strip().upper().removeprefix("RO"), []).append(sym)
    y0, y1 = (int(x) for x in years.split("-"))
    kinds = {k for k, _ in datagov.KINDS} - (set() if uu else {"UU"})
    total = 0
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for year, pkg in sorted(datagov.packages(client).items()):
            if not y0 <= year <= y1:
                continue
            rows = datagov.ingest_year(client, year, pkg, set(by_cui), kinds, log=typer.echo)
            con.execute("DELETE FROM fundamentals WHERE year = ?", [year])
            con.execute("DELETE FROM fundamentals_raw WHERE year = ?", [year])
            for r in rows:
                for sym in by_cui[r["cui"]]:
                    con.execute(
                        "INSERT OR REPLACE INTO fundamentals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            sym,
                            year,
                            r["kind"],
                            r["cui"],
                            r["caen"],
                            r["revenue"],
                            r["total_revenue"],
                            r["net_profit"],
                            r["equity"],
                            r["total_assets"],
                            r["debts"],
                            r["cash"],
                            r["employees"],
                        ],
                    )
                    con.executemany(
                        "INSERT INTO fundamentals_raw VALUES (?, ?, ?, ?, ?)",
                        [[sym, year, r["kind"], k, v] for k, v in r["values"].items() if v is not None],
                    )
                    total += 1
    db.log_ingest(con, "fundamentals", {"years": years, "uu": uu}, "ok", total)
    typer.echo(f"Total: {total} randuri emitent-an")


def _store_issuer(con, symbol: str, html: str):
    """Fisa emitentului -> instruments, dividende, capital, actionariat, rapoarte, calendar."""
    data = issuer.parse(symbol, html)
    issuer.store(con, data)
    n = reports.store_reports(con, reports.parse_issuer_news(symbol, html))
    reports.store_calendar(con, symbol, reports.parse_calendar(symbol, html))
    return data, n


@ingest_app.command("delisted")
def ingest_delisted(
    refresh_list: bool = typer.Option(False, help="Re-descarca lista din cautarea avansata BVB."),
    limit: int = typer.Option(0, help="Maxim atatea simboluri verificate (0 = toate)."),
):
    """Actiuni delistate: lista BVB + istoric din graficul BVB (doar cele cu tranzactii pe BVB)."""
    import time

    import httpx

    from bvb.config import BVB_BASE, REQUEST_DELAY, USER_AGENT
    from bvb.ingest import delisted

    con = db.connect()
    rows = delisted.fetch_list(log=typer.echo) if refresh_list or not delisted.load_list() else delisted.load_list()
    con.execute(
        "CREATE TABLE IF NOT EXISTS delisted_probe (symbol VARCHAR PRIMARY KEY, checked TIMESTAMP, days INTEGER)"
    )
    known = {
        r[0] for r in con.execute("SELECT symbol FROM instruments UNION SELECT symbol FROM delisted_probe").fetchall()
    }
    todo = [r for r in rows if r["symbol"] not in known and r["status"] != "Tranzactionabila"]
    if limit:
        todo = todo[:limit]
    typer.echo(f"{len(rows)} actiuni in lista BVB, {len(todo)} delistate de verificat")
    until = bvb_history.last_complete_day()
    found = 0
    headers = {"User-Agent": USER_AGENT, "Referer": f"{BVB_BASE}/"}
    with httpx.Client(headers=headers, timeout=60) as client:
        for i, r in enumerate(todo, 1):
            sym = r["symbol"]
            try:
                raw = bvb_history.fetch(client, sym, adjusted=False)
                adj = bvb_history.fetch(client, sym, adjusted=True) if raw.get("s") == "ok" else None
            except httpx.HTTPError as e:
                typer.echo(f"{sym}: eroare {e!r}"[:200])
                continue
            prices = bvb_history.parse(sym, raw, adj, until)
            if prices:
                bvb_history.store(con, prices)
                con.execute(
                    """INSERT INTO instruments (symbol, name, isin, cui, market, status, first_seen, last_seen)
                               VALUES (?, ?, ?, ?, 'DELISTED', ?, ?, ?) ON CONFLICT (symbol) DO NOTHING""",
                    [
                        sym,
                        r["issuer"] or r["name"],
                        r["isin"],
                        r["cui"] or None,
                        r["status"],
                        prices[0][0],
                        prices[-1][0],
                    ],
                )
                found += 1
            con.execute("INSERT OR REPLACE INTO delisted_probe VALUES (?, now(), ?)", [sym, len(prices)])
            if i % 100 == 0:
                typer.echo(f"{i}/{len(todo)} verificate, {found} cu istoric")
            time.sleep(REQUEST_DELAY / 2)
    db.log_ingest(con, "delisted", {"checked": len(todo)}, "ok", found)
    typer.echo(f"Total: {found} actiuni delistate cu istoric pe BVB (din {len(todo)} verificate)")


@ingest_app.command("issuers")
def ingest_issuers(
    symbols: list[str] = typer.Argument(None, help="Simboluri; implicit actiunile neactualizate de --max-age zile."),
    max_age: int = typer.Option(7, help="Re-descarca fisele mai vechi de atatea zile."),
    from_raw: bool = typer.Option(False, help="Re-parseaza HTML-ul deja salvat, fara descarcare."),
):
    """Fisa emitentului: date de baza, dividende, modificari de capital, actionariat."""
    con = db.connect()
    if from_raw:
        files = sorted((issuer.RAW_DIR / "issuer").glob("*.html"))
        for f in files:
            if symbols and f.stem not in symbols:
                continue
            _store_issuer(con, f.stem, f.read_text(encoding="utf-8"))
        typer.echo(f"Re-parsate {len(files)} fise")
        return
    if not symbols:
        symbols = [
            r[0]
            for r in con.execute(
                "SELECT symbol FROM instruments WHERE market NOT IN ('INDEX', 'DELISTED') "
                "AND (issuer_updated IS NULL OR issuer_updated < now() - to_days(?)) ORDER BY symbol",
                [max_age],
            ).fetchall()
        ]
    ok = 0
    for symbol, html, err in issuer.fetch_snapshots(symbols):
        if err is not None:
            typer.echo(f"{symbol}: eroare {err!r}"[:200])
            continue
        issuer.save_raw(symbol, html)
        data, n_reports = _store_issuer(con, symbol, html)
        ok += 1
        typer.echo(
            f"{symbol}: {len(data['dividends'])} dividende, {len(data['capital'])} modificari capital, "
            f"{n_reports} rapoarte"
        )
    db.log_ingest(con, "issuers", {"symbols": len(symbols)}, "ok", ok)
    typer.echo(f"Total: {ok}/{len(symbols)} fise")


@app.command("adjust")
def adjust_cmd(
    symbols: list[str] = typer.Argument(None, help="Simboluri; implicit toate actiunile."),
    show: int = typer.Option(25, help="Cate randuri din rezumat afiseaza (cele mai problematice primele)."),
):
    """Calculeaza preturile ajustate (capital + dividende) in `prices_adj`."""
    con = db.connect()
    if not symbols:
        symbols = [
            r[0]
            for r in con.execute("SELECT symbol FROM instruments WHERE market <> 'INDEX' ORDER BY symbol").fetchall()
        ]
    summary = adjust.run(con, symbols)
    db.log_ingest(con, "adjust", {"symbols": len(symbols)}, "ok", int(summary["days"].sum()) if len(summary) else 0)
    if len(summary):
        summary = summary.sort_values(["suspicious", "unknown", "max_div_yield"], ascending=False)
        typer.echo(summary.head(show).to_string(index=False))
        typer.echo(
            f"\n{len(summary)} simboluri; evenimente necunoscute: {summary['unknown'].sum()}, "
            f"miscari suspecte: {summary['suspicious'].sum()}, dividende sarite: {summary['div_skipped'].sum()}"
        )


PCT = {
    "cagr",
    "price_cagr",
    "bench_cagr",
    "volatility",
    "max_drawdown",
    "tracking_error",
    "div_yield",
    "pct_days_traded",
    "div_yield_12m",
    "pct_days_traded_1y",
}


def _fmt(df):
    df = df.copy()
    for col in df.columns:
        if col in PCT:
            df[col] = df[col].map(lambda x: f"{x:.1%}" if x == x else "")
        elif df[col].dtype.kind == "f":
            df[col] = df[col].map(lambda x: f"{x:,.2f}" if x == x else "")
    return df


@app.command()
def stock(
    symbol: str,
    rf: float = typer.Option(0.0, help="Rata fara risc anuala pentru Sharpe/Sortino (ex. 0.06)."),
):
    """Raport pe o actiune: randamente, risc, lichiditate, dividende."""
    from bvb import analytics

    r = analytics.stock_report(db.connect(), symbol.upper(), rf=rf)
    i = r["info"]
    typer.echo(f"{symbol.upper()} — {i['name']} ({i['isin']}, {i['market']}, {i['segment']} {i['category']})")
    typer.echo(f"Activitate: {i['activity']}")
    cap = f"{i['market_cap'] / 1e6:,.0f} mil. RON" if i["market_cap"] else "n/a"
    typer.echo(
        f"Ultimul pret: {i['last_close']} ({i['last_date']}), capitalizare {cap}, "
        f"randament dividend 12 luni {i['div_yield_12m']:.1%}"
    )
    typer.echo(
        f"Lichiditate 1 an: tranzactii in {i['pct_days_traded_1y']:.0%} din zile, "
        f"valoare medie zilnica {i['adv_value_1y']:,.0f} RON\n"
    )
    w = r["windows"].T.infer_objects()
    w = w[
        [
            "cagr",
            "price_cagr",
            "bench_cagr",
            "volatility",
            "sharpe",
            "sortino",
            "max_drawdown",
            "dd_peak",
            "dd_trough",
            "beta",
            "corr",
            "tracking_error",
            "info_ratio",
        ]
    ]
    typer.echo("Randament total (dividende brute reinvestite) vs BET-TR:")
    for col in ("sharpe", "sortino", "beta", "corr", "info_ratio"):
        w[col] = w[col].astype(float)
    typer.echo(_fmt(w).T.to_string())
    if len(r["dividends"]):
        typer.echo("\nUltimele dividende:")
        typer.echo(r["dividends"].to_string(index=False))


@app.command()
def screen(
    market: str = typer.Option("REGS", help="Piata: REGS, XRS1 (AeRO) etc."),
    years: int = typer.Option(3, help="Fereastra pentru metrici (ani)."),
    min_traded: float = typer.Option(0.0, help="Elimina actiunile tranzactionate in mai putin de atatea zile (0-1)."),
    sort: str = typer.Option("market_cap_mn", help="Coloana de sortare."),
    top: int = typer.Option(40),
):
    """Tabel comparativ: capitalizare, randament, risc, dividend, lichiditate."""
    from bvb import analytics

    df = analytics.screen(db.connect(), market, years)
    df = df[df["pct_days_traded"].fillna(0) >= min_traded]
    df = df.sort_values(sort, ascending=sort in ("volatility", "beta"))
    typer.echo(f"{market}, fereastra {years} ani, randament total vs BET-TR:")
    typer.echo(_fmt(df.head(top)).to_string())


@app.command()
def backtest(
    weights: str = typer.Argument(..., help="Ex: 'TLV=0.3,SNP=0.3,H2O=0.4' sau 'TLV,SNP,H2O' (ponderi egale)."),
    start: str = typer.Option(None, help="Data start YYYY-MM-DD (implicit: prima zi comuna)."),
    end: str = typer.Option(None, help="Data sfarsit YYYY-MM-DD."),
    capital: float = typer.Option(100_000.0),
    rebalance: str = typer.Option("none", help="none | monthly | quarterly | yearly"),
    fee: float = typer.Option(0.0025, help="Comision pe tranzactie (0.0025 = 0,25%)."),
    tax: str = typer.Option("auto", help="'auto' = cotele istorice de impozit pe dividende, sau o cota fixa (ex. 0)."),
    dividends: str = typer.Option("drip", help="drip (reinvestite in aceeasi actiune) | cash"),
    rf: float = typer.Option(0.0, help="Rata fara risc anuala pentru Sharpe/Sortino."),
    csv: str = typer.Option(None, help="Salveaza NAV-ul zilnic (portofoliu + benchmark) in acest CSV."),
):
    """Backtest de portofoliu cu dividende, impozit, comisioane si rebalansare, vs BET-TR."""
    from datetime import date as _date

    from bvb import portfolio

    cfg = portfolio.Config(
        weights=portfolio.parse_weights(weights),
        start=_date.fromisoformat(start) if start else None,
        end=_date.fromisoformat(end) if end else None,
        capital=capital,
        rebalance=rebalance,
        fee=fee,
        tax=tax if tax == "auto" else float(tax),
        dividends=dividends,
        rf=rf,
    )
    r = portfolio.backtest(db.connect(), cfg)
    m = r.metrics
    typer.echo(f"Portofoliu: {', '.join(f'{s} {w:.0%}' for s, w in cfg.weights.items())}")
    typer.echo(
        f"Perioada: {r.nav.index[0].date()} – {r.nav.index[-1].date()}, rebalansare {rebalance}, "
        f"comision {fee:.2%}, impozit dividende {tax}, dividende {dividends}"
    )
    for n in r.notes:
        typer.echo(f"  ! {n}")
    typer.echo("")
    rows = [
        ("Valoare finala", f"{m['final_value']:,.0f}", f"{r.benchmark.iloc[-1]:,.0f}"),
        ("CAGR", f"{m['cagr']:.2%}", f"{m['bench_cagr']:.2%}"),
        ("Volatilitate", f"{m['volatility']:.2%}", f"{m['bench_volatility']:.2%}"),
        (
            "Max drawdown",
            f"{m['max_drawdown']:.2%} ({m['dd_peak']} → {m['dd_trough']})",
            f"{m['bench_max_drawdown']:.2%}",
        ),
        ("Sharpe / Sortino", f"{m['sharpe']:.2f} / {m['sortino']:.2f}", ""),
        ("Beta / corelatie", f"{m['beta']:.2f} / {m['corr']:.2f}", ""),
        ("Tracking error / IR", f"{m['tracking_error']:.2%} / {m['info_ratio']:.2f}", ""),
        ("Dividende brute / impozit", f"{m['dividends_gross']:,.0f} / {m['dividend_tax']:,.0f}", ""),
        ("Comisioane", f"{m['fees_paid']:,.0f}", ""),
        ("Rulaj anual", f"{m['turnover_per_year']:.0%}", ""),
    ]
    w = max(len(r_[0]) for r_ in rows)
    typer.echo(f"{'':{w}}  {'Portofoliu':<40}  BET-TR")
    for name, p, b in rows:
        typer.echo(f"{name:{w}}  {p:<40}  {b}")
    yr = portfolio.yearly_returns(r)
    typer.echo("\nRandament pe ani:")
    typer.echo(yr.map(lambda x: f"{x:.1%}").to_string())
    if csv:
        pd.DataFrame({"portfolio": r.nav, "benchmark": r.benchmark}).to_csv(csv, index_label="date")
        typer.echo(f"\nNAV salvat in {csv}")


@app.command()
def risk(
    weights: str = typer.Argument(..., help="Ex: 'TLV=0.3,SNP=0.3,H2O=0.4' sau 'TLV,SNP,H2O'."),
    value: float = typer.Option(100_000.0, help="Valoarea portofoliului (RON)."),
    years: float = typer.Option(3.0, help="Fereastra de estimare (ani)."),
    horizon: int = typer.Option(1, help="Orizont VaR (zile de tranzactionare)."),
    end: str = typer.Option(None, help="Data evaluarii YYYY-MM-DD (implicit ultima zi)."),
    participation: float = typer.Option(0.2, help="Cota maxima din volumul zilnic la lichidare."),
):
    """Risc de portofoliu: VaR/CVaR, contributii, corelatii, stres, concentrare, lichiditate."""
    from datetime import date as _date

    from bvb import portfolio
    from bvb import risk as risk_mod

    w = portfolio.parse_weights(weights)
    r = risk_mod.report(
        db.connect(),
        w,
        value=value,
        years=years,
        horizon=horizon,
        participation=participation,
        end=_date.fromisoformat(end) if end else None,
    )
    c = r.concentration
    typer.echo(
        f"Portofoliu {value:,.0f} RON, estimare {r.window[0]} – {r.window[1]}, "
        f"volatilitate anuala {c['portfolio_vol']:.1%}, shrinkage covarianta {r.shrinkage:.2f}"
    )
    for n in r.notes:
        typer.echo(f"  ! {n}")

    typer.echo(f"\nVaR / CVaR pe {horizon} zi(le) (pierdere):")
    v = r.var.copy()
    for col in ("hist_var", "hist_cvar", "param_var", "param_cvar"):
        v[col] = v[col].map(lambda x: f"{x:.2%}")
    for col in ("hist_var_ron", "hist_cvar_ron"):
        v[col] = v[col].map(lambda x: f"{x:,.0f}")
    v.index = [f"{x:.0%}" for x in v.index]
    typer.echo(v.to_string())

    typer.echo("\nPozitii:")
    p = r.positions.copy()
    for col in ("weight", "volatility", "risk_contribution", "pct_days_traded"):
        p[col] = p[col].map(lambda x: f"{x:.1%}" if x == x else "")
    p["beta_weekly"] = p["beta_weekly"].map(lambda x: f"{x:.2f}")
    p["days_to_liquidate"] = p["days_to_liquidate"].map(lambda x: f"{x:.1f}" if x == x else "n/a")
    typer.echo(p.to_string())

    typer.echo("\nCorelatii (randamente saptamanale):")
    typer.echo(r.correlation.round(2).to_string())

    typer.echo("\nScenarii de stres (randament total):")
    s = r.stress.copy()
    for col in ("portfolio", "benchmark"):
        s[col] = s[col].map(lambda x: f"{x:.1%}")
    typer.echo(s.fillna("").to_string(index=False))

    typer.echo("\nConcentrare:")
    typer.echo(
        f"  HHI {c['hhi']:.3f} (echivalent {c['effective_n']:.1f} pozitii egale), "
        f"cea mai mare pozitie {c['top1']:.0%}, top 3 {c['top3']:.0%}"
    )
    typer.echo("  Pe sectoare: " + ", ".join(f"{k} {v:.0%}" for k, v in r.by_sector.items()))
    typer.echo(
        f"  Companii controlate de stat (>= 50%): {c['state_controlled']:.0%}, "
        f"cu orice participatie de stat: {c['state_any']:.0%}; in alte monede decat RON: {c['non_ron']:.0%}"
    )
    typer.echo(
        f"\nLichiditate (max {participation:.0%} din valoarea medie zilnica, ultimele 6 luni): "
        f"vandabil in 1 zi {c['liquidatable_1d']:.0%}, 5 zile {c['liquidatable_5d']:.0%}, "
        f"20 zile {c['liquidatable_20d']:.0%}"
    )


FUND_PCT = {"net_margin", "roe", "roa", "revenue_growth", "profit_growth", "payout", "pe_pctile_10y", "pb_pctile_10y"}


@app.command()
def fundamentals(
    symbol: str,
    years: int = typer.Option(10, help="Cati ani afiseaza."),
):
    """Situatii financiare anuale (individuale, data.gov.ro), indicatori si multipli actuali."""
    from bvb import valuation

    con = db.connect()
    sym = symbol.upper()
    f = valuation.fundamentals(con, sym)
    if f.empty:
        typer.echo(f"Nu exista date financiare pentru {sym} (CUI negasit in data.gov.ro).")
        raise typer.Exit(1)
    f = f.tail(years)
    show = pd.DataFrame(index=f.index)
    for col in ("revenue", "net_profit", "equity", "total_assets", "debts", "dividends_total"):
        show[f"{col}_mn"] = (f[col] / 1e6).map(lambda x: f"{x:,.1f}" if x == x else "")
    for col in ("net_margin", "roe", "roa", "revenue_growth", "payout"):
        show[col] = f[col].map(lambda x: f"{x:.1%}" if x == x else "")
    show["debt_to_equity"] = f["debt_to_equity"].map(lambda x: f"{x:.2f}" if x == x else "")
    show["employees"] = f["employees"].map(lambda x: f"{x:,.0f}" if x == x else "")
    typer.echo(f"{sym} — situatii individuale ({f['kind'].iloc[-1]}), milioane RON:")
    typer.echo(show.T.to_string())
    m = valuation.current_multiples(con, [sym])
    if len(m):
        r = m.iloc[0]
        typer.echo(
            f"\nCapitalizare {r['mcap_mn']:,.0f} mil. RON; pe exercitiul {r['fiscal_year']}: "
            f"P/E {r['pe']:.1f}, P/B {r['pb']:.2f}, P/S {r['ps']:.2f}"
        )
        if r["pe_pctile_10y"] == r["pe_pctile_10y"]:
            typer.echo(
                f"Fata de ultimii 10 ani: P/E mai mare decat in {r['pe_pctile_10y']:.0%} din luni, "
                f"P/B mai mare decat in {r['pb_pctile_10y']:.0%} din luni"
            )


@app.command()
def valuation(
    market: str = typer.Option("REGS"),
    sort: str = typer.Option("mcap_mn"),
    min_traded: float = typer.Option(0.5, help="Prag de lichiditate (fractie din zile cu tranzactii, 1 an)."),
    top: int = typer.Option(40),
):
    """Multipli de evaluare si calitate pentru toate actiunile unei piete."""
    from datetime import date as _date

    from bvb import analytics
    from bvb import valuation as val

    con = db.connect()
    symbols = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT f.symbol FROM fundamentals f JOIN instruments i USING (symbol) WHERE i.market = ?",
            [market],
        ).fetchall()
    ]
    df = val.current_multiples(con, symbols)
    liq = analytics.liquidity(con, list(df.index), _date.today())
    df = df[liq["pct_days_traded"].fillna(0) >= min_traded]
    df = df.sort_values(sort, ascending=sort in ("pe", "pb", "ps", "debt_to_equity", "pe_pctile_10y", "pb_pctile_10y"))
    out = df.head(top).copy()
    for col in out.columns:
        if col in FUND_PCT:
            out[col] = out[col].map(lambda x: f"{x:.0%}" if x == x else "")
        elif out[col].dtype.kind == "f":
            out[col] = out[col].map(lambda x: f"{x:,.2f}" if x == x else "")
    typer.echo("Multipli pe ultimul exercitiu disponibil (situatii individuale):")
    typer.echo(out.to_string())


@ingest_app.command("reports")
def ingest_reports(
    windows: int = typer.Option(1, help="Cate ferestre de ~10 zile inapoi (pagina globala BVB)."),
):
    """Rapoarte curente ale tuturor emitentilor (inclusiv tranzactii management, art. 19)."""
    con = db.connect()
    total = 0
    for day, html in reports.fetch_global(windows=windows):
        reports.save_raw(f"global_{day.replace('.', '-')}", html)
        n = reports.store_reports(con, reports.parse_global(html))
        typer.echo(f"pana la {day}: {n} rapoarte")
        total += n
    db.log_ingest(con, "reports", {"windows": windows}, "ok", total)


@ingest_app.command("news")
def ingest_news():
    """Stiri din fluxurile RSS (ZF, Profit.ro), etichetate cu emitentii mentionati."""
    from bvb.ingest import news as news_mod

    con = db.connect()
    match = news_mod.build_matcher(
        con.execute("SELECT symbol, name FROM instruments WHERE market <> 'INDEX'").fetchall()
    )
    items = news_mod.fetch()
    n = news_mod.store(con, items, match)
    tagged = sum(1 for it in items if match(f"{it['title']} {it['summary']}"))
    db.log_ingest(con, "news", {}, "ok", n)
    typer.echo(f"{n} stiri, {tagged} cu emitenti identificati")


@ingest_app.command("report-texts")
def ingest_report_texts(
    days: int = typer.Option(90, help="Rapoartele din ultimele atatea zile."),
    all_symbols: bool = typer.Option(False, "--all", help="Toti emitentii, nu doar lista de urmarire."),
):
    """Descarca PDF-urile rapoartelor (lista de urmarire) si extrage textul pentru cautare."""
    import io
    import time

    import httpx
    from pypdf import PdfReader

    from bvb.config import REQUEST_DELAY, USER_AGENT

    con = db.connect()
    where = "" if all_symbols else "AND symbol IN (SELECT symbol FROM watchlist)"
    todo = con.execute(
        f"""SELECT symbol, published, title, url_ro FROM reports
        WHERE text IS NULL AND url_ro IS NOT NULL AND published > now() - to_days(?) {where}
        ORDER BY published DESC""",
        [days],
    ).fetchall()
    ok = 0
    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Referer": "https://bvb.ro/"}, timeout=60, follow_redirects=True
    ) as client:
        for symbol, published, title, url in todo:
            try:
                r = client.get(url)
                r.raise_for_status()
                text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
            except Exception as e:
                typer.echo(f"{symbol} {published:%Y-%m-%d} {title[:50]}: eroare {e!r}"[:200])
                continue
            con.execute(
                "UPDATE reports SET text = ? WHERE symbol = ? AND published = ? AND title = ?",
                [text, symbol, published, title],
            )
            ok += 1
            time.sleep(REQUEST_DELAY / 2)
    typer.echo(f"Text extras din {ok}/{len(todo)} rapoarte")


watch_app = typer.Typer(help="Lista de urmarire.", no_args_is_help=True)
app.add_typer(watch_app, name="watch")


@watch_app.command("add")
def watch_add(symbols: list[str]):
    con = db.connect()
    con.executemany("INSERT OR IGNORE INTO watchlist (symbol) VALUES (?)", [[s.upper()] for s in symbols])
    watch_list()


@watch_app.command("remove")
def watch_remove(symbols: list[str]):
    con = db.connect()
    con.executemany("DELETE FROM watchlist WHERE symbol = ?", [[s.upper()] for s in symbols])
    watch_list()


@watch_app.command("list")
def watch_list():
    rows = db.connect().execute("SELECT symbol FROM watchlist ORDER BY symbol").fetchall()
    typer.echo(", ".join(r[0] for r in rows) or "(gol)")


def _symbols_filter(symbols: list[str] | None, watchlist: bool) -> tuple[str, list]:
    if symbols:
        return f"symbol IN ({','.join('?' * len(symbols))})", [s.upper() for s in symbols]
    if watchlist:
        return "symbol IN (SELECT symbol FROM watchlist)", []
    return "1=1", []


@app.command("reports")
def reports_cmd(
    symbols: list[str] = typer.Argument(None),
    days: int = typer.Option(30),
    category: str = typer.Option(None, help="insider, dividend, results, agm, buyback, holdings, ..."),
    watchlist: bool = typer.Option(False, "--watchlist", "-w"),
    search: str = typer.Option(None, help="Cauta in titlu si in textul extras din PDF."),
    limit: int = typer.Option(50),
):
    """Rapoartele curente recente, filtrate."""
    where, params = _symbols_filter(symbols, watchlist)
    sql = (
        "SELECT published, symbol, category, title, url_ro FROM reports "
        f"WHERE {where} AND published > now() - to_days(?)"
    )
    params.append(days)
    if category:
        sql += " AND category = ?"
        params.append(category)
    if search:
        sql += " AND (title ILIKE ? OR text ILIKE ?)"
        params += [f"%{search}%"] * 2
    df = db.connect().execute(sql + " ORDER BY published DESC LIMIT ?", [*params, limit]).df()
    df["title"] = df["title"].str.slice(0, 80)
    typer.echo(df.to_string(index=False) if len(df) else "Niciun raport.")


@app.command("calendar")
def calendar_cmd(
    symbols: list[str] = typer.Argument(None),
    days: int = typer.Option(30, help="Evenimentele din urmatoarele atatea zile."),
    watchlist: bool = typer.Option(False, "--watchlist", "-w"),
):
    """Evenimente viitoare: rezultate, AGA, date ex-dividend."""
    where, params = _symbols_filter(symbols, watchlist)
    df = (
        db.connect()
        .execute(
            f"""
        SELECT date, symbol, kind, event FROM calendar
        WHERE {where} AND date >= current_date AND date <= current_date + to_days(?)
        UNION ALL
        SELECT ex_date, symbol, 'ex-dividend',
               'Dividend ' || amount || ' RON, plata ' || coalesce(pay_date::VARCHAR, '?')
        FROM dividends WHERE {where} AND ex_date >= current_date AND ex_date <= current_date + to_days(?)
        ORDER BY 1, 2
    """,
            [*params, days, *params, days],
        )
        .df()
    )
    typer.echo(df.to_string(index=False) if len(df) else "Niciun eveniment.")


@app.command("news")
def news_cmd(
    symbols: list[str] = typer.Argument(None),
    days: int = typer.Option(7),
    watchlist: bool = typer.Option(False, "--watchlist", "-w"),
):
    """Stiri RSS care mentioneaza emitentii (toti, cei dati sau lista de urmarire)."""
    if symbols:
        cond, params = "list_has_any(symbols, ?)", [[s.upper() for s in symbols]]
    elif watchlist:
        cond, params = "list_has_any(symbols, (SELECT list(symbol) FROM watchlist))", []
    else:
        cond, params = "len(symbols) > 0", []
    df = (
        db.connect()
        .execute(
            f"""SELECT published, source, array_to_string(symbols, ',') AS symbols, title, url
        FROM news WHERE {cond} AND published > now() - to_days(?) ORDER BY published DESC""",
            [*params, days],
        )
        .df()
    )
    df["title"] = df["title"].str.slice(0, 90)
    typer.echo(df.to_string(index=False) if len(df) else "Nicio stire.")


@app.command()
def alerts(
    notify: bool = typer.Option(False, help="Trimite si o notificare macOS."),
    move: float = typer.Option(0.05, help="Prag pentru miscarea de pret din ultima sedinta."),
):
    """Anunturi noi, ex-dividend in 7 zile si miscari mari pentru lista de urmarire."""
    from bvb import alerts as alerts_mod

    lines = alerts_mod.collect(db.connect(), move_threshold=move)
    typer.echo("\n".join(lines) if lines else "Nimic nou pentru lista de urmarire.")
    if notify:
        alerts_mod.notify(lines)


@app.command()
def daily(
    full: bool = typer.Option(False, help="Si actualizarile saptamanale: istoric grafic, fise emitenti, metadate."),
    notify: bool = typer.Option(False, help="Notificare macOS cu alertele."),
):
    """Rularea zilnica (dupa 18:30): preturi, anunturi, stiri, ajustari, alerte."""
    steps = [
        ("Preturi BVB", lambda: ingest_bvb(days=30, full=False, refresh=False)),
        ("Rapoarte curente", lambda: ingest_reports(windows=1)),
        ("Stiri", ingest_news),
    ]
    if full:
        steps += [
            ("Istoric grafic", lambda: ingest_history(symbols=None)),
            ("Indici", lambda: ingest_indices(indices=None)),
            ("Fise emitenti", lambda: ingest_issuers(symbols=None, max_age=6, from_raw=False)),
        ]
    steps += [
        ("Ajustari", lambda: adjust_cmd(symbols=None, show=0)),
        ("Texte rapoarte (lista de urmarire)", lambda: ingest_report_texts(days=30, all_symbols=False)),
        ("Alerte", lambda: alerts(notify=notify, move=0.05)),
    ]
    failed = []
    for name, step in steps:
        typer.echo(f"\n== {name}")
        try:
            step()
        except Exception as e:  # un pas esuat nu le opreste pe celelalte
            failed.append(name)
            typer.echo(f"EROARE: {e!r}"[:300])
    if failed:
        typer.echo(f"\nPasi esuati: {', '.join(failed)}")
        raise typer.Exit(1)


@app.command()
def schedule():
    """Ruleaza `daily` in zilele lucratoare la 19:15 si `daily --full` sambata (pentru containerul de ingestie)."""
    from bvb import scheduler

    scheduler.loop(log=lambda m: typer.echo(m))


@app.command()
def snapshot():
    """Publica acum copia pentru citire (dashboard); se face automat la finalul comenzilor care scriu."""
    db.publish_snapshot(db.connect())
    typer.echo(f"Copie actualizata: {db.READ_PATH}")


@app.command()
def dashboard(
    port: int = typer.Option(8501),
    address: str = typer.Option(
        "127.0.0.1", help="Adresa de ascultare; 0.0.0.0 doar in container, fara port publicat (ADR 0004)."
    ),
):
    """Porneste dashboard-ul Streamlit (http://localhost:8501)."""
    import subprocess
    import sys
    from pathlib import Path

    path = Path(__file__).with_name("dashboard.py")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(path),
            "--server.port",
            str(port),
            "--server.address",
            address,  # implicit doar local: datele BVB sunt pentru uz personal
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        check=False,
    )


@app.command()
def reconcile(
    other: str = typer.Option("bvb_hist", help="Sursa comparata cu sumarul BVB: bvb_hist | yahoo."),
    threshold: float = typer.Option(0.01, help="Prag diferenta relativa."),
):
    """Compara inchiderile din sumarul BVB cu alta sursa."""
    df = reconcile_prices(db.connect(), other, threshold)
    typer.echo(df.to_string(index=False) if len(df) else f"Nicio zi comuna bvb/{other}.")


@app.command()
def status():
    """Rezumat continut baza de date."""
    con = db.connect()
    typer.echo(
        con.execute("""
        SELECT source, count(DISTINCT symbol) AS simboluri, count(*) AS randuri,
               min(date) AS de_la, max(date) AS pana_la
        FROM prices_eod GROUP BY source ORDER BY source
    """)
        .df()
        .to_string(index=False)
    )
    typer.echo("\nUltimele rulari:")
    typer.echo(
        con.execute(
            "SELECT ts, job, status, rows, left(message, 80) AS message FROM ingest_log ORDER BY id DESC LIMIT 5"
        )
        .df()
        .to_string(index=False)
    )
