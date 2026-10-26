"""Compara preturile de inchidere din sumarul BVB cu alta sursa pe zilele comune."""

RECONCILE_SQL = """
WITH pairs AS (
    SELECT b.symbol, b.date, b.close AS bvb, y.close AS other,
           abs(y.close / b.close - 1) AS diff
    FROM prices_eod b
    JOIN prices_eod y USING (date, symbol)
    WHERE b.source = 'bvb' AND y.source = ? AND b.close > 0
)
SELECT symbol,
       count(*)                                   AS days,
       count(*) FILTER (WHERE diff > ?)           AS mismatches,
       round(max(diff) * 100, 2)                  AS max_diff_pct,
       arg_max(date, diff)                        AS worst_date
FROM pairs
GROUP BY symbol
ORDER BY mismatches DESC, max_diff_pct DESC
"""


def reconcile(con, other: str = "bvb_hist", threshold: float = 0.01):
    return con.execute(RECONCILE_SQL, [other, threshold]).df()
