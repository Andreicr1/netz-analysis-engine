import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import StatusBadge from "../StatusBadge.svelte";

describe("StatusBadge", () => {
	it("renders status text (formatted)", () => {
		render(StatusBadge, { props: { status: "approved" } });
		expect(screen.getByText("Approved")).toBeTruthy();
	});

	it("keeps compatibility with legacy type props", () => {
		const { container } = render(StatusBadge, {
			props: { status: "qualified", type: "deal_stage" },
		});
		expect(container.querySelector("span")).toBeTruthy();
		expect(screen.getByText("Qualified")).toBeTruthy();
	});

	it("uses an explicit label override when provided", () => {
		render(StatusBadge, { props: { status: "warning", label: "Override" } });
		expect(screen.getByText("Override")).toBeTruthy();
	});

	it("uses the resolver output when provided", () => {
		render(StatusBadge, {
			props: {
				status: "qualified",
				resolve: () => ({
					label: "Qualified for IC",
					severity: "info",
					color: "var(--netz-info)",
				}),
			},
		});
		expect(screen.getByText("Qualified for IC")).toBeTruthy();
	});

	it("renders unknown status with default styling", () => {
		render(StatusBadge, { props: { status: "unknown_status" } });
		expect(screen.getByText("Unknown Status")).toBeTruthy();
	});

	it("infers severity attributes from generic status tokens", () => {
		const { container } = render(StatusBadge, { props: { status: "approved" } });
		expect(container.querySelector("[data-status-severity='success']")).toBeTruthy();
	});
});
