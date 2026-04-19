/**
 * Wealth Library — frontend types mirroring the backend Pydantic
 * shapes from `backend/app/domains/wealth/schemas/sanitized.py`.
 *
 * The types intentionally mirror the API surface defined in spec
 * §4.8 of docs/superpowers/specs/2026-04-08-wealth-library.md and
 * are kept narrow on purpose: storage_path is *only* present on the
 * detail model, never on listings; quant jargon never reaches this
 * file because the backend sanitises before serialising.
 */

export type LibraryNodeKind = "folder" | "file";
export type LibraryPinType = "pinned" | "starred" | "recent";

export interface LibraryNode {
	node_type: LibraryNodeKind;
	path: string;
	label: string;

	// Folder-only
	child_count?: number | null;
	last_updated_at?: string | null;

	// File-only
	id?: string | null;
	kind?: string | null;
	title?: string | null;
	subtitle?: string | null;
	status?: string | null;
	language?: string | null;
	version?: number | null;
	is_current?: boolean | null;
	entity_kind?: string | null;
	entity_label?: string | null;
	entity_slug?: string | null;
	confidence?: number | null;
	created_at?: string | null;
	updated_at?: string | null;
}

export interface LibraryTree {
	roots: LibraryNode[];
	generated_at: string;
}

export interface LibraryNodePage {
	items: LibraryNode[];
	next_cursor: string | null;
	total_estimate?: number | null;
}

export interface LibrarySearchResult {
	items: LibraryNode[];
	next_cursor: string | null;
	total_estimate?: number | null;
	query?: string | null;
}

export interface LibraryPin {
	id: string;
	pin_type: LibraryPinType;
	library_index_id: string;
	library_path: string;
	label: string;
	kind?: string | null;
	created_at: string;
	last_accessed_at: string;
	position?: number | null;
}

export interface LibraryPinsResponse {
	pinned: LibraryPin[];
	starred: LibraryPin[];
	recent: LibraryPin[];
}

export interface LibraryDocumentDetail {
	id: string;
	source_table: string;
	source_id: string;
	kind: string;
	title: string;
	subtitle?: string | null;
	status: string;
	language?: string | null;
	version?: number | null;
	is_current: boolean;
	entity_kind?: string | null;
	entity_id?: string | null;
	entity_slug?: string | null;
	entity_label?: string | null;
	folder_path: string[];
	author_id?: string | null;
	approver_id?: string | null;
	approved_at?: string | null;
	created_at: string;
	updated_at: string;
	confidence?: number | null;
	decision_anchor?: string | null;
	storage_path?: string | null;
	metadata?: Record<string, unknown> | null;
}
