# Prompt — IAPD XML Feed Enrichment for `sec_managers`

## Contexto

A tabela `sec_managers` tem 976,980 advisers (5,657 são fund managers). O seed atual vem do FOIA CSV bulk, que popula apenas:
- `crd_number`, `firm_name`, `cik`, `sec_number`
- `private_fund_count`, `hedge_fund_count`, `pe_fund_count`, `vc_fund_count`, `real_estate_fund_count`
- `total_private_fund_assets`, `state`, `country`

**Campos com 0% de cobertura nos fund managers** (existem no schema mas nunca foram populados):
- `aum_total`, `aum_discretionary`, `aum_non_discretionary` — Item 5F do Form ADV
- `total_accounts` — Item 5F
- `fee_types` (JSONB) — Item 5E
- `client_types` (JSONB) — Item 5D
- `website` — Item 1
- `compliance_disclosures` — Item 11
- `last_adv_filed_at` — Filing/@Dt

Esses dados estão nos **IAPD XML bulk feeds** (Form ADV Part 1A structured data), disponíveis localmente:
- `C:\Users\Andrei\Desktop\EDGAR FILES\IA_FIRM_SEC_Feed_03_24_2026.xml\IA_FIRM_SEC_Feed_03_24_2026.xml` — 74 MB, 23,037 SEC-registered firms
- `C:\Users\Andrei\Desktop\EDGAR FILES\IA_FIRM_STATE_Feed_03_24_2026.xml\IA_FIRM_STATE_Feed_03_24_2026.xml` — 67 MB, 21,532 state-registered firms

## Objetivo

1. Criar parser para o XML IAPD feed
2. Criar management command / script para ingestão one-shot do XML local
3. Enriquecer o `sec_adv_ingestion` worker para suportar XML feed (além do FOIA CSV)
4. UPDATE em `sec_managers` com os campos faltantes

## XML Structure

```xml
<IAPDFirmSECReport GenOn="2026-03-24">
  <Firms>
    <Firm>
      <Info FirmCrdNb="137689" SECNb="801-73984" BusNm="ENDEAVOUR CAPITAL" LegalNm="ENDEAVOUR CAPITAL ADVISORS INC." UmbrRgstn="N"/>
      <MainAddr Strt1="410 GREENWICH AVE" City="GREENWICH" State="CT" Cntry="United States" PostlCd="06830" PhNb="203-618-0101"/>
      <Rgstn FirmType="Registered" St="APPROVED" Dt="2012-03-30"/>
      <Filing Dt="2025-03-28" FormVrsn="10/2021"/>
      <FormInfo>
        <Part1A>
          <!-- Item 1: Website -->
          <Item1 Q1F5="0" Q1I="Y" Q1M="N" Q1P="LEI_CODE_HERE">
            <WebAddrs>
              <WebAddr>HTTP://WWW.ENDCAP.COM</WebAddr>
            </WebAddrs>
          </Item1>

          <!-- Item 5A: Total employees -->
          <Item5A TtlEmp="8"/>

          <!-- Item 5D: Client types — Q5D{X}1 = count, Q5D{X}3 = AUM for that type -->
          <!-- A=individuals, B=HNW, C=banks, D=insurance, E=investment companies,
               F=pooled vehicles, G=pension, H=charities, I=state/muni, J=other advisers,
               K=corps/business, L=sovereign, M=other, N=other -->
          <Item5D Q5DF1="3" Q5DF3="518254494"/>

          <!-- Item 5E: Fee types — Y/N flags -->
          <Item5E Q5E1="Y" Q5E2="N" Q5E3="N" Q5E4="N" Q5E5="N" Q5E6="Y" Q5E7="N"/>
          <!-- Q5E1=% of AUM, Q5E2=hourly, Q5E3=subscription, Q5E4=fixed,
               Q5E5=commissions, Q5E6=performance, Q5E7=other -->

          <!-- Item 5F: AUM breakdown -->
          <Item5F Q5F1="Y" Q5F2A="518254494" Q5F2B="0" Q5F2C="518254494" Q5F2D="3" Q5F2E="0" Q5F2F="3" Q5F3="0"/>
          <!-- Q5F2A=discretionary AUM, Q5F2B=non-discretionary AUM,
               Q5F2C=total AUM, Q5F2D=discretionary accounts,
               Q5F2E=non-discretionary accounts, Q5F2F=total accounts -->

          <!-- Item 11: Disciplinary disclosures (all Y/N) -->
          <Item11 Q11="N"/>
          <Item11A Q11A1="N" Q11A2="N"/>
          <!-- ... through Item11H -->
        </Part1A>
      </FormInfo>
    </Firm>
  </Firms>
</IAPDFirmSECReport>
```

