"""Stiri din fluxuri RSS publice, etichetate cu emitentii mentionati.

Potrivirea se face pe nume (fara forma juridica) si pe aliasuri uzuale, nu pe
simbol: simbolurile scurte (M, EL, SNP) ar da prea multe potriviri false.
"""

import re
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from bvb.config import USER_AGENT

FEEDS = {
    "zf": "https://www.zf.ro/rss",
    "profit": "https://www.profit.ro/rss",
}

# Nume uzuale in presa, pe langa denumirea oficiala.
ALIASES = {
    "SNP": ["petrom", "omv petrom"], "TLV": ["banca transilvania"], "H2O": ["hidroelectrica"],
    "SNG": ["romgaz"], "TGN": ["transgaz"], "TEL": ["transelectrica"], "SNN": ["nuclearelectrica"],
    "EL": ["electrica"], "BRD": ["brd groupe", "brd-groupe", "brd "], "FP": ["fondul proprietatea"],
    "DIGI": ["digi communications", "rcs&rds", "rcs & rds"], "M": ["medlife"], "ONE": ["one united"],
    "AQ": ["aquila part"], "TTS": ["transport trade services", "tts "], "WINE": ["purcari"],
    "SFG": ["sphera franchise"], "TRP": ["teraplast"], "COTE": ["conpet"], "BVB": ["bursa de valori bucuresti"],
    "ATB": ["antibiotice"], "ALR": ["alro"], "EBS": ["erste group"], "AROBS": ["arobs"],
    "BNET": ["bittnet"], "CFH": ["cris-tim", "cristim"], "PE": ["premier energy"], "OIL": ["oil terminal"],
    "LION": ["lion capital"], "EVER": ["evergent"], "TRANSI": ["transilvania investments"],
    "INFINITY": ["infinity capital"], "LONG": ["longshield"], "SAFE": ["safetech"],
}
LEGAL_FORMS = r"\b(s\.?a\.?|sa|s\.?r\.?l\.?|n\.?v\.?|ag|plc|se|societatea|compania|nationala)\b"


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t)


def name_keys(name: str) -> list[str]:
    """Cheia de cautare din denumirea oficiala (min. 2 cuvinte sau un cuvant lung)."""
    n = re.sub(LEGAL_FORMS, " ", norm(name))
    n = re.sub(r"[^a-z0-9& -]", " ", n)
    n = " ".join(n.split())
    words = n.split()
    if len(words) >= 2:
        return [" ".join(words[:2])]
    return [n] if len(n) >= 6 else []


def build_matcher(instruments: list[tuple[str, str]]):
    patterns = []
    for symbol, name in instruments:
        keys = ALIASES.get(symbol, []) + (name_keys(name) if name else [])
        for k in dict.fromkeys(keys):
            patterns.append((symbol, re.compile(r"(?<![a-z0-9])" + re.escape(k.strip()) + r"(?![a-z0-9])")))

    def match(text: str) -> list[str]:
        t = norm(text)
        return sorted({s for s, rx in patterns if rx.search(t)})

    return match


def parse_feed(source: str, xml: bytes) -> list[dict]:
    root = ElementTree.fromstring(xml)
    items = []
    for it in root.iter("item"):
        get = lambda tag: (it.findtext(tag) or "").strip()
        try:
            published = parsedate_to_datetime(get("pubDate")).replace(tzinfo=None) if get("pubDate") else None
        except (TypeError, ValueError):
            published = None
        summary = re.sub(r"<[^>]+>", " ", get("description"))
        items.append({"source": source, "url": get("link"), "title": get("title"),
                      "summary": " ".join(summary.split())[:1000], "published": published or datetime.now()})
    return items


def fetch(feeds: dict[str, str] = FEEDS) -> list[dict]:
    out = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for source, url in feeds.items():
            r = client.get(url)
            r.raise_for_status()
            out.extend(parse_feed(source, r.content))
    return out


def store(con, items: list[dict], match) -> int:
    n = 0
    for it in items:
        if not it["url"]:
            continue
        symbols = match(f"{it['title']} {it['summary']}")
        con.execute(
            """INSERT INTO news (url, source, published, title, summary, symbols) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (url) DO UPDATE SET symbols = excluded.symbols""",
            [it["url"], it["source"], it["published"], it["title"], it["summary"], symbols])
        n += 1
    return n
