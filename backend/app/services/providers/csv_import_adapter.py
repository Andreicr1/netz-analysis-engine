"""CSV import adapter for bulk instrument ingestion.

NOT an InstrumentDataProvider — CSV is an import mechanism, not a market data
provider. Forcing both into the same interface would be a Liskov violation.

Security: Sanitizes CSV cells against formula injection (=, +, -, @, tab, cr).
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.providers.protocol import RawInstrumentData

logger = logging.getLogger(__name__)

# ── CSV formula injection defense ─────────────────────────────────
_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r"})

# ── Required columns per instrument type ──────────────────────────
_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "fund": frozenset({"name", "aum_usd", "manager_name", "inception_date"}),
    "bond": frozenset({"name", "maturity_date", "coupon_rate_pct", "issuer_name"}),
    "equity": frozenset({"name", "market_cap_usd", "sector", "exchange"}),
}

# Common columns present in all instrument types
_COMMON_COLUMNS = frozenset({"name", "isin", "ticker", "asset_class", "geography", "currency"})


@dataclass(frozen=True, slots=True)
class CsvRowError:
    """Validation error for a single CSV row."""

    row_number: int
    column: str | None
    message: str


@dataclass(frozen=True, slots=True)
class CsvImportResult:
    """Result of CSV import operation."""

    imported: int
    skipped: int
    errors: list[CsvRowError] = field(default_factory=list)
    instruments: list[RawInstrumentData] = field(default_factory=list)


def _sanitize_cell(value: str) -> str:
    """Sanitize a cell value against CSV formula injection."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


class CsvImportAdapter:
    """Parses CSV files into RawInstrumentData with per-row validation."""

    def parse(
        self,
        file_bytes: io.BytesIO,
        instrument_type: str,
    ) -> CsvImportResult:
        """Parse CSV and return validated instruments + errors.

        Args:
            file_bytes: CSV file content as BytesIO.
            instrument_type: One of 'fund', 'bond', 'equity'.

        Returns:
            CsvImportResult with imported instruments and any row errors.
        """
        if instrument_type not in _REQUIRED_COLUMNS:
            return CsvImportResult(
                imported=0,
                skipped=0,
                errors=[CsvRowError(row_number=0, column=None, message=f"Unknown instrument_type: {instrument_type}")],
            )

        required = _REQUIRED_COLUMNS[instrument_type]
        errors: list[CsvRowError] = []
        instruments: list[RawInstrumentData] = []
        seen_isins: set[str] = set()

        try:
            text = file_bytes.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return CsvImportResult(
                imported=0,
                skipped=0,
                errors=[CsvRowError(row_number=0, column=None, message="File is not valid UTF-8")],
            )

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return CsvImportResult(
                imported=0,
                skipped=0,
                errors=[CsvRowError(row_number=0, column=None, message="CSV has no header row")],
            )

        # Validate required columns exist
        headers = frozenset(reader.fieldnames)
        missing = required - headers
        if missing:
            return CsvImportResult(
                imported=0,
                skipped=0,
                errors=[CsvRowError(
                    row_number=0,
                    column=None,
                    message=f"Missing required columns: {sorted(missing)}",
                )],
            )

        for row_num, row in enumerate(reader, start=2):
            # Sanitize all cells
            sanitized = {k: _sanitize_cell(v.strip()) if v else "" for k, v in row.items() if k}

            # Validate required fields are non-empty
            row_errors = []
            for col in required:
                if not sanitized.get(col):
                    row_errors.append(CsvRowError(
                        row_number=row_num,
                        column=col,
                        message=f"Required field '{col}' is empty",
                    ))

            if row_errors:
                errors.extend(row_errors)
                continue

            # ISIN dedup
            isin = sanitized.get("isin", "").upper() or None
            if isin:
                if isin in seen_isins:
                    errors.append(CsvRowError(
                        row_number=row_num,
                        column="isin",
                        message=f"Duplicate ISIN: {isin}",
                    ))
                    continue
                seen_isins.add(isin)

            # Build attributes dict (all non-common columns)
            attrs = {
                k: sanitized[k]
                for k in sanitized
                if k not in _COMMON_COLUMNS and sanitized[k]
            }

            # Numeric validation for known numeric fields
            attrs = self._validate_numeric_attrs(attrs, row_num, errors)

            instruments.append(RawInstrumentData(
                ticker=sanitized.get("ticker") or None,
                isin=isin,
                name=sanitized["name"],
                instrument_type=instrument_type,
                asset_class=sanitized.get("asset_class") or self._default_asset_class(instrument_type),
                geography=sanitized.get("geography") or "unknown",
                currency=sanitized.get("currency") or "USD",
                source="csv",
                raw_attributes=attrs,
            ))

        return CsvImportResult(
            imported=len(instruments),
            skipped=len(errors),
            errors=errors,
            instruments=instruments,
        )

    @staticmethod
    def _default_asset_class(instrument_type: str) -> str:
        """Infer default asset_class from instrument type."""
        if instrument_type == "bond":
            return "fixed_income"
        return "equity"

    @staticmethod
    def _validate_numeric_attrs(
        attrs: dict[str, Any],
        row_num: int,
        errors: list[CsvRowError],
    ) -> dict[str, Any]:
        """Validate and coerce known numeric fields."""
        numeric_fields = {
            "aum_usd", "market_cap_usd", "coupon_rate_pct",
            "management_fee_pct", "performance_fee_pct",
            "min_free_float_pct", "pe_ratio_ttm", "dividend_yield_pct",
        }
        result = dict(attrs)
        for field_name in numeric_fields:
            if field_name in result and result[field_name]:
                try:
                    val = float(result[field_name])
                    if val < 0 and field_name in ("aum_usd", "market_cap_usd"):
                        errors.append(CsvRowError(
                            row_number=row_num,
                            column=field_name,
                            message=f"{field_name} cannot be negative: {val}",
                        ))
                    result[field_name] = str(val)
                except ValueError:
                    errors.append(CsvRowError(
                        row_number=row_num,
                        column=field_name,
                        message=f"Invalid number for {field_name}: {result[field_name]}",
                    ))
                    result.pop(field_name, None)
        return result
