/** Portfolio (tactical) domain types — maps 1:1 to backend schemas. */

export interface PortfolioSummary {
	profile: string;
	snapshot_date: string | null;
	cvar_current: string | null;
	cvar_limit: string | null;
	cvar_utilized_pct: string | null;
	trigger_status: string | null;
	regime: string | null;
	core_weight: string | null;
	satellite_weight: string | null;
	computed_at: string | null;
}

export interface PortfolioSnapshot {
	snapshot_id: string;
	profile: string;
	snapshot_date: string;
	weights: Record<string, number>;
	fund_selection: Record<string, unknown> | null;
	cvar_current: string | null;
	cvar_limit: string | null;
	cvar_utilized_pct: string | null;
	trigger_status: string | null;
	consecutive_breach_days: number;
	regime: string | null;
	core_weight: string | null;
	satellite_weight: string | null;
	regime_probs: Record<string, number> | null;
	cvar_lower_5: string | null;
	cvar_upper_95: string | null;
	computed_at: string | null;
}

export interface StrategicAllocation {
	allocation_id: string;
	profile: string;
	block_id: string;
	target_weight: number;
	min_weight: number;
	max_weight: number;
	risk_budget: number | null;
	rationale: string | null;
	approved_by: string | null;
	effective_from: string;
	effective_to: string | null;
	created_at: string;
}

export interface TacticalPosition {
	position_id: string;
	profile: string;
	block_id: string;
	overweight: number;
	conviction_score: number | null;
	signal_source: string | null;
	rationale: string | null;
	valid_from: string;
	valid_to: string | null;
	created_at: string;
}

export interface EffectiveAllocation {
	profile: string;
	block_id: string;
	strategic_weight: number | null;
	tactical_overweight: number | null;
	effective_weight: number | null;
	min_weight: number | null;
	max_weight: number | null;
}

export interface RebalanceEvent {
	event_id: string;
	profile: string;
	event_date: string;
	event_type: string;
	trigger_reason: string | null;
	weights_before: Record<string, number> | null;
	weights_after: Record<string, number> | null;
	cvar_before: string | null;
	cvar_after: string | null;
	status: string;
	approved_by: string | null;
	notes: string | null;
	created_at: string;
}

/** Editable weight row for the allocation editor */
export interface EditableWeight {
	block_id: string;
	weight: number;
	min_weight: number;
	max_weight: number;
	strategic_weight: number;
}
