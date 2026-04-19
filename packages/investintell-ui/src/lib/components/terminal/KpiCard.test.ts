import { render } from "@testing-library/svelte";
import { describe, expect, test } from "vitest";
import KpiCard from "./KpiCard.svelte";

describe("KpiCard", () => {
	test("renders label + pre-formatted value", () => {
		const { container } = render(KpiCard, {
			props: { label: "TOTAL AUM", value: "$1.23B" },
		});
		expect(container.textContent).toContain("TOTAL AUM");
		expect(container.textContent).toContain("$1.23B");
	});

	test("loading state suppresses delta + shows skeleton", () => {
		const { container } = render(KpiCard, {
			props: { label: "AUM", value: "$1.23B", delta: "+1.2pp", loading: true },
		});
		expect(container.querySelector(".terminal-kpi__skeleton")).not.toBeNull();
		expect(container.querySelector(".terminal-kpi__delta")).toBeNull();
	});

	test("delta tone class follows prop", () => {
		const { container } = render(KpiCard, {
			props: { label: "P/L", value: "+2.1%", delta: "+0.3pp", deltaTone: "up" },
		});
		const delta = container.querySelector(".terminal-kpi__delta");
		expect(delta?.className).toContain("terminal-kpi__delta--up");
	});

	test("size variant sets modifier class", () => {
		const { container } = render(KpiCard, {
			props: { label: "NAV", value: "100.00", size: "lg" },
		});
		expect(container.querySelector(".terminal-kpi--lg")).not.toBeNull();
	});

	test("mono attribute toggles font-family hook", () => {
		const { container } = render(KpiCard, {
			props: { label: "NAV", value: "100.00", mono: false },
		});
		expect(container.querySelector(".terminal-kpi[data-mono]")).toBeNull();
	});
});
