/**
 * Portfolio Analytics types — Phase 6 Block A of the
 * portfolio-enterprise-workbench plan.
 *
 * The /portfolio/analytics surface is a multi-subject analytical
 * workbench that lets a PM browse model portfolios or the approved
 * universe in a 3×2 chart grid. Block A ships the framework (scope
 * switcher + grid + tab dock); Block B fills the grid cells with
 * real chart components.
 *
 * All state on /portfolio/analytics is URL-driven — no workspace
 * mutations, no localStorage (DL15). Deep links and browser
 * back/forward navigation work out of the box.
 */

/**
 * Analytics scope — the entity universe currently loaded into the
 * subject list on the left. OD-25 locks ``compare_both`` to v1.1
 * (rendered with a disabled badge in Phase 6 Block A).
 */
export type AnalyticsScope =
	| "model_portfolios"
	| "approved_universe"
	| "compare_both";

export const ANALYTICS_SCOPES: readonly AnalyticsScope[] = [
	"model_portfolios",
	"approved_universe",
	"compare_both",
] as const;

/**
 * Plain-English labels for each scope. Used by ScopeSwitcher and
 * BottomTabDock tab subtitles. Phase 10 Task 10.1 will pull these
 * into the canonical jargon translation table.
 */
export const ANALYTICS_SCOPE_LABEL: Record<AnalyticsScope, string> = {
	model_portfolios: "Model Portfolios",
	approved_universe: "Approved Universe",
	compare_both: "Compare Both",
};

/**
 * Analytics group focus — which chart group is currently rendered in
 * the AnalysisGrid. The plan §5.4 enumerates four canonical groups.
 */
export type AnalyticsGroupFocus =
	| "returns_risk"
	| "holdings"
	| "peer"
	| "stress";

export const ANALYTICS_GROUPS: readonly AnalyticsGroupFocus[] = [
	"returns_risk",
	"holdings",
	"peer",
	"stress",
] as const;

export const ANALYTICS_GROUP_LABEL: Record<AnalyticsGroupFocus, string> = {
	returns_risk: "Returns & Risk",
	holdings: "Holdings",
	peer: "Peer",
	stress: "Stress",
};

/**
 * A subject is one row in the FilterRail's left list — either a model
 * portfolio or an approved-universe instrument. The shape is the same
 * for both scopes so the FilterRail subject list does not need to know
 * which scope it is rendering.
 */
export interface AnalyticsSubject {
	/** Stable identifier — model_portfolio.id or instrument_id. */
	id: string;
	/** Display name shown in the FilterRail and BottomTabDock label. */
	name: string;
	/** Optional secondary line — profile/mandate or strategy_label. */
	subtitle?: string;
	/** Optional badge — e.g. state chip for model portfolios. */
	badge?: string;
	/** Which scope this subject came from (used for the BottomTabDock tab). */
	scope: AnalyticsScope;
}

/**
 * One BottomTabDock tab — represents an open analytical session on a
 * single subject. The fingerprint is ``${scope}:${subjectId}`` so
 * dedupe is automatic when the same subject is opened twice from the
 * subject list.
 *
 * URL-hash serialization (DL15 — no localStorage) uses base64-encoded
 * JSON of an array of these tabs plus the active id.
 */
export interface AnalyticsTab {
	/** Stable identifier — equal to the fingerprint for now. */
	id: string;
	/** Subject id (model_portfolio.id or instrument_id). */
	subjectId: string;
	/** Subject scope at the time the tab was opened. */
	scope: AnalyticsScope;
	/** Display name shown in the BottomTabDock. */
	label: string;
	/** Optional secondary line in the BottomTabDock. */
	subtitle?: string;
	/** Currently-active group inside the tab. */
	groupFocus: AnalyticsGroupFocus;
}

/**
 * Hash payload shape — what we serialize into the URL hash for
 * BottomTabDock persistence. Kept versioned so a future schema change
 * can be detected and ignored without breaking deep links.
 */
export interface AnalyticsHashState {
	v: 1;
	tabs: AnalyticsTab[];
	activeId: string | null;
}

/**
 * Compute the canonical fingerprint for an analytics subject. Used by
 * the BottomTabDock to dedupe re-opens of the same subject from the
 * subject list — opening fund X from approved_universe twice is one
 * tab, not two.
 */
export function tabFingerprint(scope: AnalyticsScope, subjectId: string): string {
	return `${scope}:${subjectId}`;
}

/**
 * Type guard for the URL ``?scope=`` parameter. Falls back to
 * ``model_portfolios`` if the value is missing or unknown so a stale
 * deep link never lands on a 404.
 */
export function parseScopeParam(value: string | null | undefined): AnalyticsScope {
	if (value === "approved_universe" || value === "compare_both") {
		return value;
	}
	return "model_portfolios";
}

/**
 * Type guard for the URL ``?group=`` parameter. Same fallback logic
 * as ``parseScopeParam``.
 */
export function parseGroupParam(value: string | null | undefined): AnalyticsGroupFocus {
	if (
		value === "holdings" ||
		value === "peer" ||
		value === "stress"
	) {
		return value;
	}
	return "returns_risk";
}
