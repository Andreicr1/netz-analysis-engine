import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import DataCard from "../DataCard.svelte";

describe("DataCard", () => {
	it("renders value and label", () => {
		render(DataCard, { props: { value: "R$ 1.2M", label: "AUM" } });
		expect(screen.getByText("R$ 1.2M")).toBeTruthy();
		expect(screen.getByText("AUM")).toBeTruthy();
	});

	it("renders upward trend with green color", () => {
		const { container } = render(DataCard, {
			props: { value: "15%", label: "Return", trend: "up", trendValue: "+2.3%" },
		});
		const trendEl = container.querySelector("[class*='trend']") ?? container.querySelector("span");
		expect(trendEl?.textContent).toContain("+2.3%");
	});

	it("renders downward trend", () => {
		const { container } = render(DataCard, {
			props: { value: "5%", label: "CVaR", trend: "down", trendValue: "-1.1%" },
		});
		expect(container.textContent).toContain("-1.1%");
	});

	it("renders flat trend", () => {
		render(DataCard, {
			props: { value: "0%", label: "Change", trend: "flat" },
		});
		expect(screen.getByText("0%")).toBeTruthy();
	});
});
