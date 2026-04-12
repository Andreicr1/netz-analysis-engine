# FI Classification Audit — Investigation Brief

**Date:** 2026-04-12
**Mission:** Pure investigation. NO code changes. Find WHY some funds are misclassified as `fixed_income` when they are clearly equity or real estate.
**Context:** FI Quant Session 2 shipped scoring dispatch by `asset_class`. The dispatch WORKS correctly, but the INPUT classification is wrong for some funds — Real Estate funds scored as FI, equity-named funds scored as FI.

## What to investigate

### 1. Where does `asset_class` come from?

The `risk_calc.py` worker determines which funds get `scoring_model = "fixed_income"` vs `"equity"`. Find the EXACT logic:

- Read `backend/app/domains/wealth/workers/risk_calc.py` fully
- Search for where `asset_class` is read or derived per fund
- Is it from `instruments_universe.asset_class`?
- Is it from `strategy_label`?
- Is it from a mapping function?
- Is it hardcoded based on `fund_type` or `universe`?
- Is it derived from the fund name?

Report the EXACT file, function, and line number where the classification decision is made.

### 2. What does the classification data look like?

Run these queries against the local dev DB:

```sql
-- Q1: What distinct asset_class values exist and how are they distributed?
SELECT asset_class, COUNT(*) AS cnt
FROM instruments_universe
GROUP BY asset_class
ORDER BY cnt DESC;

-- Q2: What strategy_labels are classified as fixed_income?
SELECT i.asset_class, i.strategy_label, COUNT(*) AS cnt
FROM instruments_universe i
WHERE i.asset_class = 'fixed_income'
GROUP BY i.asset_class, i.strategy_label
ORDER BY cnt DESC;

-- Q3: Sample of Real Estate funds classified as fixed_income
SELECT i.external_id, i.name, i.asset_class, i.strategy_label, i.fund_type
FROM instruments_universe i
WHERE i.asset_class = 'fixed_income'
  AND (i.name ILIKE '%real estate%' OR i.name ILIKE '%reit%' OR i.strategy_label ILIKE '%real estate%')
LIMIT 20;

-- Q4: Sample of clearly-equity funds classified as fixed_income
SELECT i.external_id, i.name, i.asset_class, i.strategy_label, i.fund_type
FROM instruments_universe i
WHERE i.asset_class = 'fixed_income'
  AND (i.name ILIKE '%equity%' OR i.name ILIKE '%stock%' OR i.name ILIKE '%growth%' OR i.name ILIKE '%value%')
LIMIT 20;

-- Q5: How was asset_class populated? Is there a migration or worker that sets it?
-- Search for INSERT or UPDATE on instruments_universe.asset_class
```

Also grep the codebase:

```bash
grep -rn "asset_class" backend/app/domains/wealth/workers/risk_calc.py | head -20
grep -rn "asset_class" backend/app/domains/wealth/models/ | head -20
grep -rn "\"fixed_income\"\|'fixed_income'" backend/app/domains/wealth/ | head -30
grep -rn "asset_class.*=\|set.*asset_class" backend/ --include="*.py" | grep -v __pycache__ | head -30
```

### 3. What is the classification logic in the worker?

The risk_calc worker's Pass 1.7 (FI analytics) decides which funds are FI. Find:

- The conditional: `if asset_class == "fixed_income"` or equivalent
- Where `asset_class` is READ (from DB? from instrument model? from a config?)
- Whether there's a MAPPING from strategy_label → asset_class
- Whether the mapping is correct or has bugs (e.g., maps "Real Estate" → "fixed_income")

### 4. What SHOULD the correct classification be?

For reference, the expected mapping:

| Strategy/Type | Correct asset_class |
|---|---|
| US Aggregate Bond, IG Corporate, HY, Government, Municipal, Mortgage | `fixed_income` |
| Real Estate, REIT | `alternatives` (NOT fixed_income) |
| Equity, Growth, Value, Large Cap, Small Cap, International Equity | `equity` |
| Commodities, Infrastructure, Private Credit | `alternatives` |
| Money Market | `cash` |
| Multi-Asset, Balanced | `equity` or needs separate model |

## Report Format

```markdown
# FI Classification Audit — Findings

## 1. Classification source
- **File:** <exact path>
- **Function:** <exact function name>
- **Line:** <line number>
- **Logic:** <describe the classification decision>
- **Data source:** <where asset_class comes from — DB column, mapping, derivation>

## 2. Classification data (Q1-Q5 output)
<paste full query outputs>

## 3. Misclassification examples
- Real Estate as FI: <count and examples>
- Equity-named as FI: <count and examples>
- Other misclassifications: <any>

## 4. Root cause
<one paragraph explaining WHY the misclassification happens>

## 5. Recommended fix
<factual description of what needs to change — which mapping, which condition, which data>
```

## Constraints

- Zero file modifications
- Zero commits
- Budget: 15-20 minutes
