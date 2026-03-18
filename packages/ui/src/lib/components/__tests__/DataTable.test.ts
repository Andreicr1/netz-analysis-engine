import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import DataTable from "../DataTable.svelte";

const columns = [
	{
		accessorKey: "group",
		header: "Group",
		cell: ({ getValue }: { getValue: () => unknown }) => String(getValue()),
		enableSorting: true,
	},
	{
		accessorKey: "name",
		header: "Name",
		cell: ({ getValue }: { getValue: () => unknown }) => String(getValue()),
		enableSorting: true,
	},
];

describe("DataTable", () => {
	it("caps page size at 100 rows", () => {
		const data = Array.from({ length: 150 }, (_, index) => ({
			group: `G${index}`,
			name: `Row ${index}`,
		}));

		const { container } = render(DataTable, {
			props: {
				data,
				columns,
				pageSize: 150,
			},
		});

		expect(container.querySelectorAll("tbody tr").length).toBe(100);
		expect(screen.getByText(/Showing 1-100 of 150/)).toBeTruthy();
	});

	it("supports multi-sort with shift-click", async () => {
		const data = [
			{ group: "B", name: "Alpha" },
			{ group: "A", name: "Alpha" },
			{ group: "A", name: "Beta" },
		];

		const { container } = render(DataTable, {
			props: {
				data,
				columns,
				pageSize: 10,
			},
		});

		await fireEvent.click(screen.getByRole("button", { name: "Name" }));
		await fireEvent.click(screen.getByRole("button", { name: "Group" }), { shiftKey: true });

		const rows = Array.from(container.querySelectorAll("tbody tr")).map((row) =>
			row.textContent?.replace(/\s+/g, " ").trim(),
		);

		expect(rows[0]).toBe("AAlpha");
		expect(rows[1]).toBe("BAlpha");
		expect(rows[2]).toBe("ABeta");
	});
});
