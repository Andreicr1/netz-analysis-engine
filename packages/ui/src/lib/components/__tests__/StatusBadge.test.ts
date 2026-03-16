import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import StatusBadge from "../StatusBadge.svelte";

describe("StatusBadge", () => {
	it("renders status text (formatted)", () => {
		render(StatusBadge, { props: { status: "approved" } });
		expect(screen.getByText("Approved")).toBeTruthy();
	});

	it("renders with deal_stage type", () => {
		const { container } = render(StatusBadge, {
			props: { status: "qualified", type: "deal_stage" },
		});
		expect(container.querySelector("span")).toBeTruthy();
		expect(screen.getByText("Qualified")).toBeTruthy();
	});

	it("renders with regime type (uppercase preserved)", () => {
		render(StatusBadge, { props: { status: "RISK_ON", type: "regime" } });
		// formatLabel: "RISK_ON" → "RISK ON" → first letter caps → "RISK ON"
		expect(screen.getByText("RISK ON")).toBeTruthy();
	});

	it("renders with risk type", () => {
		render(StatusBadge, { props: { status: "high", type: "risk" } });
		expect(screen.getByText("High")).toBeTruthy();
	});

	it("renders with review type", () => {
		render(StatusBadge, { props: { status: "pending", type: "review" } });
		expect(screen.getByText("Pending")).toBeTruthy();
	});

	it("renders with content type", () => {
		render(StatusBadge, { props: { status: "published", type: "content" } });
		expect(screen.getByText("Published")).toBeTruthy();
	});

	it("renders unknown status with default styling", () => {
		render(StatusBadge, { props: { status: "unknown_status" } });
		expect(screen.getByText("Unknown Status")).toBeTruthy();
	});
});
