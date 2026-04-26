"""PR-Q11 — Instrument Identity Resolver Worker.

Resolves and enriches instrument identifiers from 5 sources:
  1. SEC company_tickers.json (local file)
  2. SEC company_tickers_mf.json (fetched from SEC)
  3. ESMA Fund Register (DB join)
  4. SEC ADV bulk (DB join via sec_managers + sec_manager_funds)
  5. OpenFIGI /v3/mapping (external API — Phase 3)

Lock: 900_110 (pg_try_advisory_lock).
Frequency: weekly + on-demand post-universe_sync.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

IDENTITY_RESOLVER_LOCK_ID = 900_110

SEC_MF_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_USER_AGENT = "Netz/1.0 (andrei@investintell.com)"

# Per-field source authority (highest number = highest authority).
# Higher authority overwrites lower; equal authority with different value -> conflict.
FIELD_AUTHORITY: dict[str, dict[str, int]] = {
    "cik_padded": {
        "sec_company_tickers": 3,
        "sec_company_tickers_mf": 2,
        "sec_adv": 1,
    },
    "cik_unpadded": {
        "sec_company_tickers": 3,
        "sec_company_tickers_mf": 2,
        "sec_adv": 1,
    },
    "sec_series_id": {"sec_company_tickers_mf": 3},
    "sec_class_id": {"sec_company_tickers_mf": 3},
    "sec_crd": {"sec_adv": 3},
    "sec_private_fund_id": {"sec_adv": 3},
    "isin": {"esma": 3, "openfigi": 2},
    "cusip_8": {"openfigi": 3},
    "cusip_9": {"openfigi": 3},
    "figi": {"openfigi": 3},
    "ticker": {
        "sec_company_tickers": 4,
        "sec_company_tickers_mf": 3,
        "esma": 2,
        "openfigi": 1,
    },
    "ticker_exchange": {"openfigi": 3},
    "mic": {"openfigi": 3},
    "lei": {"esma": 3, "openfigi": 2},
    "esma_manager_id": {"esma": 3},
}


# ---------------------------------------------------------------------------
# Source data structures
# ---------------------------------------------------------------------------


# Per-field VARCHAR length limits from instrument_identity schema (migration 0177).
# Sources occasionally emit values that exceed these limits (e.g. OpenFIGI may
# return a composite ticker like "TICKER:EXCH:MIC" that is too wide). Without
# pre-validation those rows fail the whole INSERT with StringDataRightTruncationError
# and the entire instrument's identity row is lost.
_FIELD_MAX_LENGTH: dict[str, int] = {
    "cik_padded": 10,
    "cik_unpadded": 10,
    "sec_series_id": 15,
    "sec_class_id": 15,
    "sec_crd": 10,
    "sec_private_fund_id": 50,
    "cusip_8": 8,
    "cusip_9": 9,
    "isin": 12,
    "sedol": 7,
    "figi": 12,
    "ticker": 20,
    "ticker_exchange": 20,
    "mic": 4,
    "lei": 20,
    "esma_manager_id": 20,
}


class SourceResult:
    """Container for identity fields discovered by a single source."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.fields: dict[str, str | None] = {}

    def set(self, field: str, value: str | None) -> None:
        if value is None:
            return
        max_len = _FIELD_MAX_LENGTH.get(field)
        if max_len is not None and len(value) > max_len:
            logger.warning(
                "identity_resolver.field_too_long",
                source=self.source_name,
                field=field,
                value_length=len(value),
                max_length=max_len,
                value_preview=value[:50],
            )
            return
        self.fields[field] = value


# ---------------------------------------------------------------------------
# UPSERT logic (6 rules from plan v2 L508-516)
# ---------------------------------------------------------------------------


