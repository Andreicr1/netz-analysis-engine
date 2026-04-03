# Design Tokens — One X AI-Powered Investment Dashboard (Figma)

**Source:** [Figma Community — One X Template](https://www.figma.com/design/za2qtz3TzkuO7CNN6iSP4e)
**Node:** `2:107` (Stovest Investment Dashboard)
**Extracted:** 2026-04-03

> Nota: Este arquivo Figma **nao possui variables, paint styles, text styles, ou effect styles** formalizados. Todos os tokens abaixo foram extraidos diretamente dos nos do design (inline values).

---

## 1. Color Palette

### 1.1 Core Colors

| Token | Hex | Opacity | Usage | Count |
|-------|-----|---------|-------|-------|
| `background-primary` | `#000000` | 1.0 | Main frame background, card overlays | 6 |
| `background-card` | `#000000` | 1.0 | Cards (via Rectangle fills) | — |
| `background-card-glass` | `#0d0d0d` | 0.6 | Glass card overlay (Total Holding) | 1 |
| `background-card-inner` | `#141519` | 1.0 | Portfolio stock cards (AAPL, TSLA, etc.) | 5 |
| `background-nav-item` | `#1a1b20` | 1.0 | Top nav items, search bar, icon containers | 7 |

### 1.2 Brand / Accent

| Token | Hex | RGB | Usage | Count |
|-------|-----|-----|-------|-------|
| `accent-primary` | `#0177fb` | rgb(1, 119, 251) | Active tab bg, chart elements, time pills | 7 (fill) + 7 (stroke) |
| `accent-positive` | `#11ec79` | rgb(17, 236, 121) | Positive change %, trend up icons | 9 (fill) + 9 (stroke) |
| `accent-negative` | `#fc1a1a` | rgb(252, 26, 26) | Negative change %, trend down indicators | 4 (fill) + 1 (stroke) |

### 1.3 Text Colors

| Token | Hex | Opacity | Usage | Count |
|-------|-----|---------|-------|-------|
| `text-primary` | `#ffffff` | 1.0 | Primary text (labels, values, headings) | 84 |
| `text-secondary` | `#d9d9d9` | 1.0 | Subtitles, category labels (Main Menu, Support) | 5 |
| `text-tertiary` | `#c2c2c2` | 1.0 | Exchange labels (NYSE. SPOT, NYSE. AMZN) | 2 |
| `text-muted` | `#cbccd1` | 1.0 | Placeholder text (search bar) | 1 |

### 1.4 Border / Separator Colors

| Token | Hex | Usage | Count |
|-------|-----|-------|-------|
| `border-subtle` | `#404249` | Sidebar divider, main content border | 2 |
| `border-grid` | `#43454b` | Chart grid lines | 9 |
| `icon-inactive` | `#484a52` | Inactive icon fills | 10 |

### 1.5 Overlay / Glass Effects

| Token | Hex | Opacity | Usage |
|-------|-----|---------|-------|
| `overlay-tooltip-bg` | `#ffffff` | 0.10 | Chart tooltip background |
| `overlay-badge-bg` | `#ffffff` | 0.13 | Percentage badge background |
| `overlay-indicator` | `#ffffff` | 0.15 | Chart indicator element |

### 1.6 Gradients

| Token | Type | Stops | Usage |
|-------|------|-------|-------|
| `gradient-chart-area` | `GRADIENT_LINEAR` | `#0177fb` @ 7% (opacity 0) → `#0177fb` @ 100% (opacity 0.5) | Chart area fill under curve |

---

## 2. Typography

### 2.1 Font Family

| Property | Value |
|----------|-------|
| **Primary font** | **Urbanist** |
| **Weights used** | Light (300), Regular (400), Medium (500), SemiBold (600), Bold (700) |

### 2.2 Type Scale

| Token | Size | Weight | Style | Usage | Count |
|-------|------|--------|-------|-------|-------|
| `display-xl` | 44px | 700 (Bold) | — | Hero value (`$ 12,304.11`) | 1 |
| `display-lg` | 32px | Mixed | — | Welcome heading (`Welcome, Naya`) | 1 |
| `heading-brand` | 24.8px | 500 (Medium) | — | Logo text (`Stovest`) | 1 |
| `heading-search` | 20.7px | 400 (Regular) | — | Search placeholder | 1 |
| `heading-nav` | 20px | 400 (Regular) | — | Top nav items (Market, Wallets, Tools) | 3 |
| `heading-section` | 20px | 500 (Medium) | — | Section titles (Total Holding, My Portfolio, etc.) | 5 |
| `body-sidebar-active` | 18px | 600 (SemiBold) | — | Active sidebar item (Dashboard) | 1 |
| `body-sidebar` | 18px | 400 (Regular) | — | Sidebar menu items (Portfolio, Analysis, etc.) | 6 |
| `body-stock-value` | 18px | 700 (Bold) | — | Stock price cards (`$ 1,721.3`) | 5 |
| `body-table-header` | 17px | 600 (SemiBold) | — | Table column headers (Stock, Last Price, etc.) | 6 |
| `body-default` | 16px | 400 (Regular) | — | Most UI text (tabs, values, subtitles) | 28 |
| `body-default-tight` | 16px | 400 (Regular) | letter-spacing: -5% | Return label, change values | 2 |
| `body-highlight` | 16px | 600 (SemiBold) | — | Highlighted values (`$ 1,234.30`) | 1 |
| `body-tooltip` | 15px | 700 (Bold) | — | Tooltip values (`$ 16,500`) | 1 |
| `caption-light` | 14px | 300 (Light) | — | Email, chart axis labels (dates) | 15 |
| `caption` | 14px | 400 (Regular) | — | Chart Y-axis labels (200k, 150k, etc.) | 9 |
| `caption-date` | 13px | 300 (Light) | — | Tooltip date (`1st Mar 2024`) | 1 |
| `label` | 12px | 400 (Regular) | — | Category labels, ticker symbols, unit counts | 18 |
| `label-micro` | 10px | 400 (Regular) | letter-spacing: -5% | Badge percentages (`+3.5%`) | 1 |

---

## 3. Spacing System

### 3.1 Gaps (itemSpacing in auto-layout)

| Token | Value | Usage | Count |
|-------|-------|-------|-------|
| `gap-xs` | 2px | Stacked text blocks (name + email) | 2 |
| `gap-sm` | 4px | Inline value + change rows | 10 |
| `gap-md` | 8px | Small inline groups | 1 |
| `gap-base` | 10px | Most common — icon+text pairs, tab groups | 22 |
| `gap-icon` | 11px | Watchlist icon + text | 2 |
| `gap-lg` | 16px | Sidebar menu items spacing | 6 |
| `gap-xl` | 24px | Support section items | 1 |
| `gap-2xl` | 30px | Chart Y-axis labels | 1 |
| `gap-3xl` | 44px | Chart X-axis labels | 1 |
| `gap-4xl` | 48px | Top bar sections, icon groups, user profile | 3 |

### 3.2 Padding Patterns

| Token | Values (T/R/B/L) | Usage | Count |
|-------|-------------------|-------|-------|
| `padding-pill` | 18 / 26 / 18 / 26 | Tab pills, filter pills | 10 |
| `padding-pill-compact` | 18 / 21 / 18 / 21 | Watchlist tab pills | 3 |
| `padding-icon-container` | 20 / 20 / 20 / 20 | Notification, settings icon buttons | 3 |
| `padding-icon-sm` | 17 / 17 / 17 / 17 | Dropdown arrow container | 1 |
| `padding-icon-xs` | 13 / 13 / 13 / 13 | Small icon container | 1 |

---

## 4. Border Radius

| Token | Value | Usage | Count |
|-------|-------|-------|-------|
| `radius-xs` | 2px | Micro elements (sparkline strokes) | 2 |
| `radius-sm` | 4px | Time period selector, percentage badges | 2 |
| `radius-md` | 9px | Chart indicator element | 1 |
| `radius-lg` | 24px | Cards, stock cards, chart containers | 9 |
| `radius-pill` | 32px | Pills, tabs, filter buttons | 13 |
| `radius-nav` | 36px | Top nav bar items, search bar | 4 |
| `radius-circle` | 50px | Avatar, icon buttons (notification, settings) | 5 |

### Asymmetric Radius

| Token | Values (TL/TR/BR/BL) | Usage | Count |
|-------|----------------------|-------|-------|
| `radius-card-top` | 24 / 24 / 0 / 0 | Bottom cards (Portfolio Overview, Watchlist) | 2 |
| `radius-content-area` | 32 / 0 / 0 / 0 | Main content area background | 1 |

---

## 5. Effects / Blur

### 5.1 Background Blur (Glass / Frosted)

| Token | Radius | Usage |
|-------|--------|-------|
| `blur-glass-heavy` | 22.2px | Total Holding card overlay |
| `blur-glass-light` | 4.7px | Chart indicator element |
| `blur-glass-subtle` | 3px | Chart tooltip |

### 5.2 Layer Blur (Glow)

| Token | Radius | Usage |
|-------|--------|-------|
| `blur-glow-accent` | 6.1px | Blue accent dots (chart) |
| `blur-glow-negative` | 7.4px | Red indicator dots |

---

## 6. Stroke Weights

| Token | Value | Count |
|-------|-------|-------|
| `stroke-default` | 1px | 209 (icons, dividers, borders) |
| `stroke-thin` | 0.5px | 11 (fine details) |
| `stroke-chart` | 3px | 1 (chart main line) |

---

## 7. Layout Dimensions

### 7.1 Canvas

| Property | Value |
|----------|-------|
| **Viewport** | 1728 x 1117 px |
| **Sidebar width** | ~308px (left edge to content) |
| **Content area** | 1394 x 1004 px |
| **Content padding** | 24px (inner content frame) |

### 7.2 Component Sizes

| Component | Width | Height |
|-----------|-------|--------|
| Total Holding card | 444 x 261 px |
| Portfolio row | 870 x 261 px |
| Chart area | 1335 x 363 px |
| Table card | 929 x 308 px |
| Watchlist card | 382 x 308 px |
| Stock mini-card | ~146-147 x 149 px |
| Icon button (lg) | 61 x 61 px |
| Icon button (md) | 55 x 55 px |
| Tab pill | ~67-133 x 55 px |

---

## 8. Icon System

| Library | Style | Size | Examples |
|---------|-------|------|----------|
| **Vuesax Linear** | Outline (1px stroke) | 20-24px | chart, bag-2, chart-2, presention-chart, people, lovely, notification, setting-2, microphone-2, trend-up, arrow-down, arrow-2, more |
| **Brand icons** | Solid fill | 16-31px | Apple (fa6-brands), Tesla (cib), Microsoft (bi), Google (eva/bi), Nvidia (bi), Spotify (teenyicons), Amazon (custom) |

---

## 9. CSS Custom Properties (Suggested Mapping)

```css
:root {
  /* Colors */
  --color-bg-primary: #000000;
  --color-bg-card: #000000;
  --color-bg-card-glass: rgba(13, 13, 13, 0.6);
  --color-bg-card-inner: #141519;
  --color-bg-nav: #1a1b20;
  --color-accent: #0177fb;
  --color-positive: #11ec79;
  --color-negative: #fc1a1a;
  --color-text-primary: #ffffff;
  --color-text-secondary: #d9d9d9;
  --color-text-tertiary: #c2c2c2;
  --color-text-muted: #cbccd1;
  --color-border-subtle: #404249;
  --color-border-grid: #43454b;
  --color-icon-inactive: #484a52;
  --color-overlay-10: rgba(255, 255, 255, 0.10);
  --color-overlay-13: rgba(255, 255, 255, 0.13);
  --color-overlay-15: rgba(255, 255, 255, 0.15);

  /* Typography */
  --font-family: 'Urbanist', sans-serif;
  --font-weight-light: 300;
  --font-weight-regular: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
  --font-weight-bold: 700;
  --font-size-micro: 10px;
  --font-size-label: 12px;
  --font-size-caption: 14px;
  --font-size-body: 16px;
  --font-size-table-header: 17px;
  --font-size-sidebar: 18px;
  --font-size-heading-section: 20px;
  --font-size-heading-brand: 25px;
  --font-size-display-lg: 32px;
  --font-size-display-xl: 44px;

  /* Spacing */
  --gap-xs: 2px;
  --gap-sm: 4px;
  --gap-md: 8px;
  --gap-base: 10px;
  --gap-lg: 16px;
  --gap-xl: 24px;
  --gap-2xl: 30px;
  --gap-3xl: 44px;
  --gap-4xl: 48px;

  /* Border Radius */
  --radius-xs: 2px;
  --radius-sm: 4px;
  --radius-md: 9px;
  --radius-lg: 24px;
  --radius-pill: 32px;
  --radius-nav: 36px;
  --radius-circle: 50px;

  /* Effects */
  --blur-glass-heavy: 22.2px;
  --blur-glass-light: 4.7px;
  --blur-glass-subtle: 3px;
  --blur-glow-accent: 6.1px;
  --blur-glow-negative: 7.4px;

  /* Stroke */
  --stroke-default: 1px;
  --stroke-thin: 0.5px;
  --stroke-chart: 3px;
}
```

---

## 10. Design Characteristics Summary

| Aspect | Description |
|--------|-------------|
| **Theme** | Dark mode only (pure black `#000000` background) |
| **Style** | Glassmorphism + flat cards with subtle borders |
| **Primary accent** | Blue (`#0177fb`) — consistent across interactions |
| **Data viz** | Green/red polarity for gains/losses; gradient area fills |
| **Cards** | Rounded corners (24px), dark inner backgrounds, no drop shadows |
| **Navigation** | Sidebar (left) + Top nav bar (horizontal) |
| **Typography** | Urbanist — geometric sans-serif, 5 weights, 12+ size steps |
| **Icons** | Vuesax Linear (outline style, 1px stroke) |
| **Interaction hints** | Pills for filters/tabs, hover states implied by accent color |
