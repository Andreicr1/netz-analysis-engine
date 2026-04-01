"""
seed_nav_barchart.py
Processa arquivos xlsx exportados pelo Barchart for Excel e faz upsert
em instruments_universe + nav_timeseries.

Formatos suportados:
  - Single ticker (ex: ABR-D.xlsx):
      Row 0: "Time Series" | "ABR-D"
      Row 1: "Date"        | "Close"
      Row 2+: date         | price

  - Multi ticker (Barchart History com varios simbolos):
      Row 0: "Time Series" | "SPY"   | "QQQ"  | ...
      Row 1: "Date"        | "Close" | "Close" | ...
      Row 2+: date         | price1  | price2  | ...

Uso:
    python -m scripts.seed_nav_barchart D:/Projetos/nav_batches/
    python -m scripts.seed_nav_barchart D:/Projetos/seed_nav.xlsx
    python -m scripts.seed_nav_barchart D:/Projetos/nav_batches/ --dry-run
    python -m scripts.seed_nav_barchart D:/Projetos/nav_batches/ --source barchart
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Iterator

import asyncpg
import pandas as pd

DB = os.environ.get(
    "DATABASE_URL_SYNC",
    "postgresql://tsdbadmin:LFBuQ5TEio_dP47w5P201NydByiw2RO3@nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb",
).replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")

UPSERT_CHUNK = 500
MAX_NAN_RATIO = 0.05
MAX_DAILY_LOG_RETURN = 0.30  # flag extremo — nao bloqueia, so loga


# ── Parser ──────────────────────────────────────────────────────────────────

def parse_barchart_xlsx(path: Path) -> Iterator[tuple[str, pd.DataFrame]]:
    """
    Yields (ticker, df) where df has columns [nav_date: date, nav: float].
    Handles both single-ticker and multi-ticker Barchart exports.
    """
    df_raw = pd.read_excel(path, header=None, dtype=str)

    if df_raw.shape[1] < 2:
        print(f"  [SKIP] {path.name}: menos de 2 colunas")
        return

    # Row 0 = ticker headers, Row 1 = field labels ("Date", "Close", ...)
    # Row 2+ = data
    ticker_row = df_raw.iloc[0]
    field_row  = df_raw.iloc[1]

    # Detect number of ticker columns (skip column 0 which is "Time Series"/"Date")
    tickers: list[tuple[int, str]] = []  # (col_index, ticker_symbol)
    for col_idx in range(1, df_raw.shape[1]):
        ticker_label = str(ticker_row.iloc[col_idx]).strip()
        field_label  = str(field_row.iloc[col_idx]).strip().lower()
        if ticker_label in ("nan", "", "None") or field_label != "close":
            continue
        tickers.append((col_idx, ticker_label))

    if not tickers:
        print(f"  [SKIP] {path.name}: nenhum campo 'Close' encontrado")
        return

    # Data rows start at index 2
    date_col = pd.to_datetime(df_raw.iloc[2:, 0], errors="coerce")

    for col_idx, ticker in tickers:
        close_col = pd.to_numeric(df_raw.iloc[2:, col_idx], errors="coerce")
        df = pd.DataFrame({"nav_date": date_col.values, "nav": close_col.values})
        df = df.dropna(subset=["nav_date", "nav"])
        df = df[df["nav"] > 0]
        df["nav_date"] = df["nav_date"].apply(lambda x: x.date() if hasattr(x, "date") else x)
        df = df.sort_values("nav_date").reset_index(drop=True)

        if df.empty:
            print(f"  [SKIP] {ticker}: sem dados validos apos limpeza")
            continue

        yield ticker, df


# ── Log returns ─────────────────────────────────────────────────────────────

def compute_log_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona coluna return_1d (log return). Primeiro row fica None."""
    navs = df["nav"].values
    returns: list[float | None] = [None]
    for i in range(1, len(navs)):
        if navs[i] > 0 and navs[i - 1] > 0:
            r = math.log(navs[i] / navs[i - 1])
            if abs(r) > MAX_DAILY_LOG_RETURN:
                print(f"    [WARN] Extreme return {r:.4f} on {df['nav_date'].iloc[i]}")
            returns.append(r)
        else:
            returns.append(None)
    df["return_1d"] = returns
    return df


# ── DB helpers ───────────────────────────────────────────────────────────────

async def get_or_create_instrument(
    conn: asyncpg.Connection,
    ticker: str,
    dry_run: bool,
) -> uuid.UUID | None:
    """
    Lookup instrument_id by ticker. Se nao existir, cria entrada basica global.
    Retorna None em dry_run para instrumentos nao existentes.
    """
    row = await conn.fetchrow(
        "SELECT instrument_id FROM instruments_universe WHERE ticker = $1", ticker
    )
    if row:
        return row["instrument_id"]

    if dry_run:
        return None  # nao criar em dry_run

    # Criar instrumento basico como 'equity' (sem check constraint de attrs)
    # universe_sync vai reclassificar e enriquecer depois com dados SEC/ESMA
    new_id = uuid.uuid4()
    await conn.execute("""
        INSERT INTO instruments_universe
            (instrument_id, instrument_type, name, ticker, asset_class,
             geography, currency, is_active, attributes)
        VALUES ($1, 'equity', $2, $3, 'equity', 'unknown', 'USD', true,
                jsonb_build_object('market_cap_usd', '0', 'sector', 'unknown', 'exchange', 'unknown'))
        ON CONFLICT ON CONSTRAINT uq_iu_ticker DO NOTHING
    """, new_id, ticker, ticker)

    # Re-fetch (pode ter sido inserido por outra sessao concorrente)
    row = await conn.fetchrow(
        "SELECT instrument_id FROM instruments_universe WHERE ticker = $1", ticker
    )
    return row["instrument_id"] if row else None


