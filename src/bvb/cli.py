import typer

from bvb import adjust, db
from bvb.ingest import bvb_history, bvb_summary, issuer, yahoo
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
    full: bool = typer.Option(False, help="Parcurge toata fereastra si umple golurile (nu se opreste la prima zi existenta)."),
    refresh: bool = typer.Option(False, help="Re-descarca si zilele deja existente."),
):
    """Preturi EOD din sumarul zilnic BVB (toate actiunile)."""
    con = db.connect()
    have = set() if refresh else {
        r[0] for r in con.execute("SELECT DISTINCT date FROM prices_eod WHERE source = 'bvb'").fetchall()
    }
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
        symbols = [r[0] for r in con.execute(
            f"SELECT symbol FROM instruments WHERE {' AND '.join(where)} ORDER BY symbol").fetchall()]
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
        symbols = [r[0] for r in con.execute("SELECT symbol FROM instruments ORDER BY symbol").fetchall()]
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
        "INSERT INTO instruments (symbol, market) VALUES (?, 'INDEX') ON CONFLICT (symbol) DO UPDATE SET market = 'INDEX'",
        [[i] for i in indices],
    )
    counts = bvb_history.ingest(con, indices, log=typer.echo)
    db.log_ingest(con, "bvb_indices", {"indices": indices}, "ok", sum(counts.values()))


@ingest_app.command("issuers")
def ingest_issuers(
    symbols: list[str] = typer.Argument(None, help="Simboluri; implicit actiunile neactualizate de --max-age zile."),
    max_age: int = typer.Option(7, help="Re-descarca fisele mai vechi de atatea zile."),
):
    """Fisa emitentului: date de baza, dividende, modificari de capital."""
    con = db.connect()
    if not symbols:
        symbols = [r[0] for r in con.execute(
            "SELECT symbol FROM instruments WHERE market <> 'INDEX' "
            "AND (issuer_updated IS NULL OR issuer_updated < now() - to_days(?)) ORDER BY symbol",
            [max_age]).fetchall()]
    ok = 0
    for symbol, html, err in issuer.fetch_snapshots(symbols):
        if err is not None:
            typer.echo(f"{symbol}: eroare {err!r}"[:200])
            continue
        issuer.save_raw(symbol, html)
        data = issuer.parse(symbol, html)
        issuer.store(con, data)
        ok += 1
        typer.echo(f"{symbol}: {len(data['dividends'])} dividende, {len(data['capital'])} modificari capital")
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
        symbols = [r[0] for r in con.execute(
            "SELECT symbol FROM instruments WHERE market <> 'INDEX' ORDER BY symbol").fetchall()]
    summary = adjust.run(con, symbols)
    db.log_ingest(con, "adjust", {"symbols": len(symbols)}, "ok", int(summary["days"].sum()) if len(summary) else 0)
    if len(summary):
        summary = summary.sort_values(["suspicious", "unknown", "max_div_yield"], ascending=False)
        typer.echo(summary.head(show).to_string(index=False))
        typer.echo(f"\n{len(summary)} simboluri; evenimente necunoscute: {summary['unknown'].sum()}, "
                   f"miscari suspecte: {summary['suspicious'].sum()}, dividende sarite: {summary['div_skipped'].sum()}")


PCT = {"cagr", "price_cagr", "bench_cagr", "volatility", "max_drawdown", "tracking_error",
       "div_yield", "pct_days_traded", "div_yield_12m", "pct_days_traded_1y"}


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
    typer.echo(f"Ultimul pret: {i['last_close']} ({i['last_date']}), capitalizare {cap}, "
               f"randament dividend 12 luni {i['div_yield_12m']:.1%}")
    typer.echo(f"Lichiditate 1 an: tranzactii in {i['pct_days_traded_1y']:.0%} din zile, "
               f"valoare medie zilnica {i['adv_value_1y']:,.0f} RON\n")
    w = r["windows"].T.infer_objects()
    w = w[["cagr", "price_cagr", "bench_cagr", "volatility", "sharpe", "sortino", "max_drawdown",
           "dd_peak", "dd_trough", "beta", "corr", "tracking_error", "info_ratio"]]
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
        capital=capital, rebalance=rebalance, fee=fee,
        tax=tax if tax == "auto" else float(tax), dividends=dividends, rf=rf,
    )
    r = portfolio.backtest(db.connect(), cfg)
    m = r.metrics
    typer.echo(f"Portofoliu: {', '.join(f'{s} {w:.0%}' for s, w in cfg.weights.items())}")
    typer.echo(f"Perioada: {r.nav.index[0].date()} – {r.nav.index[-1].date()}, rebalansare {rebalance}, "
               f"comision {fee:.2%}, impozit dividende {tax}, dividende {dividends}")
    for n in r.notes:
        typer.echo(f"  ! {n}")
    typer.echo("")
    rows = [
        ("Valoare finala", f"{m['final_value']:,.0f}", f"{r.benchmark.iloc[-1]:,.0f}"),
        ("CAGR", f"{m['cagr']:.2%}", f"{m['bench_cagr']:.2%}"),
        ("Volatilitate", f"{m['volatility']:.2%}", f"{m['bench_volatility']:.2%}"),
        ("Max drawdown", f"{m['max_drawdown']:.2%} ({m['dd_peak']} → {m['dd_trough']})", f"{m['bench_max_drawdown']:.2%}"),
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
    typer.echo(con.execute("""
        SELECT source, count(DISTINCT symbol) AS simboluri, count(*) AS randuri,
               min(date) AS de_la, max(date) AS pana_la
        FROM prices_eod GROUP BY source ORDER BY source
    """).df().to_string(index=False))
    typer.echo("\nUltimele rulari:")
    typer.echo(con.execute(
        "SELECT ts, job, status, rows, left(message, 80) AS message FROM ingest_log ORDER BY id DESC LIMIT 5").df().to_string(index=False))
