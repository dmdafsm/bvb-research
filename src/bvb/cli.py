import typer

from bvb import db
from bvb.ingest import bvb_history, bvb_summary, yahoo
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
