/**
 * Workbench tool state — Phase 9 Block B.
 *
 * Declares the union of tools available inside the /portfolio/live
 * Workbench and the metadata the tool ribbon uses to render them.
 *
 * Source-of-truth discipline (DL15 — Zero localStorage):
 *   The parent +page.svelte reads the active tool from
 *   ``page.url.searchParams.get("tool")`` and writes it back via
 *   ``goto({replaceState, noScroll, keepFocus})``. This module
 *   exports pure constants + a type guard — there is NO in-module
 *   $state, no store, no effect. The shell and ribbon are both
 *   pure presentation and consume ``activeTool`` + ``onToolChange``
 *   as props, identical to the Phase 8 ``selectedId`` + ``onSelect``
 *   pattern for the portfolio selector.
 *
 * Scope (re-scoped Phase 9 Block B mandate):
 *   - overview        — Phase 8 dashboard (KPI strip + allocations)
 *   - drift_analysis  — Target vs Actual comparison (placeholder)
 *   - execution_desk  — Trading boleta surface (placeholder)
 *
 * Adding a new tool later is a 2-line change (append to
 * ``WORKBENCH_TOOLS`` + add a label + add the {#if} branch in the
 * shell). The type guard automatically covers URL validation.
 */

export const WORKBENCH_TOOLS = [
	"overview",
	"drift_analysis",
	"execution_desk",
] as const;

export type WorkbenchTool = (typeof WORKBENCH_TOOLS)[number];

export const DEFAULT_WORKBENCH_TOOL: WorkbenchTool = "overview";

export interface WorkbenchToolMeta {
	id: WorkbenchTool;
	label: string;
	/** Short description surfaced via title / aria-description. */
	description: string;
}

export const WORKBENCH_TOOL_META: Record<WorkbenchTool, WorkbenchToolMeta> = {
	overview: {
		id: "overview",
		label: "Overview",
		description: "KPIs and current allocations for the selected portfolio.",
	},
	drift_analysis: {
		id: "drift_analysis",
		label: "Drift Analysis",
		description: "Target vs actual weight drift, per-block tolerance.",
	},
	execution_desk: {
		id: "execution_desk",
		label: "Execution Desk",
		description: "Order pad and trading boleta for rebalance actions.",
	},
};

/**
 * URL validation guard. The query string is user-editable, so the
 * ribbon component must treat ``?tool=<value>`` as untrusted input.
 * Returns ``true`` only for values in the canonical union.
 */
export function isWorkbenchTool(
	value: string | null | undefined,
): value is WorkbenchTool {
	if (value === null || value === undefined) return false;
	return (WORKBENCH_TOOLS as readonly string[]).includes(value);
}

/**
 * Resolve an arbitrary URL query value to a valid tool, falling back
 * to the default when the value is missing or invalid. Keeps the
 * call site in +page.svelte one-liner-clean.
 */
export function resolveWorkbenchTool(
	value: string | null | undefined,
): WorkbenchTool {
	return isWorkbenchTool(value) ? value : DEFAULT_WORKBENCH_TOOL;
}
