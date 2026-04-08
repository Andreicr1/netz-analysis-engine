import { render } from "@testing-library/svelte";
import type { Component } from "svelte";
import { expect, test } from "vitest";
import EnterpriseTableOriginal from "./EnterpriseTable.svelte";
import type { ColumnDef } from "./types";

interface Row {
	id: string;
	name: string;
	aum: number;
}

// Coerce the generic component to a concrete Row-typed component so
// @testing-library/svelte's render() accepts strongly-typed props.
const EnterpriseTable = EnterpriseTableOriginal as unknown as Component<{
	rows: Row[];
	columns: ColumnDef<Row>[];
	rowKey: (row: Row) => string;
}>;

const rows: Row[] = [
	{ id: "1", name: "Alpha Fund", aum: 1_200_000_000 },
	{ id: "2", name: "Beta Fund", aum: 800_000_000 },
];
const columns: ColumnDef<Row>[] = [
	{ id: "name", header: "Name", accessor: (r) => r.name },
	{
		id: "aum",
		header: "AUM",
		numeric: true,
		accessor: (r) => r.aum,
		format: (v) => `${((v as number) / 1e6).toFixed(1)}M`,
	},
];

test("renders headers and rows", () => {
	const { getByText } = render(EnterpriseTable, {
		props: {
			rows,
			columns,
			rowKey: (r: Row) => r.id,
		},
	});
	expect(getByText("Name")).toBeTruthy();
	expect(getByText("Alpha Fund")).toBeTruthy();
	expect(getByText("1200.0M")).toBeTruthy();
});

test("numeric column gets tabular-nums class", () => {
	const { container } = render(EnterpriseTable, {
		props: {
			rows,
			columns,
			rowKey: (r: Row) => r.id,
		},
	});
	const aumCells = container.querySelectorAll("td.et-num");
	expect(aumCells.length).toBe(2);
});
