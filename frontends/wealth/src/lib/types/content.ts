/** Content domain types — Flash Reports, Outlooks, Spotlights. */

export interface ContentSummary {
	id: string;
	content_type: string;
	title: string | null;
	language: string;
	status: string;
	storage_path: string | null;
	created_by: string | null;
	approved_by: string | null;
	approved_at: string | null;
	created_at: string;
	updated_at: string;
}

export type ContentType = "investment_outlook" | "flash_report" | "manager_spotlight";

export function contentTypeLabel(type: string): string {
	switch (type) {
		case "investment_outlook": return "Investment Outlook";
		case "flash_report":      return "Flash Report";
		case "manager_spotlight": return "Manager Spotlight";
		default:                  return type.replace(/_/g, " ");
	}
}

export function contentTypeColor(type: string): string {
	switch (type) {
		case "investment_outlook": return "var(--ii-info)";
		case "flash_report":      return "var(--ii-warning)";
		case "manager_spotlight": return "var(--ii-success)";
		default:                  return "var(--ii-text-muted)";
	}
}
