/**
 * Phase 7 Alerts Unification — TS shapes mirroring the backend
 * ``UnifiedAlertRead`` schema in
 * ``backend/app/domains/wealth/schemas/alerts.py``.
 *
 * The frontend never branches on the source. Every alert flows
 * through this single contract; only the backend aggregator knows
 * about the underlying ``strategy_drift_alerts`` /
 * ``portfolio_alerts`` tables.
 *
 * Per DL15: read/unread state lives on the backend's
 * ``acknowledged_at`` columns. The GlobalAlertInbox never touches
 * localStorage / sessionStorage.
 */

/** Canonical severity scale used by the unified API. */
export type UnifiedSeverity = "info" | "warning" | "critical";

/** Source table the alert came from. The frontend uses this only to
 *  build the acknowledge URL — never to branch rendering logic. */
export type UnifiedAlertSource = "drift" | "portfolio";

/** What kind of entity the alert is about. Drives href + icon. */
export type UnifiedSubjectKind = "instrument" | "portfolio";

export interface UnifiedAlert {
	/** Source row id. Combine with ``source`` for the acknowledge call. */
	id: string;
	source: UnifiedAlertSource;

	/** Snake-case alert kind for icon / label routing. */
	alert_type: string;

	/** Normalized severity. */
	severity: UnifiedSeverity;

	/** 1-line headline. */
	title: string;
	subtitle: string | null;

	/** Subject linkage. */
	subject_kind: UnifiedSubjectKind;
	subject_id: string;
	subject_name: string | null;

	/** Read state. */
	created_at: string;
	acknowledged_at: string | null;
	acknowledged_by: string | null;

	/** Drill-through href computed by the backend route layer. */
	href: string | null;
}

/** Envelope returned by GET /alerts/inbox. */
export interface UnifiedAlertInbox {
	items: UnifiedAlert[];
	total: number;
	unread_count: number;
	by_source: Record<string, number>;
}

/** Per-portfolio open count from GET /alerts/portfolio/{id}/count. */
export interface PortfolioAlertCount {
	portfolio_id: string;
	open_count: number;
}
