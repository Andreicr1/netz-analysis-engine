/** Exposure domain types. */

export interface ExposureMatrix {
	dimension: string;
	aggregation: string;
	rows: string[];
	columns: string[];
	data: number[][];
}
