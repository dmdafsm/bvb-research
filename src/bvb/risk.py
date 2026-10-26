"""Risc de portofoliu: VaR/CVaR, contributii la risc, corelatii, stres,
concentrare si risc de lichiditate.

Ponderile sunt considerate constante pe fereastra de estimare (portofoliul de azi
aplicat pe istoricul recent). Randamentele vin din `tr_close` pe calendarul BET.
In zilele fara tranzactii randamentul e 0 (pret reportat), ceea ce subestimeaza
riscul si corelatiile actiunilor nelichide; corelatiile si beta se estimeaza de
aceea pe randamente saptamanale.
"""

from dataclasses import dataclass
from datetime import date
from statistics import NormalDist

import numpy as np
import pandas as pd

from bvb import analytics

# Episoade de stres pe piata romaneasca (aprox. varf -> minim al BET).
SCENARIOS = [
    ("Criza financiara globala", date(2007, 7, 20), date(2009, 2, 27)),
    ("Criza datoriilor din zona euro", date(2011, 7, 1), date(2011, 11, 25)),
    ("OUG 114/2018 (taxa pe active)", date(2018, 12, 7), date(2018, 12, 28)),
    ("COVID-19", date(2020, 2, 19), date(2020, 3, 23)),
    ("Invazia Ucrainei", date(2022, 2, 10), date(2022, 3, 7)),
]
INDEX_SHOCKS = [-0.10, -0.20, -0.30]
STATE_CONTROL_PCT = 50.0


# --- estimare --------------------------------------------------------------


