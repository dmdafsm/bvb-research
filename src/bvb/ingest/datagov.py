"""Situatii financiare anuale de pe data.gov.ro (Ministerul Finantelor, licenta CC-BY 4.0).

Seturi: situatii_financiare_<an> (2008+), cate un fisier pe tip de raportare:
  BL_BS_SL (bilant lung/scurt), IR (IFRS), UU (format prescurtat), Inst_de_credit
  (banci), SIF, ASIG (asigurari), VS (sector financiar). Fiecare .txt are coloane
  CUI, CAEN, I1..In; semnificatia lui Ii e in .csv-ul descriptor cu acelasi nume.
Atentie: sunt situatii INDIVIDUALE (nu consolidate) ale emitentului.

Fisierele sunt mari (UU ~80 MB/an); le citim in flux si pastram doar CUI-urile
emitentilor listati.
"""

import csv
import io
import re
import time
import unicodedata

import httpx

API = "https://data.gov.ro/api/3/action"
# Tip -> fragment din numele fisierului, comparat fara '_' / ' ' (anii vechi: webblbsslan2010.txt).
KINDS = [("IR", "WEBIR"), ("BL", "BLBSSL"), ("BANK", "INST"), ("SIF", "SIF"),
         ("ASIG", "ASIG"), ("VS", "WEBVS"), ("UU", "WEBUU")]

# Coloanele bilantului standard (BL / IR / UU), cand lipseste descriptorul (ani vechi).
STANDARD_LABELS = [
    "CUI", "CAEN", "ACTIVE IMOBILIZATE - TOTAL", "ACTIVE CIRCULANTE - TOTAL", "Stocuri", "Creante",
    "Casa si conturi la banci", "CHELTUIELI IN AVANS", "DATORII", "VENITURI IN AVANS", "PROVIZIOANE",
    "CAPITALURI - TOTAL", "Capital subscris varsat", "Patrimoniul regiei", "Cifra de afaceri neta",
    "VENITURI TOTALE", "CHELTUIELI TOTALE", "Profit brut", "Pierdere bruta", "Profit net", "Pierdere neta",
    "Numar mediu de salariati",
]


def norm(label: str) -> str:
    s = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def kind_of(filename: str) -> str | None:
    f = re.sub(r"[_\s]+", "", filename.upper().replace("%20", ""))
    for kind, pattern in KINDS:
        if pattern in f:
            return kind
    return None


def packages(client: httpx.Client) -> dict[int, dict]:
    """An -> pachetul CKAN; varianta '_actualizat' are prioritate."""
    res = client.get(f"{API}/package_search", params={"q": "name:situatii_financiare*", "rows": 100}).json()
    out = {}
    for p in sorted(res["result"]["results"], key=lambda p: "actualizat" in p["name"]):
        m = re.search(r"(20\d\d)", p["name"])
        if m:
            out[int(m.group(1))] = p
    return out


def year_files(pkg: dict) -> dict[str, dict]:
    """Tip -> {'data': url .txt, 'desc': url .csv sau None}."""
    files: dict[str, dict] = {}
    for r in pkg["resources"]:
        name = r["url"].rsplit("/", 1)[-1]
        kind = kind_of(name)
        if not kind:
            continue
        slot = files.setdefault(kind, {"data": None, "desc": None})
        if name.lower().endswith(".txt"):
            slot["data"] = r["url"]
        elif name.lower().endswith(".csv"):
            slot["desc"] = r["url"]
    return {k: v for k, v in files.items() if v["data"]}


def parse_descriptor(text: str) -> list[str]:
    """Liniile 'eticheta;cod' -> etichetele in ordinea coloanelor."""
    return [line.split(";")[0].strip() for line in text.splitlines() if ";" in line]


def filter_rows(lines, cuis: set[str]) -> tuple[list[str], list[list[str]]]:
    """-> (antet, randurile CUI-urilor cautate)"""
    reader = csv.reader(lines)
    header = next(reader)
    return header, [row for row in reader if row and row[0].strip() in cuis]