## Mapping XML → `sec_managers` columns

| XML Path | sec_managers column | Type | Notes |
|----------|-------------------|------|-------|
| `Info/@FirmCrdNb` | `crd_number` | TEXT (PK) | Match key |
| `Item5F/@Q5F2C` | `aum_total` | BIGINT | Total AUM (disc + non-disc) |
| `Item5F/@Q5F2A` | `aum_discretionary` | BIGINT | Discretionary AUM |
| `Item5F/@Q5F2B` | `aum_non_discretionary` | BIGINT | Non-discretionary AUM |
| `Item5F/@Q5F2F` | `total_accounts` | INTEGER | Total accounts |
| `Item5E/@Q5E1..Q5E7` | `fee_types` | JSONB | See fee mapping below |
| `Item5D` attrs | `client_types` | JSONB | See client mapping below |
| `Item1/WebAddrs/WebAddr[1]` | `website` | TEXT | First URL |
| `Item11` all attrs | `compliance_disclosures` | INTEGER | Count of "Y" across all 11.x |
| `Filing/@Dt` | `last_adv_filed_at` | DATE | Last ADV filing date |

### Fee types JSONB mapping

```python
fee_types = []
if Q5E1 == "Y": fee_types.append("pct_of_aum")
if Q5E2 == "Y": fee_types.append("hourly")
if Q5E3 == "Y": fee_types.append("subscription")
if Q5E4 == "Y": fee_types.append("fixed")
if Q5E5 == "Y": fee_types.append("commissions")
if Q5E6 == "Y": fee_types.append("performance")
if Q5E7 == "Y": fee_types.append("other")
# Store as JSON array: ["pct_of_aum", "performance"]
```

### Client types JSONB mapping

```python
# Item5D attributes: Q5D{X}1 = client count, Q5D{X}3 = AUM for that client type
# Only include types where count > 0
client_types = {}
mapping = {
    "A": "individuals", "B": "hnw_individuals", "C": "banks",
    "D": "insurance", "E": "investment_companies", "F": "pooled_vehicles",
    "G": "pension_plans", "H": "charities", "I": "state_municipal",
    "J": "other_advisers", "K": "corporations", "L": "sovereign",
    "M": "other_1", "N": "other_2",
}
for code, name in mapping.items():
    count_attr = f"Q5D{code}1"
    aum_attr = f"Q5D{code}3"
    count = int(item5d.get(count_attr, 0) or 0)
    if count > 0:
        client_types[name] = {
            "count": count,
            "aum": int(item5d.get(aum_attr, 0) or 0),
        }
# Store as JSONB: {"pooled_vehicles": {"count": 3, "aum": 518254494}}
```

## Implementation

### File: `backend/data_providers/sec/iapd_xml_parser.py` (NEW)

Streaming XML parser using `xml.etree.ElementTree.iterparse` — the file is 74 MB, fits in memory but streaming is cleaner.

```python
"""IAPD XML Feed parser — extracts Form ADV Part 1A structured data.

Parses IA_FIRM_SEC_Feed and IA_FIRM_STATE_Feed XML files into dicts
keyed by CRD number for bulk UPDATE into sec_managers.
"""

def parse_iapd_xml(xml_path: str) -> list[dict]:
    """Parse IAPD XML feed, return list of enrichment dicts.

    Each dict has: crd_number + all mappable fields.
    Only returns firms that have at least one non-empty field to update.
    Uses iterparse to stream — clears elements after processing to avoid
    holding the full DOM in memory.
    """
    ...
```

### File: `backend/data_providers/sec/adv_service.py` (MODIFY)

Add method:

```python
async def ingest_iapd_xml(self, xml_path: str) -> int:
    """Enrich sec_managers with Form ADV Part 1A data from IAPD XML feed.

    Parses the XML, then batch UPDATEs existing sec_managers rows.
    Only updates rows where crd_number already exists (no INSERT).
    Returns count of managers updated.
    """
```

