/** Admin-specific TypeScript types. */

export interface ServiceHealth {
	name: string;
	status: "ok" | "degraded" | "down";
	latency_ms: number | null;
	error: string | null;
}

export interface WorkerStatus {
	name: string;
	last_run: string | null;
	duration_ms: number | null;
	status: string;
	error_count: number;
}

export interface TenantListItem {
	organization_id: string;
	org_name: string;
	org_slug: string;
	vertical: string;
	config_count: number;
	asset_count: number;
	created_at: string;
}

export interface TenantDetail {
	organization_id: string;
	org_name: string;
	org_slug: string;
	configs: ConfigListItem[];
	assets: TenantAsset[];
}

export interface TenantAsset {
	id: string;
	organization_id: string;
	asset_type: string;
	content_type: string;
	created_at: string;
	updated_at: string;
}

export interface ConfigListItem {
	vertical: string;
	config_type: string;
	has_override: boolean;
	version: number | null;
	updated_at: string | null;
}

export interface ConfigDiff {
	default: Record<string, unknown>;
	override: Record<string, unknown> | null;
	merged: Record<string, unknown>;
	changed_keys: string[];
}

export interface PromptListItem {
	template_name: string;
	description: string;
	source_level: "org" | "global" | "filesystem";
	version: number | null;
	has_override: boolean;
}

export interface PromptDetail {
	template_name: string;
	content: string;
	source_level: string;
	version: number | null;
}

export interface PromptPreviewResponse {
	rendered: string;
	errors: string[];
}
