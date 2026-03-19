# Style premium refactor summary

## Original weaknesses
- The original language was a safe enterprise blue-gray system that leaned heavily on near-default Tailwind spacing, shadow, and slate values.
- Surface tokens were too flat and too close together, so page background, cards, insets, and overlays lacked convincing separation.
- Border hierarchy was effectively one-dimensional, which made panels, form fields, tables, and navigation all compete at the same visual level.
- Typography covered only basic headings and body copy, so dense product UI patterns had weak support for labels, captions, and restrained executive-style hierarchy.
- Motion was generic and mechanical, and the base layer did not provide polished defaults for focus, links, selection, or unstyled controls.

## Key design decisions
- Shift the default palette toward deeper navy, quieter steel-blue accents, and a softened copper highlight to keep the system institutional rather than flashy.
- Introduce layered surface, border, focus, and accent tokens while preserving the legacy token names already used throughout the app.
- Strengthen hierarchy with editorial heading tuning, semantic typography tokens, and spacing rhythm aliases that improve composition without forcing component rewrites.
- Replace the generic shadow ladder with restrained card and floating elevations that use border definition and ambient depth together.
- Upgrade motion and base primitives so dialogs, menus, fields, links, focus states, and global page chrome feel calmer and more deliberate.

## Files changed
- `packages/ui/src/lib/styles/tokens.css`
- `packages/ui/src/lib/styles/typography.css`
- `packages/ui/src/lib/styles/spacing.css`
- `packages/ui/src/lib/styles/shadows.css`
- `packages/ui/src/lib/styles/animations.css`
- `packages/ui/src/lib/styles/index.css`

## Recommended next steps for component-level refinement
- Align card, modal, sheet, and dropdown component internals to the new surface tiers so headers, bodies, and footers each read at the right level.
- Normalize button, badge, tab, and table treatments around the new border hierarchy and accent-soft tokens instead of ad hoc background mixes.
- Tighten page-level spacing in navigation bars, filter rows, metric cards, and detail panels to consistently use the new semantic rhythm tokens.
- Audit status colors inside charts and badges so success, warning, and danger usage stays restrained and role-driven.
- Revisit dark theme component states individually, especially hover and active layers, to ensure elevated surfaces stay distinct in dense screens.
