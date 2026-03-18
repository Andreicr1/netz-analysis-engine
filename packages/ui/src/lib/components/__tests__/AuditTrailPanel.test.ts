import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import AuditTrailPanel, { type AuditTrailEntry } from "../AuditTrailPanel.svelte";

beforeEach(() => {
	vi.useFakeTimers();
	vi.setSystemTime(new Date("2026-03-18T15:00:00Z"));
});

afterEach(() => {
	vi.useRealTimers();
});

function buildEntries(): AuditTrailEntry[] {
	return [
		{
			id: "entry-1",
			actor: "Maria Admin",
			timestamp: "2026-03-16T09:00:00Z",
			action: "Created mandate",
			scope: "Portfolio setup",
			outcome: "Recorded",
		},
		{
			id: "entry-2",
			actor: "Maria Admin",
			timestamp: "2026-03-17T11:00:00Z",
			action: "Reviewed mandate",
			scope: "Portfolio setup",
			outcome: "Approved",
			actorCapacity: "Investment Committee",
			actorEmail: "maria@netz.test",
			immutable: true,
			sourceSystem: "manual",
		},
		{
			id: "entry-3",
			actor: "Joao Operator",
			timestamp: "2026-03-18T10:00:00Z",
			action: "Published decision",
			scope: "Credit approval",
			outcome: "Published",
		},
		{
			id: "entry-4",
			actor: "Ana Reviewer",
			timestamp: "2026-03-18T12:00:00Z",
			action: "Shared report",
			scope: "Credit approval",
			outcome: "Delivered",
		},
	];
}

describe("AuditTrailPanel", () => {
	it("adds log accessibility and renders grouped dates with metadata", () => {
		const { container } = render(AuditTrailPanel, {
			props: {
				title: "Recent actions",
				entries: buildEntries(),
				maxVisible: 4,
			},
		});

		expect(screen.getByRole("log", { name: "Recent actions" })).toBeTruthy();
		expect(screen.getByText("Today")).toBeTruthy();
		expect(screen.getByText("Yesterday")).toBeTruthy();
		expect(screen.getByText("Investment Committee")).toBeTruthy();
		expect(screen.getByText("maria@netz.test")).toBeTruthy();
		expect(screen.getByText("manual")).toBeTruthy();
		expect(screen.getByText("Immutable")).toBeTruthy();
		expect(container.querySelector("time[datetime]")).toBeTruthy();
	});

	it("caps visible entries and reveals older history on demand", async () => {
		render(AuditTrailPanel, {
			props: {
				entries: buildEntries(),
				maxVisible: 2,
			},
		});

		expect(screen.queryByText("Created mandate")).toBeNull();
		expect(screen.getByRole("button", { name: "Load earlier entries (2)" })).toBeTruthy();

		await fireEvent.click(screen.getByRole("button", { name: "Load earlier entries (2)" }));

		expect(screen.getByText("Created mandate")).toBeTruthy();
	});
});