The UPDATE query should use COALESCE to not overwrite existing non-null values with empty XML fields (some ERAs don't report Item 5):

```sql
UPDATE sec_managers SET
    aum_total = COALESCE(:aum_total, aum_total),
    aum_discretionary = COALESCE(:aum_discretionary, aum_discretionary),
    aum_non_discretionary = COALESCE(:aum_non_discretionary, aum_non_discretionary),
    total_accounts = COALESCE(:total_accounts, total_accounts),
    fee_types = CASE WHEN :fee_types::jsonb != '[]'::jsonb THEN :fee_types ELSE fee_types END,
    client_types = CASE WHEN :client_types::jsonb != '{}'::jsonb THEN :client_types ELSE client_types END,
    website = COALESCE(:website, website),
    compliance_disclosures = COALESCE(:compliance_disclosures, compliance_disclosures),
    last_adv_filed_at = COALESCE(:last_adv_filed_at, last_adv_filed_at)
WHERE crd_number = :crd_number
```

### File: `backend/app/domains/wealth/workers/sec_adv_ingestion.py` (MODIFY)

Add XML ingestion step after the CSV bulk:

```python
# After CSV bulk, check for local XML feed and enrich
import os
xml_sec_path = os.environ.get("IAPD_SEC_XML_PATH")
xml_state_path = os.environ.get("IAPD_STATE_XML_PATH")

if xml_sec_path and os.path.exists(xml_sec_path):
    enriched = await svc.ingest_iapd_xml(xml_sec_path)
    logger.info("adv_xml_enrichment.sec", enriched=enriched)

if xml_state_path and os.path.exists(xml_state_path):
    enriched = await svc.ingest_iapd_xml(xml_state_path)
    logger.info("adv_xml_enrichment.state", enriched=enriched)
```

### File: Management command for one-shot ingest (NEW)

`backend/scripts/ingest_iapd_xml.py`:

```python
"""One-shot IAPD XML enrichment.

Usage:
    cd backend
    python scripts/ingest_iapd_xml.py "C:/path/to/IA_FIRM_SEC_Feed.xml"
    python scripts/ingest_iapd_xml.py "C:/path/to/IA_FIRM_SEC_Feed.xml" "C:/path/to/IA_FIRM_STATE_Feed.xml"
"""
```

## Processing Notes

- **SEC feed** (23,037 firms): SEC-registered advisers — all have CRD, most file detailed Part 1A
- **STATE feed** (21,532 firms): State-registered advisers — may have less detail in Part 1A
- Some firms appear in both feeds — UPDATE is idempotent via COALESCE
- ERAs (Exempt Reporting Advisers) often have empty Item 5 — skip/ignore empty fields
- Total firms in both feeds: ~44,500. Our `sec_managers` has 976,980 (from FOIA CSV which includes historical). Overlap = firms that are currently active registrants.
- The XML is a **snapshot** (GenOn="2026-03-24"), not incremental. Future runs: IAPD publishes new feeds weekly at `https://reports.adviserinfo.sec.gov/datastore/`

## Validation

After ingest, run via Tiger CLI:

```sql
-- Fund managers enrichment coverage
SELECT
  COUNT(*) AS fund_managers,
  COUNT(*) FILTER (WHERE aum_total > 0) AS has_aum,
  COUNT(*) FILTER (WHERE total_accounts > 0) AS has_accounts,
  COUNT(*) FILTER (WHERE fee_types != '[]'::jsonb) AS has_fees,
  COUNT(*) FILTER (WHERE client_types != '{}'::jsonb) AS has_clients,
  COUNT(*) FILTER (WHERE website IS NOT NULL AND website != '') AS has_website,
  COUNT(*) FILTER (WHERE last_adv_filed_at IS NOT NULL) AS has_filing_date
FROM sec_managers
WHERE private_fund_count > 0 OR hedge_fund_count > 0
   OR pe_fund_count > 0 OR vc_fund_count > 0
   OR real_estate_fund_count > 0;
```

Expected: ~3,000-4,000 of the 5,657 fund managers should get enriched (the SEC-registered ones). State-only advisers may not be fund managers.

## Rules

- No migration needed — all columns already exist in `sec_managers`
- Use `iterparse` for XML — memory-efficient streaming
- Batch UPDATEs in chunks of 500 (use `executemany` or loop)
- COALESCE — never overwrite existing data with NULL/empty
- fee_types as JSON array of strings: `["pct_of_aum", "performance"]`
- client_types as JSON dict with count+aum: `{"pooled_vehicles": {"count": 3, "aum": 518254494}}`
- compliance_disclosures = count of "Y" answers across all Item 11 sub-questions
- website = first `<WebAddr>` text, strip leading `HTTP://` normalize
- Parse both SEC and STATE feeds — some fund managers are state-registered
- Tests: unit test for XML parser with sample XML (use the examples from this prompt)
- Run `make check` after (exclude `test_instrument_ingestion.py` — pre-existing failure)