async def upsert_nav_batch(
    conn: asyncpg.Connection,
    instrument_id: uuid.UUID,
    df: pd.DataFrame,
    source: str,
    dry_run: bool,
) -> int:
    """Upsert df em nav_timeseries em chunks. Retorna rows inseridas."""
    if dry_run:
        return len(df)

    rows = [
        {
            "instrument_id": instrument_id,
            "nav_date": row.nav_date,
            "nav": round(float(row.nav), 6),
            "return_1d": round(float(row.return_1d), 8) if row.return_1d is not None and not math.isnan(float(row.return_1d)) else None,
            "return_type": "log",
            "currency": "USD",
            "source": source,
        }
        for row in df.itertuples()
    ]

    upsert_sql = """
        INSERT INTO nav_timeseries
            (instrument_id, nav_date, nav, return_1d, return_type, currency, source)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (instrument_id, nav_date)
        DO UPDATE SET
            nav         = EXCLUDED.nav,
            return_1d   = EXCLUDED.return_1d,
            return_type = EXCLUDED.return_type,
            source      = EXCLUDED.source
    """

    total = 0
    for i in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[i : i + UPSERT_CHUNK]
        await conn.executemany(
            upsert_sql,
            [(r["instrument_id"], r["nav_date"], r["nav"],
              r["return_1d"], r["return_type"], r["currency"], r["source"])
             for r in chunk],
        )
        total += len(chunk)

    return total


# ── Main ─────────────────────────────────────────────────────────────────────

async def process_file(
    conn: asyncpg.Connection,
    path: Path,
    source: str,
    dry_run: bool,
) -> dict:
    stats = {"file": path.name, "tickers": 0, "rows": 0, "skipped": 0, "errors": []}

    for ticker, df in parse_barchart_xlsx(path):
        # NaN ratio check
        nan_ratio = df["nav"].isna().sum() / max(len(df), 1)
        if nan_ratio > MAX_NAN_RATIO:
            print(f"  [SKIP] {ticker}: NaN ratio {nan_ratio:.2%} > {MAX_NAN_RATIO:.0%}")
            stats["skipped"] += 1
            continue

        df = compute_log_returns(df)

        try:
            instrument_id = await get_or_create_instrument(conn, ticker, dry_run)
        except Exception as e:
            msg = f"{ticker}: instrument lookup failed — {e}"
            print(f"  [ERROR] {msg}")
            stats["errors"].append(msg)
            continue

        if instrument_id is None:
            if dry_run:
                print(f"  [DRY-RUN] {ticker}: {len(df)} rows — instrument nao existe (seria criado)")
            else:
                print(f"  [SKIP] {ticker}: nao foi possivel criar instrumento")
                stats["skipped"] += 1
            continue

        try:
            upserted = await upsert_nav_batch(conn, instrument_id, df, source, dry_run)
        except Exception as e:
            msg = f"{ticker}: upsert failed — {e}"
            print(f"  [ERROR] {msg}")
            stats["errors"].append(msg)
            continue

        prefix = "[DRY-RUN] " if dry_run else ""
        print(f"  {prefix}{ticker}: {upserted} rows ({df['nav_date'].min()} to {df['nav_date'].max()})")
        stats["tickers"] += 1
        stats["rows"] += upserted

    return stats


async def main(input_path: str, source: str, dry_run: bool) -> None:
    p = Path(input_path)
    if p.is_file():
        files = [p]
    elif p.is_dir():
        files = sorted(p.glob("*.xlsx"))
    else:
        print(f"Caminho nao encontrado: {input_path}")
        sys.exit(1)

    if not files:
        print("Nenhum arquivo .xlsx encontrado.")
        sys.exit(1)

    print(f"Arquivos a processar: {len(files)}")
    if dry_run:
        print("[DRY-RUN MODE — nenhuma escrita no DB]")
    print()

    conn = await asyncpg.connect(DB, ssl="require")

    total_tickers = 0
    total_rows = 0
    all_errors: list[str] = []

    for f in files:
        print(f"=== {f.name} ===")
        stats = await process_file(conn, f, source, dry_run)
        total_tickers += stats["tickers"]
        total_rows    += stats["rows"]
        all_errors    += stats["errors"]
        print()

    await conn.close()

    print("=" * 50)
    print(f"Resultado {'(DRY-RUN) ' if dry_run else ''}:")
    print(f"  Tickers processados : {total_tickers}")
    print(f"  Rows upserted       : {total_rows:,}")
    if all_errors:
        print(f"  Erros ({len(all_errors)}):")
        for e in all_errors[:20]:
            print(f"    - {e}")
    else:
        print("  Erros: 0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed nav_timeseries from Barchart xlsx exports")
    parser.add_argument("input", help="Arquivo .xlsx ou diretorio contendo .xlsx")
    parser.add_argument("--source", default="barchart", help="Valor do campo source (default: barchart)")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem escrever no DB")
    args = parser.parse_args()
    asyncio.run(main(args.input, args.source, args.dry_run))
