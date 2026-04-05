---
title: "refactor: Holdings Data Normalization & Schema Structuring"
type: refactor
status: completed
date: 2026-04-04
last_updated: 2026-04-04 21:18
---

# Holdings Data Normalization & Schema Structuring

## Overview

Following the successful refactor of the `Fund Data Percentage Normalization`, the Holdings dataset (specifically N-PORT data) presents similar data integrity issues that must be addressed to ensure accurately typed, normalized data for the frontend.

## Problem Statement

### 1. The Percentage Mismatch (x100 Multiplier)
Holdings percentages are currently being displayed incorrectly (e.g., 7.41% appears as 741.00%). 
This occurs because the raw data is passed as "100-based" (i.e., `7.41`), whereas the frontend's `Intl.NumberFormat` (using `style: "percent"`) expects pure decimal fractions (`0.0741`).

### 2. Incorrect Sector Allocation (The "RF" map bug)
Sector allocation attributes are currently misassigned. Instead of reflecting the specific sector of the held asset (e.g., "Cash"), it displays classifications like "Real Estate Fund" for cash vehicles (e.g. "Capital Group Central Cash Fund"). 
This happens because:
a) The N-PORT `sector` field contains SEC `issuerCat` classifications (like CORP, MUN, RF, UST).
b) There is a mapping bug in the N-PORT pipeline mapping `RF` to "Real Estate Fund" instead of "Registered Fund".

### 3. Missing Structured Schemas
The Holdings table requires strict Pydantic schemas, mirroring the `instrument.py` refactoring. This enforces correctly typed attributes per holding, providing consistency across the backend and the API boundary.

## Technical Approach

### Phase 1: Establish Pydantic Schemas for Holdings
**Goal:** Create a structured representation of a `FundHolding` that enforces data types and data normalization.
- Refine the Pydantic model for Holdings (`FundHolding` in `catalog.py` and models processing N-PORT).
- Add validators to ensure `pct_of_nav` is automatically normalized to a pure decimal fraction if passed as a percentage.

### Phase 2: Percentage Normalization
**Goal:** Normalize `pct_of_nav` and other ratio-based columns in N-PORT processing pipelines.
- Trace the extraction logic for N-PORT data (likely in `vertical_engines.wealth.dd_report.sec_injection.gather_sec_nport_data` and DB API).
- Incorporate division by 100 on N-PORT percentages to conform to the established decimal pure fraction standard used in fund instruments.

### Phase 3: Sector Assignment Fix & GICS Enrichment
**Goal:** Correctly resolve the sector or asset category of individual holdings, providing rich GICS categorization.
- Currently, 13F tools use `resolve_sector()` in `shared.py` (SIC -> OpenFIGI/yfinance -> keyword heuristics -> GICS).
- Re-use this `resolve_sector()` pipeline for N-PORT holdings to translate basic SEC `issuerCat` strings into rich, accurate actual industry sectors for corporations/equities.
- Fix the existing mapping bug where `RF` is mapped to "Real Estate Fund", updating it to its true definition: "Registered Fund" (serving as the default sector/type when GICS enrichment is not applicable).
- Keep `issuerCat` (renamed appropriately at the UI level to "Issuer Type") as a reliable fallback or distinct property when `sector` is empty.

### Phase 4: Frontend UI / Fact Sheet Verification
**Goal:** Ensure the UI appropriately consumes the normalized dataset.
- Wait for the API to output correct values and confirm the frontend correctly formats decimals.
- Monitor sector texts to verify successful classification matching.

## Acceptance Criteria
- [x] Holdings percentages properly display standard values in the UI (e.g., `7.41%` instead of `741.00%`).
- [x] Holdings inherit accurate GICS sectors (re-using `resolve_sector()`).
- [x] Registered Funds correctly resolve to "Registered Fund" instead of "Real Estate Fund" for the mapping fallback.
- [x] Holdings data correctly serializes through rigorous Pydantic schemas (added `issuer_category` as pure raw data).
