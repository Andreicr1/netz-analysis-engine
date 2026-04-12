"""
backfill_nav.py  —  NAV backfill com checkpoint e resume.

Processa instruments_universe em batches pequenos, salva progresso em
.nav_backfill_checkpoint.json, e retoma de onde parou se interrompido.

Uso:
    cd backend
    .venv\Scripts\python.exe -m scripts.backfill_nav
    .venv\Scripts\python.exe -m scripts.backfill_nav --batch-size 100 --lookback 3650
    .venv\Scripts\python.exe -m scripts.backfill_nav --reset   # apaga checkpoint e recomeça
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

import asyncpg

from app.services.providers.tiingo_instrument_provider import TiingoInstrumentProvider

DB = os.environ.get(
    "DATABASE_URL_SYNC",
    "postgresql://tsdbadmin:LFBuQ5TEio_dP47w5P201NydByiw2RO3@nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb",
).replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")

CHECKPOINT_FILE = Path(__file__).parent.parent / ".nav_backfill_checkpoint.json"
UPSERT_CHUNK = 500
MAX_NAN_RATIO = 0.05
_io_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


# ── Checkpoint ───────────────────────────────────────────────────────────────

def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text())
        done = set(data.get("done_tickers", []))
        print(f"[checkpoint] Retomando — {len(done)} tickers ja processados")
        return done
    return set()


def save_checkpoint(done: set[str]) -> None:
    CHECKPOINT_FILE.write_text(json.dumps({
        "done_tickers": sorted(done),
        "updated_at": datetime.now().isoformat(),
        "count": len(done),
    }, indent=2))


# ── Download ─────────────────────────────────────────────────────────────────

_provider = TiingoInstrumentProvider()


def _fetch_batch(tickers: list[str], period: str) -> dict:
    try:
        return _provider.fetch_batch_history(tickers, period=period)
    except Exception as e:
        print(f"  [WARN] Tiingo fetch failed: {e}")
        return {}


# ── Upsert ───────────────────────────────────────────────────────────────────

async def upsert_rows(conn: asyncpg.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO nav_timeseries
            (instrument_id, nav_date, nav, return_1d, return_type, currency, source)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (instrument_id, nav_date)
        DO UPDATE SET nav=EXCLUDED.nav, return_1d=EXCLUDED.return_1d,
                      return_type=EXCLUDED.return_type, source=EXCLUDED.source
    """
    total = 0
    for i in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[i: i + UPSERT_CHUNK]
        await conn.executemany(sql, [
            (r["instrument_id"], r["nav_date"], r["nav"],
             r["return_1d"], r["return_type"], r["currency"], r["source"])
            for r in chunk
        ])
        total += len(chunk)
    return total


# ── Process batch ─────────────────────────────────────────────────────────────

async def process_batch(
    conn: asyncpg.Connection,
    ticker_map: dict[str, tuple],  # ticker -> (instrument_id, currency)
    period: str,
    done: set[str],
    loop,
) -> tuple[int, int, list[str]]:
    """Download + upsert um batch. Retorna (tickers_ok, rows_upserted, skipped)."""
    tickers = list(ticker_map.keys())

    history = await loop.run_in_executor(_io_executor, _fetch_batch, tickers, period)

    rows: list[dict] = []
    ok: list[str] = []
    skipped: list[str] = []

    for ticker, (instrument_id, currency) in ticker_map.items():
        if ticker not in history or history[ticker].empty:
            skipped.append(ticker)
            continue
        tdf = history[ticker]
        if "Close" not in tdf.columns:
            skipped.append(ticker)
            continue
        close = tdf["Close"].dropna()
        nan_ratio = close.isna().sum() / max(len(close), 1)
        if nan_ratio > MAX_NAN_RATIO or (close <= 0).any():
            skipped.append(ticker)
            continue
        tdf = tdf.dropna(subset=["Close"])
        prev = None
        for idx, row in tdf.iterrows():
            nav_date = idx.date() if hasattr(idx, "date") else idx
            price = float(row["Close"])
            if price <= 0:
                prev = None
                continue
            ret = math.log(price / prev) if prev and prev > 0 else None
            prev = price
            rows.append({
                "instrument_id": instrument_id,
                "nav_date": nav_date,
                "nav": round(price, 6),
                "return_1d": round(ret, 8) if ret is not None else None,
                "return_type": "log",
                "currency": currency,
                "source": "tiingo",
            })
        ok.append(ticker)

    upserted = await upsert_rows(conn, rows)
    return len(ok), upserted, skipped


