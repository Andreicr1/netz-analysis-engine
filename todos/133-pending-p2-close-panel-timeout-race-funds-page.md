---
status: pending
priority: p2
issue_id: 133
tags: [code-review, performance, frontend]
---

# Problem Statement

`closePanel()` in the funds page uses `setTimeout(220ms)` to null out `selectedFund` after the close animation completes. If a user clicks to open a different fund before the 220ms timer fires, the timeout callback runs and clears the newly selected fund, collapsing the panel mid-open. This is a classic stale closure / timer race condition.

# Findings

- `frontends/wealth/src/routes/(team)/funds/+page.svelte` lines 86-91 define `closePanel()` with a `setTimeout` that sets `selectedFund = null`.
- The timeout ID is not stored anywhere.
- When `openPanel(fund)` is called before the previous timeout fires, `selectedFund` is correctly set to the new fund.
- 220ms later, the timeout from `closePanel()` fires and sets `selectedFund = null`, erasing the newly opened panel.
- Reproduced by: click fund A → immediately click fund B before animation ends → panel for B closes unexpectedly.
- The 220ms value matches a typical CSS transition duration, so the race window is exactly the animation duration.

# Proposed Solutions

Store the timeout reference and cancel it when opening a new panel:

```typescript
let closePanelTimeout: ReturnType<typeof setTimeout> | null = null;

function openPanel(fund: Fund) {
    if (closePanelTimeout !== null) {
        clearTimeout(closePanelTimeout);
        closePanelTimeout = null;
    }
    selectedFund = fund;
}

function closePanel() {
    closePanelTimeout = setTimeout(() => {
        selectedFund = null;
        closePanelTimeout = null;
    }, 220);
}
```

This ensures the null-clear only fires if no new fund was selected during the animation window.

# Technical Details

- **File:** `frontends/wealth/src/routes/(team)/funds/+page.svelte` lines 86-91
- **Race window:** 220ms (CSS transition duration)
- **Fix complexity:** 4 lines added, 1 line changed
- **Source:** performance-oracle
