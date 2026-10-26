import numpy as np
import pandas as pd
import pytest

from bvb import risk


def test_ledoit_wolf_shrinks_toward_scaled_identity():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(40, 10))  # putine observatii fata de dimensiune
    cov, shrink = risk.ledoit_wolf(x)
    sample = np.cov(x - x.mean(0), rowvar=False, bias=True)
    assert 0 < shrink <= 1
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov).min() > np.linalg.eigvalsh(sample).min()
    assert np.trace(cov) == pytest.approx(np.trace(sample))


def test_historical_var_cvar():
    r = pd.Series(np.linspace(-0.10, 0.09, 20))  # -10%, -9%, ..., 9%
    var, cvar = risk.historical_var(r, 0.90)
    assert var == pytest.approx(0.081, abs=1e-3)
    assert cvar == pytest.approx(0.095, abs=1e-3)


def test_parametric_var_normal():
    var, cvar = risk.parametric_var(0.01, 0.99)
    assert var == pytest.approx(0.02326, abs=1e-4)
    assert cvar == pytest.approx(0.02665, abs=1e-4)


def test_risk_contributions_sum_to_one():
    cov = np.array([[0.04, 0.01], [0.01, 0.01]])
    w = np.array([0.5, 0.5])
    sigma, rc = risk.risk_contributions(w, cov)
    assert sigma == pytest.approx(np.sqrt(0.25 * 0.04 + 0.25 * 0.01 + 2 * 0.25 * 0.01))
    assert rc.sum() == pytest.approx(1.0)
    assert rc[0] > rc[1]  # pozitia mai volatila domina riscul


def test_liquidatable_share():
    w = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})
    liq = pd.DataFrame({"days_to_liquidate": [0.5, 10.0, np.nan]}, index=w.index)
    assert risk.liquidatable_share(liq, w, 1) == pytest.approx(0.5 + 0.3 * 0.1)
    assert risk.liquidatable_share(liq, w, 20) == pytest.approx(0.8)  # C nu se tranzactioneaza deloc
