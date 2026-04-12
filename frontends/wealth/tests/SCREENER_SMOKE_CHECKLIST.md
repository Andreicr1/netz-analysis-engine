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
