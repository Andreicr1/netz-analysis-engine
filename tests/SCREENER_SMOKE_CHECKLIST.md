# Screener Smoke Test Checklist

Last updated: 2026-04-12 (Sprint 4 — Data Trust + Score Integration)

## Grid Display

1. [ ] Grid loads with data rows (not blank)
2. [ ] Infinite scroll loads beyond first page (200 items)
3. [ ] Infinite scroll stops at end of catalog with "END OF CATALOG" message
4. [ ] Row count in footer matches total
5. [ ] Zebra striping alternates on every other row
6. [ ] Row click selects row (highlight + FocusMode trigger)
7. [ ] Keyboard up/down navigates highlighted row
8. [ ] Highlighted row scrolls into view when at edge

## Column Data Accuracy

9. [ ] Ticker column shows ticker or ISIN, not em-dash for funds with tickers
10. [ ] Name column shows fund name
11. [ ] Type badges (MF, ETF, CEF, BDC, HF, PRIV, UCITS, MMF) render correctly
12. [ ] ELITE badge shows amber "ELITE" inline for elite-flagged funds
13. [ ] Strategy column shows strategy_label
14. [ ] Geography column shows 2-letter code
15. [ ] AUM column shows formatted values (e.g., "1.2B", "500M")
16. [ ] 1Y Ret column shows percentage with correct sign (green pos, red neg)
17. [ ] 1Y Ret values are in correct magnitude (e.g., 35.9% not 0.36%)
18. [ ] 10Y Ret column shows em-dash (data not yet populated from XBRL)
19. [ ] ER% column shows percentage (e.g., "0.82%" not "0.00" or "0.01")
20. [ ] ER% NULL values show em-dash, not "0.00%"
21. [ ] SCORE column shows composite score numeral (e.g., "52.6")
22. [ ] SCORE color: green >= 70, amber 40-69, red < 40
23. [ ] SCORE NULL shows em-dash
24. [ ] No sparkline canvas elements in the grid

## Data Accuracy (5-Fund Verification)

25. [ ] LBHYX: ER% = 0.82%, 1Y Ret = 35.95%, Score = 75.2
26. [ ] KGIRX: ER% = 1.30%, 1Y Ret = 56.22%, Score = 75.1, ELITE badge
27. [ ] KGGAX: ER% = 1.27%, 1Y Ret = 63.07%, Score = 74.6, ELITE badge
28. [ ] TIBMX: ER% = 1.29%, 1Y Ret = 35.80%, Score = 74.2, ELITE badge
29. [ ] PQARX: ER% = 1.08%, 1Y Ret = 12.68%, Score = 74.1, ELITE badge

## Filters

30. [ ] All filter sections collapsed by default on page load
31. [ ] ELITE chip visible and toggleable (outside accordion)
32. [ ] Click section header expands section with chevron rotation
33. [ ] Active filter count badge appears on collapsed section with active filters
34. [ ] "ALL" button expands all sections
35. [ ] "NONE" button collapses all sections
36. [ ] Filters persist when section is collapsed
37. [ ] Manager typeahead with chip selection
38. [ ] Metric range inputs (Sharpe, Drawdown, Volatility, ER, Returns)
39. [ ] Clear button resets all filters

## FocusMode

40. [ ] Row click opens FocusMode overlay
41. [ ] ScoreCompositionPanel renders as first module in vitrine
42. [ ] Score composition shows horizontal bars with color coding
43. [ ] Component weighted values sum to approximately the composite score
44. [ ] ESC closes FocusMode
45. [ ] All 7 original analytics modules still render after score panel

## Infrastructure

46. [ ] `svelte-check` 0 errors
47. [ ] `pnpm build` clean
48. [ ] `make test` green (screener tests pass)
49. [ ] Sparkline endpoint POST /screener/sparklines still functional (not deleted)
