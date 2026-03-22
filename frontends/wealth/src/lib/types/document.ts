/** Document domain types — upload, ingestion pipeline. */

export interface WealthDocument {
	id: string;
	title: string;
	filename: string;
	content_type: string | null;
	domain: string | null;
	current_version: number;
	created_at: string | null;
	updated_at: string | null;
	created_by: string | null;
}

export interface DocumentPage {
	items: WealthDocument[];
	limit: number;
	offset: number;
}

export interface UploadUrlResponse {
	upload_id: string;
	upload_url: string;
	blob_path: string;
	expires_in: number;
}

export interface UploadCompleteResponse {
	job_id: string;
	version_id: string;
	document_id: string;
}

export interface ProcessPendingResponse {
	processed: number;
	indexed: number;
	failed: number;
	skipped: number;
}

/** Pipeline stages for progress visualization. */
export const PIPELINE_STAGES = [
	"pre-filter",
	"ocr",
	"classify",
	"govern",
	"chunk",
	"extract",
	"embed",
	"storage",
	"index",
	"complete",
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

export function stageLabel(stage: string): string {
	switch (stage) {
		case "pre-filter": return "Pre-filter";
		case "ocr":        return "OCR";
		case "classify":   return "Classify";
		case "govern":     return "Governance";
		case "chunk":      return "Chunk";
		case "extract":    return "Extract";
		case "embed":      return "Embed";
		case "storage":    return "Storage";
		case "index":      return "Index";
		case "complete":   return "Complete";
		default:           return stage;
	}
}

export function domainLabel(domain: string | null): string {
	switch (domain) {
		case "dd_report":   return "DD Report";
		case "fact_sheet":  return "Fact Sheet";
		case "compliance":  return "Compliance";
		default:            return domain ?? "Other";
	}
}
