/** Exposure domain types. */

export interface ExposureMatrix {
	dimension: string;
	aggregation: string;
	rows: string[];
	columns: string[];
	data: number[][];
	is_empty: boolean;
	as_of: string | null;
}

export interface ExposureMetadata {
	as_of: string | null;
	snapshot_count: number;
	profile_count: number;
}