def ledoit_wolf(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Covarianta cu shrinkage Ledoit-Wolf catre identitate scalata. -> (cov, intensitate)"""
    x = x - x.mean(axis=0)
    n, p = x.shape
    s = x.T @ x / n
    mu = np.trace(s) / p
    target = mu * np.eye(p)
    d2 = ((s - target) ** 2).sum()
    if d2 == 0:
        return s, 0.0
    sq = (x**2).sum(axis=1)
    b2 = min(((sq**2).sum() - n * (s**2).sum()) / n**2, d2)
    shrink = b2 / d2
    return shrink * target + (1 - shrink) * s, float(shrink)


def returns_matrix(con, symbols: list[str], end: date | None, years: float, weekly: bool = False) -> pd.DataFrame:
    values = analytics.series(con, symbols, end=end)
    last = values.index[-1]
    values = values[values.index > last - pd.DateOffset(years=years)]
    if weekly:
        values = values.resample("W-FRI").last()
    return values.pct_change().iloc[1:]


# --- VaR / CVaR --------------------------------------------------------------


def historical_var(r: pd.Series, conf: float) -> tuple[float, float]:
    """-> (VaR, CVaR) ca pierderi pozitive."""
    r = r.dropna()
    q = r.quantile(1 - conf)
    return float(-q), float(-r[r <= q].mean())


def parametric_var(sigma: float, conf: float) -> tuple[float, float]:
    z = NormalDist().inv_cdf(conf)
    return z * sigma, sigma * NormalDist().pdf(z) / (1 - conf)


def risk_contributions(w: np.ndarray, cov: np.ndarray) -> tuple[float, np.ndarray]:
    """-> (volatilitate portofoliu, contributia fiecarei pozitii ca fractie din risc)"""
    sigma = float(np.sqrt(w @ cov @ w))
    return sigma, w * (cov @ w) / sigma**2


# --- rezultate ---------------------------------------------------------------


@dataclass
class RiskReport:
    as_of: date
    window: tuple[date, date]
    var: pd.DataFrame  # pe niveluri de incredere: historical / parametric, VaR si CVaR
    positions: pd.DataFrame  # pondere, volatilitate, beta, contributie la risc, lichiditate
    correlation: pd.DataFrame
    stress: pd.DataFrame
    concentration: dict
    by_sector: pd.Series
    shrinkage: float
    notes: list[str]


def stress_tests(con, weights: pd.Series, betas: pd.Series, end: date | None) -> pd.DataFrame:
    symbols = list(weights.index)
    tr = analytics.series(con, symbols, end=end)
    bench = analytics.benchmark_series(con, end=end)
    rows = []
    for name, start, stop in SCENARIOS:
        s, e = pd.Timestamp(start), pd.Timestamp(stop)
        if s < bench.index[0] or e > bench.index[-1]:
            continue
        b_ret = bench.asof(e) / bench.asof(s) - 1
        rets, proxied = {}, []
        for sym in symbols:
            first = tr[sym].first_valid_index()
            if first is not None and first <= s:
                rets[sym] = tr[sym].asof(e) / tr[sym].asof(s) - 1
            else:  # actiunea nu era listata: aproximare prin beta
                rets[sym] = betas.get(sym, 1.0) * b_ret
                proxied.append(sym)
        p_ret = float(sum(weights[k] * v for k, v in rets.items()))
        rows.append(
            {
                "scenario": name,
                "start": start,
                "end": stop,
                "portfolio": p_ret,
                "benchmark": b_ret,
                "proxied": ", ".join(proxied),
            }
        )
    for shock in INDEX_SHOCKS:
        rows.append(
            {
                "scenario": f"BET-TR {shock:.0%} (prin beta)",
                "start": None,
                "end": None,
                "portfolio": float((weights * betas.reindex(weights.index).fillna(1.0)).sum() * shock),
                "benchmark": shock,
                "proxied": "",
            }
        )
    return pd.DataFrame(rows)


def concentration(con, weights: pd.Series) -> tuple[dict, pd.Series]:
    syms = list(weights.index)
    info = (
        con.execute(
            f"""
        SELECT i.symbol, coalesce(i.sector, 'NECUNOSCUT') AS sector, coalesce(i.currency, 'RON') AS currency,
               coalesce(s.state_pct, 0) AS state_pct
        FROM instruments i LEFT JOIN state_ownership s USING (symbol)
        WHERE i.symbol IN ({",".join("?" * len(syms))})
    """,
            syms,
        )
        .df()
        .set_index("symbol")
        .reindex(syms)
    )
    hhi = float((weights**2).sum())
    sorted_w = weights.sort_values(ascending=False)
    by_sector = weights.groupby(info["sector"]).sum().sort_values(ascending=False)
    out = {
        "hhi": hhi,
        "effective_n": 1 / hhi,
        "top1": float(sorted_w.iloc[0]),
        "top3": float(sorted_w.iloc[:3].sum()),
        "max_sector": by_sector.index[0],
        "max_sector_weight": float(by_sector.iloc[0]),
        "state_controlled": float(weights[info["state_pct"] >= STATE_CONTROL_PCT].sum()),
        "state_any": float(weights[info["state_pct"] > 0].sum()),
        "non_ron": float(weights[info["currency"] != "RON"].sum()),
    }
    return out, by_sector


def liquidity_risk(
    con, weights: pd.Series, value: float, end: date, participation: float, days: int = 182
) -> pd.DataFrame:
    """Zile necesare lichidarii fiecarei pozitii la `participation` din valoarea medie zilnica."""
    liq = analytics.liquidity(con, list(weights.index), end, days=days)
    position = weights * value
    capacity = liq["adv_value"].fillna(0) * participation
    d2l = (position / capacity).replace(np.inf, np.nan)
    return pd.DataFrame(
        {
            "position": position,
            "adv_value": liq["adv_value"],
            "pct_days_traded": liq["pct_days_traded"],
            "days_to_liquidate": d2l,
        }
    )


def liquidatable_share(liq: pd.DataFrame, weights: pd.Series, horizon_days: int) -> float:
    """Fractia din portofoliu care poate fi vanduta in `horizon_days` zile."""
    d = liq["days_to_liquidate"]
    frac = np.where(d.isna(), 0.0, np.minimum(1.0, horizon_days / d.where(d > 0, 1e-9)))
    return float((weights * frac).sum())


def report(
    con,
    weights: dict[str, float],
    value: float = 100_000.0,
    end: date | None = None,
    years: float = 3.0,
    horizon: int = 1,
    confidences=(0.95, 0.99),
    participation: float = 0.2,
) -> RiskReport:
    w = pd.Series(weights, dtype=float)
    w = w / w.sum()
    symbols = list(w.index)
    notes = []

    daily = returns_matrix(con, symbols, end, years)
    complete = daily.dropna()
    if len(complete) < 60:
        raise ValueError("Prea putine zile comune pentru estimare (minim 60).")
    if len(complete) < len(daily) * 0.9:
        notes.append(
            f"Doar {len(complete)} din {len(daily)} zile au date pentru toate pozitiile "
            "(listare recenta); estimarea foloseste perioada comuna."
        )
    as_of = complete.index[-1].date()
    port = complete @ w.values

    # VaR istoric pe orizont: randamente compuse pe ferestre suprapuse de `horizon` zile
    port_h = (1 + port).rolling(horizon).apply(np.prod, raw=True).dropna() - 1 if horizon > 1 else port
    cov_d, shrink = ledoit_wolf(complete.values)
    sigma_d, rc = risk_contributions(w.values, cov_d)
    var_rows = []
    for c in confidences:
        hv, hcv = historical_var(port_h, c)
        pv, pcv = parametric_var(sigma_d * np.sqrt(horizon), c)
        var_rows.append(
            {
                "confidence": c,
                "hist_var": hv,
                "hist_cvar": hcv,
                "param_var": pv,
                "param_cvar": pcv,
                "hist_var_ron": hv * value,
                "hist_cvar_ron": hcv * value,
            }
        )
    var = pd.DataFrame(var_rows).set_index("confidence")

    weekly = returns_matrix(con, [*symbols, analytics.BENCHMARK], end, years, weekly=True).dropna()
    corr = weekly[symbols].corr()
    bench_w = weekly[analytics.BENCHMARK]
    betas = weekly[symbols].apply(lambda col: np.cov(col, bench_w)[0, 1] / bench_w.var())

    liq = liquidity_risk(con, w, value, as_of, participation)
    positions = pd.DataFrame(
        {
            "weight": w,
            "volatility": complete.std() * np.sqrt(analytics.TRADING_DAYS),
            "beta_weekly": betas,
            "risk_contribution": pd.Series(rc, index=symbols),
            "pct_days_traded": liq["pct_days_traded"],
            "days_to_liquidate": liq["days_to_liquidate"],
        }
    )
    conc, by_sector = concentration(con, w)
    conc["portfolio_vol"] = sigma_d * np.sqrt(analytics.TRADING_DAYS)
    for h in (1, 5, 20):
        conc[f"liquidatable_{h}d"] = liquidatable_share(liq, w, h)
    stress = stress_tests(con, w, betas, end)
    return RiskReport(
        as_of, (complete.index[0].date(), as_of), var, positions, corr, stress, conc, by_sector, shrink, notes
    )
