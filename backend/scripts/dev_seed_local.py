"""dev_seed_local.py — Seed seletivo do Docker local a partir do prod.

Copia um subconjunto cirúrgico de dados do Timescale Cloud (prod) para
o Docker local (netz_engine), suficiente para desenvolvimento com zero
latência. NÃO usa pg_dump — usa COPY via SELECT, que:
  - Contorna chunks comprimidos do TimescaleDB
  - Permite filtros WHERE por data/instrumento
  - Nunca toca o schema (schema já aplicado via alembic upgrade head)

Uso:
  # Primeiro: alembic upgrade head (aponta para local via .env.dev)
  # Depois:
  python scripts/dev_seed_local.py
  python scripts/dev_seed_local.py --tables macro_data benchmark_nav  # só algumas
  python scripts/dev_seed_local.py --since 2023-01-01                 # janela menor
  python scripts/dev_seed_local.py --dry-run                          # mostra contagens

Requisitos:
  pip install psycopg2-binary python-dotenv
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# ── Carrega .env.dev (local) e .env (prod) ───────────────────────
_root = Path(__file__).resolve().parents[1]
_backend = _root / "backend"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_backend / ".env.dev", override=False)
load_dotenv(_root / ".env.dev", override=False)
load_dotenv(_backend / ".env", override=False)
load_dotenv(_root / ".env", override=False)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

# ── URLs ──────────────────────────────────────────────────────────
# ── URLs — lidas do ambiente, nunca hardcoded ─────────────────────
# Prod: vem do .env (raiz) carregado acima
# Local: vem do .env.dev carregado acima
_prod_url = os.environ.get("DATABASE_URL_SYNC", "")
_local_url = os.environ.get("DEV_DATABASE_URL_SYNC", "")

if not _prod_url:
    print("ERROR: DATABASE_URL_SYNC não encontrado. Certifique-se de ter .env com a URL do prod.")
    sys.exit(1)

# Converte asyncpg URL para psycopg2 se necessário
def _to_psycopg2_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )

PROD_DSN = _to_psycopg2_dsn(_prod_url)

# Local: se DEV_DATABASE_URL_SYNC não estiver definido, usa docker-compose default
LOCAL_DSN = _to_psycopg2_dsn(
    _local_url or "postgresql://netz:password@localhost:5434/netz_engine"
)

# ── Instrumentos de desenvolvimento ──────────────────────────────
# Tickers usados nos testes e2e + benchmarks do bloco padrão
DEV_TICKERS = [
    # Fundos de teste e2e
    "OAKMX", "DODGX", "PRWCX",
    # Benchmarks do bloco padrão
    "SPY", "AGG", "VNQ", "QQQ", "IWM", "EFA", "EMB",
    # ETFs líquidos para screener funcionar
    "BND", "GLD", "TLT", "LQD", "HYG", "IEF", "SHY",
]

# CIKs dos fundos de teste (para N-PORT e sec_manager_funds)
DEV_CIKS = [
    # BlackRock, Vanguard, Fidelity, T. Rowe Price, Dodge & Cox
    # (gestoras dos fundos de teste — garante dados de holdings)
    "0000802796",  # Dodge & Cox
    "0000884546",  # T. Rowe Price
    "0000815124",  # Nuveen (OAKMX)
]

# ── Definição das tabelas a copiar ────────────────────────────────

def build_table_specs(since: str, tickers: list[str], ciks: list[str]) -> list[dict]:
    """Retorna lista de specs para cada tabela.

    Cada spec tem:
      name:     nome da tabela
      query:    SELECT que será passado ao COPY ... TO STDOUT
      columns:  lista de colunas (None = SELECT *)
      truncate: se deve truncar a tabela local antes de copiar
    """
    ticker_list = "'" + "','".join(tickers) + "'"
    cik_list = "'" + "','".join(ciks) + "'"

    return [
        # ── Pequenas globais — cópia total ──────────────────────
        {
            "name": "macro_data",
            "query": f"SELECT * FROM macro_data WHERE time >= '{since}'",
            "truncate": True,
        },
        {
            "name": "benchmark_nav",
            "query": f"SELECT * FROM benchmark_nav WHERE time >= '{since}'",
            "truncate": True,
        },
        {
            "name": "treasury_data",
            "query": f"SELECT * FROM treasury_data WHERE time >= '{since}'",
            "truncate": True,
        },
        {
            "name": "allocation_blocks",
            "query": "SELECT * FROM allocation_blocks",
            "truncate": True,
        },
        {
            "name": "macro_regime_history",
            "query": f"SELECT * FROM macro_regime_history WHERE time >= '{since}'",
            "truncate": True,
        },
        # ── SEC estáticas — cópia total (são pequenas) ──────────
        {
            "name": "sec_managers",
            "query": "SELECT * FROM sec_managers",
            "truncate": True,
        },
        {
            "name": "sec_manager_funds",
            "query": "SELECT * FROM sec_manager_funds",
            "truncate": True,
        },
        {
            "name": "sec_registered_funds",
            "query": "SELECT * FROM sec_registered_funds",
            "truncate": True,
        },
        # ── nav_timeseries — só os tickers de dev ───────────────
        # Hypertable comprimida: COPY via SELECT descomprime automaticamente
        {
            "name": "nav_timeseries",
            "query": (
                f"SELECT * FROM nav_timeseries "
                f"WHERE ticker IN ({ticker_list}) "
                f"AND time >= '{since}'"
            ),
            "truncate": False,  # pode haver dados org-scoped — não truncar
        },
        # ── fund_risk_metrics — mesmos instrumentos ─────────────
        {
            "name": "fund_risk_metrics",
            "query": (
                f"SELECT frm.* FROM fund_risk_metrics frm "
                f"JOIN nav_timeseries nt ON nt.instrument_id = frm.instrument_id "
                f"WHERE nt.ticker IN ({ticker_list}) "
                f"AND frm.calculated_at >= '{since}' "
                f"AND frm.organization_id IS NULL"  # apenas globais
            ),
            "truncate": False,
        },
        # ── sec_instruments — subset dos dev instruments ─────────
        {
            "name": "sec_instruments",
            "query": (
                f"SELECT si.* FROM sec_instruments si "
                f"WHERE si.ticker IN ({ticker_list})"
            ),
            "truncate": True,
        },
        # ── N-PORT — últimos 2 quarters, CIKs dos fundos de dev ─
        {
            "name": "sec_nport_holdings",
            "query": (
                "SELECT * FROM sec_nport_holdings "
                "WHERE period_of_report >= (CURRENT_DATE - INTERVAL '9 months') "
                # Sem filtro de CIK — N-PORT é fund-level, pega os que existirem
                # para os instrumentos de dev via join seria complexo;
                # a janela de 9 meses já limita o volume adequadamente.
            ),
            "truncate": True,
        },
        # ── 13F — últimos 2 quarters, top managers ───────────────
        {
            "name": "sec_13f_holdings",
            "query": (
                f"SELECT h.* FROM sec_13f_holdings h "
                f"WHERE h.period_of_report >= (CURRENT_DATE - INTERVAL '9 months') "
                f"AND h.filer_cik IN ({cik_list})"
            ),
            "truncate": True,
        },
        {
            "name": "sec_13f_diffs",
            "query": (
                f"SELECT d.* FROM sec_13f_diffs d "
                f"WHERE d.period_of_report >= (CURRENT_DATE - INTERVAL '9 months') "
                f"AND d.filer_cik IN ({cik_list})"
            ),
            "truncate": True,
        },
    ]


def count_rows(conn, query: str) -> int:
    """Conta linhas que seriam copiadas sem transferi-las."""
    count_query = f"SELECT COUNT(*) FROM ({query}) _sub"
    with conn.cursor() as cur:
        cur.execute(count_query)
        return cur.fetchone()[0]


def copy_table(
    prod_conn,
    local_conn,
    spec: dict,
    dry_run: bool = False,
) -> int:
    """Copia uma tabela do prod para local via COPY binary.

    Retorna número de linhas copiadas (ou contagem estimada em dry_run).
    """
    name = spec["name"]
    query = spec["query"]
    truncate = spec.get("truncate", True)

    if dry_run:
        n = count_rows(prod_conn, query)
        print(f"  [DRY] {name}: {n:,} rows would be copied")
        return n

    # Conta para log
    n = count_rows(prod_conn, query)
    print(f"  Copying {name}: {n:,} rows ... ", end="", flush=True)
    t0 = time.time()

    with local_conn.cursor() as local_cur:
        if truncate:
            # Desabilita triggers temporariamente para evitar cascade issues
            local_cur.execute(f"TRUNCATE TABLE {name} CASCADE")

        # COPY OUT do prod → buffer em memória → COPY IN para local
        # Usa formato CSV para compatibilidade máxima com TimescaleDB
        copy_out_sql = f"COPY ({query}) TO STDOUT WITH (FORMAT csv, HEADER false, NULL '\\N')"
        copy_in_sql = f"COPY {name} FROM STDIN WITH (FORMAT csv, HEADER false, NULL '\\N')"

        import io
        buffer = io.BytesIO()

        with prod_conn.cursor() as prod_cur:
            prod_cur.copy_expert(copy_out_sql, buffer)

        buffer.seek(0)
        local_cur.copy_expert(copy_in_sql, buffer)

    local_conn.commit()
    elapsed = time.time() - t0
    print(f"done ({elapsed:.1f}s)")
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local Docker DB from prod")
    parser.add_argument(
        "--since",
        default=(date.today() - timedelta(days=365 * 3)).isoformat(),
        help="Start date for time-series data (default: 3 years ago)",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        help="Subset of table names to copy (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show row counts without copying",
    )
    args = parser.parse_args()

    specs = build_table_specs(args.since, DEV_TICKERS, DEV_CIKS)
    if args.tables:
        specs = [s for s in specs if s["name"] in args.tables]
        if not specs:
            print(f"No matching tables. Available: {[s['name'] for s in build_table_specs(args.since, DEV_TICKERS, DEV_CIKS)]}")
            sys.exit(1)

    print(f"\nDev seed — since={args.since}, tables={len(specs)}, dry_run={args.dry_run}")
    print("Source: Timescale Cloud (prod)")
    print("Target: localhost:5434/netz_engine\n")

    print("Connecting to prod ...", end="", flush=True)
    prod_conn = psycopg2.connect(PROD_DSN)
    prod_conn.set_session(readonly=True)  # garantia extra
    print(" OK")

    if not args.dry_run:
        print("Connecting to local ...", end="", flush=True)
        local_conn = psycopg2.connect(LOCAL_DSN)
        print(" OK\n")
    else:
        local_conn = None
        print()

    total_rows = 0
    t_start = time.time()

    for spec in specs:
        try:
            n = copy_table(prod_conn, local_conn, spec, dry_run=args.dry_run)
            total_rows += n
        except Exception as e:
            print(f"\n  ERROR on {spec['name']}: {e}")
            if local_conn:
                local_conn.rollback()
            # Continua com as próximas tabelas

    elapsed = time.time() - t_start
    print(f"\nDone. {total_rows:,} rows in {elapsed:.1f}s")
    print("Next: make serve   # backend local com dados reais, zero latência")

    prod_conn.close()
    if local_conn:
        local_conn.close()


if __name__ == "__main__":
    main()