async def _upsert_identity(
    db: AsyncSession,
    instrument_id: str,
    source_results: list[SourceResult],
) -> None:
    """Apply source results to instrument_identity with per-field authority."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Fetch current row
    row = (
        await db.execute(
            text(
                "SELECT * FROM instrument_identity "
                "WHERE instrument_id = :iid"
            ),
            {"iid": instrument_id},
        )
    ).first()

    if row is None:
        # Initial insert — collect all fields, apply authority
        merged: dict[str, tuple[str, str, int]] = {}  # field -> (value, source, authority)
        for sr in source_results:
            for field, value in sr.fields.items():
                if value is None:
                    continue
                auth = FIELD_AUTHORITY.get(field, {}).get(sr.source_name, 0)
                existing = merged.get(field)
                if existing is None or auth > existing[2]:
                    merged[field] = (value, sr.source_name, auth)
                elif auth == existing[2] and value != existing[0]:
                    # Equal authority conflict — keep first, record conflict later
                    pass

        if not merged:
            return

        # Build INSERT
        cols = ["instrument_id"]
        vals: dict[str, Any] = {"iid": instrument_id}
        identity_sources: dict[str, dict] = {}
        conflict_state: dict[str, Any] = {}

        for field, (value, source, _auth) in merged.items():
            cols.append(field)
            param_name = f"v_{field}"
            vals[param_name] = value
            identity_sources[field] = {
                "source": source,
                "observed_at": now_iso,
            }

        # Check for equal-authority conflicts
        for sr in source_results:
            for field, value in sr.fields.items():
                if value is None:
                    continue
                m = merged.get(field)
                if m is None:
                    continue
                auth = FIELD_AUTHORITY.get(field, {}).get(sr.source_name, 0)
                if auth == m[2] and value != m[0] and sr.source_name != m[1]:
                    if field not in conflict_state:
                        conflict_state[field] = {"values": [], "resolved": False}
                    conflict_state[field]["values"].append({
                        "value": value,
                        "source": sr.source_name,
                        "observed_at": now_iso,
                    })
                    # Also record the winning value
                    if not any(
                        e["source"] == m[1]
                        for e in conflict_state[field]["values"]
                    ):
                        conflict_state[field]["values"].insert(0, {
                            "value": m[0],
                            "source": m[1],
                            "observed_at": now_iso,
                        })

        # Determine resolution status
        canonical_fields = {
            "cik_padded", "sec_series_id", "isin", "cusip_9",
            "ticker", "sec_private_fund_id", "esma_manager_id",
        }
        candidate_fields = {
            "sec_crd", "ticker", "cik_padded", "sec_series_id",
            "sec_private_fund_id", "esma_manager_id",
        }
        has_canonical = any(f in merged for f in canonical_fields)
        has_candidate = any(f in merged for f in candidate_fields)

        if has_canonical:
            status = "canonical"
        elif has_candidate:
            status = "candidate"
        else:
            status = "unresolved"

        col_str = ", ".join(cols + [
            "resolution_status", "identity_sources", "conflict_state",
        ])
        param_str = ", ".join(
            [":iid"] +
            [f":v_{f}" for f in merged] +
            [":status", ":sources", ":conflicts"]
        )
        vals["status"] = status
        vals["sources"] = json.dumps(identity_sources)
        vals["conflicts"] = json.dumps(conflict_state)

        await db.execute(
            text(f"INSERT INTO instrument_identity ({col_str}) VALUES ({param_str})"),
            vals,
        )
        return

    # --- UPDATE existing row ---
    current_sources = dict(row.identity_sources) if row.identity_sources else {}
    current_conflicts = dict(row.conflict_state) if row.conflict_state else {}
    updates: dict[str, Any] = {}
    new_sources = dict(current_sources)
    new_conflicts = dict(current_conflicts)

    for sr in source_results:
        for field, value in sr.fields.items():
            if value is None:
                continue

            incoming_auth = FIELD_AUTHORITY.get(field, {}).get(sr.source_name, 0)
            current_value = getattr(row, field, None)
            current_source_info = current_sources.get(field, {})
            current_source_name = current_source_info.get("source", "")
            current_auth = FIELD_AUTHORITY.get(field, {}).get(current_source_name, 0)

            if current_value is None:
                # Rule 6: Initial NULL -> insert with provenance
                updates[field] = value
                new_sources[field] = {
                    "source": sr.source_name,
                    "observed_at": now_iso,
                }
            elif incoming_auth > current_auth:
                # Rule 2: Higher authority overwrites
                updates[field] = value
                new_sources[field] = {
                    "source": sr.source_name,
                    "observed_at": now_iso,
                }
            elif incoming_auth < current_auth:
                # Rule 1: Lower authority skips silently
                pass
            elif value == current_value:
                # Rule 3: Equal authority, same value -> refresh observed_at
                new_sources[field] = {
                    "source": sr.source_name,
                    "observed_at": now_iso,
                }
            else:
                # Rule 4/5: Equal authority, different value -> conflict
                if field not in new_conflicts:
                    new_conflicts[field] = {"values": [], "resolved": False}
                conflict_values = new_conflicts[field].get("values", [])
                # Add current value if not present
                if not any(e.get("value") == current_value for e in conflict_values):
                    conflict_values.append({
                        "value": current_value,
                        "source": current_source_name,
                        "observed_at": current_source_info.get("observed_at", now_iso),
                    })
                # Add incoming value
                if not any(e.get("value") == value for e in conflict_values):
                    conflict_values.append({
                        "value": value,
                        "source": sr.source_name,
                        "observed_at": now_iso,
                    })
                new_conflicts[field]["values"] = conflict_values

    if updates or new_sources != current_sources or new_conflicts != current_conflicts:
        set_clauses = []
        params: dict[str, Any] = {"iid": instrument_id}

        for field, value in updates.items():
            param_name = f"u_{field}"
            set_clauses.append(f"{field} = :{param_name}")
            params[param_name] = value

        set_clauses.append("identity_sources = :sources")
        params["sources"] = json.dumps(new_sources)
        set_clauses.append("conflict_state = :conflicts")
        params["conflicts"] = json.dumps(new_conflicts)
        set_clauses.append("updated_at = NOW()")

        # Recalculate resolution status
        canonical_fields = {
            "cik_padded", "sec_series_id", "isin", "cusip_9",
            "ticker", "sec_private_fund_id", "esma_manager_id",
        }
        all_fields = {**{f: getattr(row, f) for f in canonical_fields}, **updates}
        has_canonical = any(v is not None for f, v in all_fields.items() if f in canonical_fields)
        if has_canonical:
            set_clauses.append("resolution_status = 'canonical'")
        elif any(
            getattr(row, f, None) is not None or updates.get(f) is not None
            for f in ("sec_crd", "ticker", "cik_padded", "sec_series_id",
                      "sec_private_fund_id", "esma_manager_id")
        ):
            set_clauses.append("resolution_status = 'candidate'")

        set_str = ", ".join(set_clauses)
        await db.execute(
            text(f"UPDATE instrument_identity SET {set_str} WHERE instrument_id = :iid"),
            params,
        )


# ---------------------------------------------------------------------------
# Source 1: SEC company_tickers.json (local file)
# ---------------------------------------------------------------------------


def _load_company_tickers_local() -> dict[str, dict]:
    """Load SEC company_tickers.json from local file.

    Returns {cik_unpadded: {"ticker": str, "title": str}} or raises.
    """
    path = os.environ.get(
        "SEC_COMPANY_TICKERS_JSON_PATH",
        r"C:\Users\Andrei\Desktop\EDGAR FILES\company_tickers.json",
    )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    result: dict[str, dict] = {}
    for entry in data.values():
        cik_str = str(entry.get("cik_str", ""))
        ticker = entry.get("ticker", "")
        title = entry.get("title", "")
        if cik_str and ticker:
            result[cik_str] = {"ticker": ticker, "title": title}
    return result


async def _source_1_company_tickers(
    db: AsyncSession,
    target_ids: list[str],
) -> tuple[dict[str, SourceResult], bool]:
    """Source 1: Match instruments to SEC company_tickers.json by ticker.

    Returns (instrument_id -> SourceResult, success).
    """
    source_name = "sec_company_tickers"
    results: dict[str, SourceResult] = {}

    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            tickers_data = await loop.run_in_executor(pool, _load_company_tickers_local)
    except Exception as e:
        logger.warning("identity_resolver.source_1_failed", error=str(e)[:200])
        return results, False

    # Build CIK -> ticker reverse map
    cik_to_data: dict[str, dict] = {}
    ticker_to_cik: dict[str, str] = {}
    for cik_str, info in tickers_data.items():
        padded = cik_str.zfill(10)
        cik_to_data[padded] = info
        cik_to_data[cik_str] = info
        ticker_to_cik[info["ticker"].upper()] = cik_str

    # Fetch target instruments with their current ticker and sec_cik
    rows = await db.execute(
        text(
            "SELECT instrument_id::text, ticker, "
            "attributes->>'sec_cik' AS sec_cik "
            "FROM instruments_universe "
            "WHERE instrument_id = ANY(:ids)"
        ),
        {"ids": target_ids},
    )

    for row in rows.fetchall():
        sr = SourceResult(source_name)
        iid = row.instrument_id

        # Try matching by sec_cik attribute
        sec_cik = row.sec_cik
        if sec_cik:
            stripped = sec_cik.lstrip("0") or "0"
            padded = stripped.zfill(10)
            if stripped in cik_to_data or padded in cik_to_data:
                info = cik_to_data.get(padded) or cik_to_data.get(stripped, {})
                sr.set("cik_padded", padded)
                sr.set("cik_unpadded", stripped)
                if info.get("ticker"):
                    sr.set("ticker", info["ticker"])

        # Try matching by ticker
        ticker = row.ticker
        if ticker and ticker.upper() in ticker_to_cik:
            cik_str = ticker_to_cik[ticker.upper()]
            padded = cik_str.zfill(10)
            stripped = cik_str.lstrip("0") or "0"
            sr.set("cik_padded", padded)
            sr.set("cik_unpadded", stripped)
            sr.set("ticker", ticker.upper())

        if sr.fields:
            results[iid] = sr

    return results, True


# ---------------------------------------------------------------------------
# Source 2: SEC company_tickers_mf.json (fetched from SEC)
# ---------------------------------------------------------------------------


def _download_mf_tickers() -> dict[str, Any]:
    """Download SEC company_tickers_mf.json."""
    from urllib.request import Request, urlopen

    req = Request(SEC_MF_TICKERS_URL, headers={"User-Agent": SEC_USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


async def _source_2_mf_tickers(
    db: AsyncSession,
    target_ids: list[str],
) -> tuple[dict[str, SourceResult], bool]:
    """Source 2: SEC company_tickers_mf.json — CIK, series_id, class_id, ticker."""
    source_name = "sec_company_tickers_mf"
    results: dict[str, SourceResult] = {}

    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            data = await loop.run_in_executor(pool, _download_mf_tickers)
    except Exception as e:
        logger.warning("identity_resolver.source_2_failed", error=str(e)[:200])
        return results, False

    # Parse MF tickers: data["data"] = [(cik, series_id, class_id, symbol), ...]
    rows_data = data.get("data", [])

    # Build lookup by series_id -> (cik, class_id, symbol)
    series_to_data: dict[str, list[tuple[str, str, str]]] = {}
    ticker_to_data: dict[str, tuple[str, str, str]] = {}
    for entry in rows_data:
        if len(entry) < 4:
            continue
        cik, series_id, class_id, symbol = str(entry[0]), str(entry[1]), str(entry[2]), str(entry[3])
        if series_id:
            if series_id not in series_to_data:
                series_to_data[series_id] = []
            series_to_data[series_id].append((cik, class_id, symbol))
        if symbol:
            ticker_to_data[symbol.upper()] = (cik, series_id, class_id)

    # Fetch target instruments
    inst_rows = await db.execute(
        text(
            "SELECT instrument_id::text, ticker, "
            "attributes->>'sec_cik' AS sec_cik, "
            "attributes->>'series_id' AS series_id, "
            "attributes->>'sec_series_id' AS sec_series_id "
            "FROM instruments_universe "
            "WHERE instrument_id = ANY(:ids)"
        ),
        {"ids": target_ids},
    )

    for row in inst_rows.fetchall():
        sr = SourceResult(source_name)
        iid = row.instrument_id
        matched = False

        # Match by series_id
        sid = row.series_id or row.sec_series_id
        if sid and sid in series_to_data:
            entries = series_to_data[sid]
            if entries:
                cik, class_id, symbol = entries[0]  # Take first match
                stripped = cik.lstrip("0") or "0"
                sr.set("cik_padded", stripped.zfill(10))
                sr.set("cik_unpadded", stripped)
                sr.set("sec_series_id", sid)
                if class_id:
                    sr.set("sec_class_id", class_id)
                if symbol:
                    sr.set("ticker", symbol)
                matched = True

        # Match by ticker
        if not matched and row.ticker and row.ticker.upper() in ticker_to_data:
            cik, series_id, class_id = ticker_to_data[row.ticker.upper()]
            stripped = cik.lstrip("0") or "0"
            sr.set("cik_padded", stripped.zfill(10))
            sr.set("cik_unpadded", stripped)
            if series_id:
                sr.set("sec_series_id", series_id)
            if class_id:
                sr.set("sec_class_id", class_id)
            sr.set("ticker", row.ticker.upper())

        if sr.fields:
            results[iid] = sr

    return results, True


# ---------------------------------------------------------------------------
# Source 3: ESMA Fund Register (DB join)
# ---------------------------------------------------------------------------


async def _source_3_esma(
    db: AsyncSession,
    target_ids: list[str],
) -> tuple[dict[str, SourceResult], bool]:
    """Source 3: ESMA join — match instruments to esma_funds by name/ISIN."""
    source_name = "esma"
    results: dict[str, SourceResult] = {}

    try:
        # Match by ISIN (from instruments_universe.isin when it's real ISIN)
        # or by name similarity
        rows = await db.execute(
            text("""
                SELECT
                    iu.instrument_id::text,
                    ef.isin AS esma_isin,
                    ef.esma_manager_id,
                    em.lei
                FROM instruments_universe iu
                JOIN esma_funds ef
                    ON ef.yahoo_ticker = iu.ticker
                    OR (
                        iu.isin IS NOT NULL
                        AND iu.isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'
                        AND ef.isin = iu.isin
                    )
                LEFT JOIN esma_managers em
                    ON em.esma_id = ef.esma_manager_id
                WHERE iu.instrument_id = ANY(:ids)
            """),
            {"ids": target_ids},
        )

        for row in rows.fetchall():
            sr = SourceResult(source_name)
            iid = row.instrument_id

            if row.esma_isin:
                sr.set("isin", row.esma_isin)
            if row.esma_manager_id:
                sr.set("esma_manager_id", row.esma_manager_id)
            if row.lei:
                sr.set("lei", row.lei)

            if sr.fields:
                results[iid] = sr

    except Exception as e:
        logger.warning("identity_resolver.source_3_failed", error=str(e)[:200])
        return results, False

    return results, True


# ---------------------------------------------------------------------------
# Source 4: SEC ADV bulk (crd_number + fund_id, NOT cik)
# ---------------------------------------------------------------------------


async def _source_4_sec_adv(
    db: AsyncSession,
    target_ids: list[str],
) -> tuple[dict[str, SourceResult], bool]:
    """Source 4: SEC ADV — match via sec_managers.crd + sec_manager_funds.fund_id."""
    source_name = "sec_adv"
    results: dict[str, SourceResult] = {}

    try:
        rows = await db.execute(
            text("""
                SELECT
                    iu.instrument_id::text,
                    sm.cik AS adviser_cik,
                    sm.crd_number AS sec_crd,
                    smf.fund_id AS sec_private_fund_id
                FROM instruments_universe iu
                JOIN sec_managers sm
                    ON sm.crd_number = iu.attributes->>'sec_crd'
                LEFT JOIN sec_manager_funds smf
                    ON smf.crd_number = sm.crd_number
                WHERE iu.instrument_id = ANY(:ids)
                  AND iu.attributes->>'sec_crd' IS NOT NULL
            """),
            {"ids": target_ids},
        )

        for row in rows.fetchall():
            sr = SourceResult(source_name)
            iid = row.instrument_id

            if row.sec_crd:
                sr.set("sec_crd", row.sec_crd)
            if row.adviser_cik:
                stripped = row.adviser_cik.lstrip("0") or "0"
                sr.set("cik_padded", stripped.zfill(10))
                sr.set("cik_unpadded", stripped)
            if row.sec_private_fund_id:
                sr.set("sec_private_fund_id", row.sec_private_fund_id)

            if sr.fields:
                results[iid] = sr

    except Exception as e:
        logger.warning("identity_resolver.source_4_failed", error=str(e)[:200])
        return results, False

    return results, True


# ---------------------------------------------------------------------------
# Source 5: OpenFIGI /v3/mapping (external API)
# ---------------------------------------------------------------------------

OPENFIGI_BATCH_SIZE = 100
OPENFIGI_RATE_LIMIT_REQUESTS = 25
OPENFIGI_RATE_LIMIT_WINDOW_S = 6.0
OPENFIGI_ENDPOINT = "https://api.openfigi.com/v3/mapping"


async def _openfigi_batch_request(
    tickers: list[dict[str, str]],
    api_key: str,
) -> list[dict | None]:
    """Send a batch of up to 100 items to OpenFIGI /v3/mapping."""
    import aiohttp

    headers = {
        "Content-Type": "application/json",
        "X-OPENFIGI-APIKEY": api_key,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            OPENFIGI_ENDPOINT,
            json=tickers,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                text_body = await resp.text()
                logger.warning(
                    "openfigi.request_failed",
                    status=resp.status,
                    body=text_body[:200],
                )
                return [None] * len(tickers)
            return await resp.json()


async def _source_5_openfigi(
    db: AsyncSession,
    target_ids: list[str],
) -> tuple[dict[str, SourceResult], bool]:
    """Source 5: OpenFIGI — resolve ticker to CUSIP, ISIN, FIGI, MIC."""
    source_name = "openfigi"
    results: dict[str, SourceResult] = {}

    api_key = os.environ.get("OPENFIGI_API_KEY", "")
    if not api_key:
        logger.warning("identity_resolver.openfigi_no_api_key")
        return results, False

    # Fetch tickers from target instruments
    rows = await db.execute(
        text(
            "SELECT instrument_id::text, ticker "
            "FROM instruments_universe "
            "WHERE instrument_id = ANY(:ids) AND ticker IS NOT NULL"
        ),
        {"ids": target_ids},
    )
    ticker_rows = rows.fetchall()

    if not ticker_rows:
        return results, True

    # Build batches of 100
    batches: list[list[tuple[str, str]]] = []  # (instrument_id, ticker)
    current_batch: list[tuple[str, str]] = []
    for row in ticker_rows:
        current_batch.append((row.instrument_id, row.ticker))
        if len(current_batch) >= OPENFIGI_BATCH_SIZE:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    from app.core.runtime.gates import get_openfigi_gate

    gate = get_openfigi_gate()
    request_count = 0

    for batch in batches:
        # Rate limiting: 25 requests per 6 seconds
        if request_count > 0 and request_count % OPENFIGI_RATE_LIMIT_REQUESTS == 0:
            await asyncio.sleep(OPENFIGI_RATE_LIMIT_WINDOW_S)

        figi_request = [
            {"idType": "TICKER", "idValue": ticker, "exchCode": "US"}
            for _, ticker in batch
        ]

        try:
            response = await gate.call(
                f"openfigi_batch_{request_count}",
                lambda req=figi_request: _openfigi_batch_request(req, api_key),
            )
        except Exception as e:
            logger.warning(
                "identity_resolver.openfigi_batch_error",
                batch=request_count,
                error=str(e)[:200],
            )
            continue

        request_count += 1

        if not response or len(response) != len(batch):
            continue

        for (iid, ticker), result_item in zip(batch, response, strict=False):
            if result_item is None or "data" not in result_item:
                continue

            data_items = result_item["data"]
            if not data_items:
                continue

            # Take first match
            item = data_items[0]
            sr = SourceResult(source_name)

            figi_val = item.get("compositeFIGI") or item.get("figi")
            if figi_val:
                sr.set("figi", figi_val)

            cusip = item.get("cusip")
            if cusip:
                if len(cusip) == 9:
                    sr.set("cusip_9", cusip)
                    sr.set("cusip_8", cusip[:8])
                elif len(cusip) == 8:
                    sr.set("cusip_8", cusip)

            isin_val = item.get("isin")
            if isin_val:
                sr.set("isin", isin_val)

            exch_code = item.get("exchCode")
            if exch_code:
                sr.set("ticker_exchange", f"{ticker}:{exch_code}")
            mic_val = item.get("micCode")
            if mic_val:
                sr.set("mic", mic_val)

            if ticker:
                sr.set("ticker", ticker)

            if sr.fields:
                results[iid] = sr

    return results, True


# ---------------------------------------------------------------------------
# Main worker entry point
# ---------------------------------------------------------------------------


async def run_identity_resolver(
    db: AsyncSession,
    *,
    target_instrument_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run the identity resolver for target instruments or all stale/new ones.

    Returns summary dict with counts and any errors.
    """
    # Acquire advisory lock
    lock_result = await db.execute(
        text("SELECT pg_try_advisory_lock(:lock_id)"),
        {"lock_id": IDENTITY_RESOLVER_LOCK_ID},
    )
    acquired = lock_result.scalar()
    if not acquired:
        logger.info("identity_resolver.lock_busy", lock_id=IDENTITY_RESOLVER_LOCK_ID)
        return {"status": "skipped", "reason": "lock_busy"}

    try:
        return await _resolve_identities(db, target_instrument_ids=target_instrument_ids)
    except Exception:
        await db.rollback()
        raise
    finally:
        try:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": IDENTITY_RESOLVER_LOCK_ID},
            )
        except Exception:
            # If the session is in failed state, rollback first then unlock
            await db.rollback()
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": IDENTITY_RESOLVER_LOCK_ID},
            )