def to_float(v: str) -> float | None:
    v = v.strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


# --- campuri standard ----------------------------------------------------------

def _first(values: dict[str, float], *patterns: str) -> float | None:
    for p in patterns:
        rx = re.compile(p)
        for label, v in values.items():
            if rx.search(label) and v is not None:
                return v
    return None


def _sum(values: dict[str, float], pattern: str) -> float | None:
    rx = re.compile(pattern)
    hits = [v for label, v in values.items() if rx.search(label) and v is not None]
    return sum(hits) if hits else None


def standardize(kind: str, values: dict[str, float]) -> dict:
    """Etichete normalizate -> campuri comune intre tipurile de raportare."""
    v = values
    out = {
        "revenue": _first(v, r"^cifra de afaceri neta"),
        "employees": _first(v, r"numar mediu de salariati"),
        "cash": _first(v, r"^casa si conturi"),
    }
    if kind == "BANK":
        # In unii ani coloanele din fisier nu urmeaza descriptorul; randul "Profit sau (-)
        # pierdere aferent(a) exercitiului" e consecvent. Cifra de afaceri nu e relevanta la banci.
        out["revenue"] = None
        out["total_revenue"] = None
        out["net_profit"] = _first(v, r"^profit sau \(-\) pierdere aferent", r"^profit sau pierdere aferent")
        out["total_assets"] = _sum(v, r"^(numerar|active financiare|investitii in filiale|imobilizari)")
        out["debts"] = _sum(v, r"^datorii financiare")
        out["equity"] = _sum(v, r"^(capital social|rezultatul reportat|alte rezerve|profit sau \(-\) pierdere)")
        out["cash"] = _first(v, r"^numerar si solduri")
    else:
        profit = _first(v, r"^profit(ul)? net")
        loss = _first(v, r"^pierdere +net")
        if profit is not None or loss is not None:
            out["net_profit"] = (profit or 0) - (loss or 0)
        else:
            c, d = _first(v, r"\(ct\.121\) \(sold creditor\)"), _first(v, r"\(ct\.121\) \(sold debitor\)")
            out["net_profit"] = (c or 0) - (d or 0) if c is not None or d is not None else None
        out["total_revenue"] = _first(v, r"^venituri( -)? totale")
        assets = [_first(v, r"^active imobilizate - total"), _first(v, r"^active circulante - total"),
                  _first(v, r"^cheltuieli in avans")]
        out["total_assets"] = sum(a for a in assets if a is not None) if any(a is not None for a in assets) else None
        out["debts"] = _first(v, r"^datorii$") if _first(v, r"^datorii$") is not None else _sum(
            v, r"^datorii ce trebuie(sc)? platite")
        out["equity"] = _first(v, r"^capitaluri proprii", r"^capitaluri - total", r"^capital - total")
    return out


def ingest_year(client: httpx.Client, year: int, pkg: dict, cuis: set[str], kinds: set[str], log=print) -> list[dict]:
    rows = []
    for kind, f in year_files(pkg).items():
        if kind not in kinds:
            continue
        labels = None
        if f["desc"]:
            labels = parse_descriptor(client.get(f["desc"]).content.decode("cp1250", errors="replace"))
        with client.stream("GET", f["data"], timeout=600) as r:
            r.raise_for_status()
            lines = (line for line in r.iter_lines())
            header, found = filter_rows(lines, cuis)
        if not labels or len(labels) != len(header):
            labels = STANDARD_LABELS if kind in ("BL", "IR", "UU") and len(header) == 22 else header
        for row in found:
            values = {norm(label): to_float(x) for label, x in zip(labels[2:], row[2:])}
            rows.append({"cui": row[0].strip(), "year": year, "kind": kind, "caen": row[1].strip(),
                         "values": values, **standardize(kind, values)})
        log(f"{year} {kind}: {len(found)} emitenti")
        time.sleep(0.5)
    return rows