# ── Main ─────────────────────────────────────────────────────────────────────

async def main(batch_size: int, lookback: int, sleep_s: float, reset: bool) -> None:
    if reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print("[checkpoint] Resetado.")

    done = load_checkpoint()

    conn = await asyncpg.connect(DB, ssl="require")

    # Buscar instrumentos ativos com ticker — ordem explícita de prioridade:
    # 1. ETFs SEC (sec_etfs): taxa de sucesso Yahoo ~95%
    # 2. ESMA com yahoo_ticker confirmado: já resolvidos via esma_isin_ticker_map
    # 3. Mutual funds (sec_fund_classes): taxa de sucesso Yahoo <20%
    instruments = await conn.fetch("""
        SELECT iu.instrument_id,
               iu.ticker,
               COALESCE(iu.currency, 'USD') as currency,
               CASE
                   WHEN se.ticker IS NOT NULL    THEN 1  -- ETF SEC confirmado
                   WHEN ef.yahoo_ticker IS NOT NULL THEN 2  -- ESMA ticker resolvido
                   ELSE 3                                   -- MF / outros
               END as priority
        FROM instruments_universe iu
        LEFT JOIN sec_etfs se ON se.ticker = iu.ticker
        LEFT JOIN esma_funds ef ON ef.yahoo_ticker = iu.ticker
        WHERE iu.is_active = true
          AND iu.ticker IS NOT NULL
          AND iu.ticker != ''
        ORDER BY priority ASC, iu.ticker ASC
    """)

    # Filtrar os ja processados
    pending = [r for r in instruments if r["ticker"].upper() not in done]
    total = len(instruments)
    remaining = len(pending)

    period_map = {365: "1y", 730: "2y", 1095: "3y", 1825: "5y", 3650: "10y"}
    period = next((v for k, v in sorted(period_map.items()) if lookback <= k), "10y")

    print(f"Total instrumentos: {total}")
    print(f"Ja processados:     {len(done)}")
    print(f"Pendentes:          {remaining}")
    print(f"Batch size:         {batch_size}")
    print(f"Period:             {period} ({lookback} dias)")
    print(f"Sleep entre batches: {sleep_s}s")
    print()

    loop = asyncio.get_event_loop()
    total_ok = 0
    total_rows = 0
    total_skipped = 0
    start_time = time.time()

    for i in range(0, remaining, batch_size):
        batch = pending[i: i + batch_size]
        ticker_map = {
            r["ticker"].upper(): (r["instrument_id"], r["currency"])
            for r in batch
        }

        batch_num = i // batch_size + 1
        total_batches = (remaining + batch_size - 1) // batch_size
        elapsed = time.time() - start_time
        done_pct = (len(done) + total_ok) / total * 100

        print(f"Batch {batch_num}/{total_batches} | {len(ticker_map)} tickers | "
              f"{done_pct:.1f}% concluido | elapsed: {elapsed:.0f}s")

        ok, rows, skipped = await process_batch(conn, ticker_map, period, done, loop)

        # Marcar como done e salvar checkpoint
        for t in ticker_map:
            done.add(t)
        save_checkpoint(done)

        total_ok += ok
        total_rows += rows
        total_skipped += len(skipped)

        tickers_shown = list(ticker_map.keys())[:5]
        print(f"  ok={ok} rows={rows:,} skipped={len(skipped)} | {tickers_shown}...")

        if i + batch_size < remaining:
            await asyncio.sleep(sleep_s)

    await conn.close()

    elapsed = time.time() - start_time
    print()
    print("=" * 55)
    print(f"CONCLUIDO em {elapsed/60:.1f} minutos")
    print(f"  Tickers processados : {total_ok}")
    print(f"  Tickers skipped     : {total_skipped}")
    print(f"  Rows upserted       : {total_rows:,}")
    print(f"  Checkpoint salvo em : {CHECKPOINT_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Tickers por batch Tiingo (default: 100)")
    parser.add_argument("--lookback", type=int, default=3650,
                        help="Dias de historico (default: 3650 = 10y)")
    parser.add_argument("--sleep", type=float, default=3.0,
                        help="Segundos entre batches (default: 3)")
    parser.add_argument("--reset", action="store_true",
                        help="Apagar checkpoint e reprocessar tudo")
    args = parser.parse_args()
    asyncio.run(main(args.batch_size, args.lookback, args.sleep, args.reset))
