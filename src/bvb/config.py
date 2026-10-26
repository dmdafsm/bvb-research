import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("BVB_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "bvb.duckdb"
# Copie doar pentru citire, publicata la finalul fiecarei comenzi care scrie;
# dashboard-ul o citeste, deci merge si in timpul colectarilor.
READ_PATH = DATA_DIR / "bvb_read.duckdb"

BVB_BASE = "https://bvb.ro"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
)

# Pause between requests to the same site, in seconds.
REQUEST_DELAY = 2.0
