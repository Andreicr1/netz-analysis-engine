# Screener Smoke Test Checklist

Open http://localhost:5174/terminal-screener after `pnpm dev`.

1. Grid renders with 9k+ row indicators (scrollbar size, row count in footer)
2. Scroll down rapidly -- no jank, sparklines load on visible rows
3. Toggle ELITE chip -- grid filters to <=300 rows, amber badges visible
4. Clear ELITE -- grid returns to full catalog
5. Click a row -- FocusMode opens with fund analytics vitrine
6. ESC closes FocusMode, focus returns to grid
7. Press Up/Down -- highlight moves between rows
8. Press Enter -- FocusMode opens on highlighted row
9. Highlight a liquid fund, press `u` -- toast "approved to universe", badge changes
10. Highlight a private fund, press `d` -- toast "DD queued", badge changes
11. Press `/` -- filter input focuses
12. Press `e` -- ELITE chip toggles
13. Apply filters then reload page -- same filters applied from URL
14. Navigate to page 2 via scroll -- cursor appears in URL
15. All text is monospace where expected, all borders are 1px hairline, zero radius
16. DOM inspector shows ~50 row elements (not 9000+)
17. Action column: liquid funds show amber "-> UNIVERSE", privates show cyan "+ DD"
18. Already-approved funds show green "IN UNIVERSE" label
19. Sparklines: green for positive trend, red for negative, em-dash for no data
20. Canvas sparklines at 48x16px, no ECharts import in bundle
21. Grid fills viewport width (2-column layout, no third column, no excessive padding)
22. Error state renders as terminal-native [ ERR ] panel with RETRY + RELOAD, not raw stack trace
23. Compact density: ~8px padding between shell chrome and screener content
24. Infinite scroll: scroll to row ~195 -- next page loads automatically, footer updates "Showing 400 of 9,193"
25. Infinite scroll continues: subsequent pages append without replacing existing data
26. END OF CATALOG indicator appears after last page loads (or ELITE-filtered small set)
27. Filter change resets infinite scroll: change any filter -- data clears and reloads from page 1
28. Manager typeahead: type 2+ chars in MANAGER input -- suggestions dropdown appears
29. Manager chips: select suggestion -- chip appears, grid filters, URL updates with ?manager=
30. Manager multi-select: add multiple managers -- chips stack, grid shows union
31. Manager chip remove: click x on chip -- removed, grid updates
32. Metric range: Sharpe min/max -- dual input fields with 500ms debounce
33. Metric range: Max Drawdown -- positive user input converts to negative backend value
34. Metric range: Volatility max, Expense Ratio max, 1Y/10Y Return min/max all present
35. Metric URL sync: ?sharpe_min=0.5&dd_max=15 persists on reload
36. Combined filter: ELITE + Manager + Sharpe produces narrow intersection
