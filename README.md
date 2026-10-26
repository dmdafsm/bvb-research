# bvb-research

Instrument personal de analiză pentru companiile listate la BVB. Plan: [docs/plan.md](docs/plan.md), surse: [docs/surse-date.md](docs/surse-date.md).

## Instalare

```bash
uv sync
uv run playwright install chromium
uv run bvb init-db
```

## Prețuri EOD

```bash
uv run bvb ingest bvb            # sedintele noi de pe BVB (se opreste la prima zi existenta)
uv run bvb ingest bvb --full     # toata fereastra BVB (~30 zile), umple golurile
uv run bvb ingest history        # istoric complet din graficul BVB (brut + ajustat)
uv run bvb ingest yahoo          # optional: istoric Yahoo, pentru validare
uv run bvb reconcile             # inchideri sumar BVB vs grafic BVB (--other yahoo)
uv run bvb status
```

- Pagina de sumar BVB oferă doar ultimele ~30 de zile. Istoricul complet vine din API-ul graficului BVB (`source = 'bvb_hist'`, `adj_close` = ajustat de BVB), folosit cu acordul utilizatorului pentru uz personal.
- View-ul `prices` dă un singur preț pe zi și simbol: sumar BVB > grafic BVB > Yahoo.
- HTML-ul brut al fiecărei ședințe BVB se păstrează în `data/raw/bvb_summary/`.
- Datele sunt doar pentru uz personal (termenii BVB).

## Teste

```bash
uv run pytest
```