async def _resolve_identities(
    db: AsyncSession,
    *,
    target_instrument_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Core resolution logic."""
    # Get target instruments
    if target_instrument_ids:
        target_rows = await db.execute(
            text(
                "SELECT instrument_id::text FROM instruments_universe "
                "WHERE instrument_id = ANY(:ids)"
            ),
            {"ids": target_instrument_ids},
        )
    else:
        target_rows = await db.execute(
            text("""
                SELECT iu.instrument_id::text
                FROM instruments_universe iu
                LEFT JOIN instrument_identity ii USING (instrument_id)
                WHERE ii.instrument_id IS NULL
                   OR ii.last_resolved_at IS NULL
                   OR ii.last_resolved_at < NOW() - INTERVAL '30 days'
            """)
        )

    target_ids = [r.instrument_id for r in target_rows.fetchall()]
    if not target_ids:
        logger.info("identity_resolver.no_targets")
        return {"status": "ok", "targets": 0}

    logger.info("identity_resolver.start", targets=len(target_ids))

    # Run all 5 sources (4 internal + OpenFIGI)
    source_funcs = [
        ("source_1", _source_1_company_tickers),
        ("source_2", _source_2_mf_tickers),
        ("source_3", _source_3_esma),
        ("source_4", _source_4_sec_adv),
        ("source_5", _source_5_openfigi),
    ]

    all_results: dict[str, list[SourceResult]] = {iid: [] for iid in target_ids}
    all_success = True

    for source_name, source_func in source_funcs:
        try:
            results, success = await source_func(db, target_ids)
            if not success:
                all_success = False
                logger.warning(
                    f"identity_resolver.{source_name}_partial_failure"
                )
            for iid, sr in results.items():
                all_results[iid].append(sr)
            logger.info(
                f"identity_resolver.{source_name}_complete",
                matches=len(results),
            )
        except Exception as e:
            all_success = False
            logger.error(
                f"identity_resolver.{source_name}_error",
                error=str(e)[:200],
            )
            await db.rollback()

    # Apply UPSERT for each instrument
    upserted = 0
    for iid, sources in all_results.items():
        if sources:
            try:
                await _upsert_identity(db, iid, sources)
                upserted += 1
            except Exception as e:
                logger.error(
                    "identity_resolver.upsert_error",
                    instrument_id=iid,
                    error=str(e)[:200],
                )
                await db.rollback()

    # Update last_resolved_at only on full success
    if all_success and upserted > 0:
        await db.execute(
            text(
                "UPDATE instrument_identity SET last_resolved_at = NOW() "
                "WHERE instrument_id = ANY(:ids)"
            ),
            {"ids": target_ids},
        )

    await db.commit()

    summary = {
        "status": "ok",
        "targets": len(target_ids),
        "upserted": upserted,
        "all_sources_success": all_success,
    }
    logger.info("identity_resolver.complete", **summary)
    return summary
