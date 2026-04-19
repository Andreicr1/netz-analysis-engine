import { render } from "@testing-library/svelte";
import { describe, expect, test } from "vitest";
import MiniSparkline from "./MiniSparkline.svelte";

describe("MiniSparkline", () => {
	test("renders polyline with points when data has ≥2 entries", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [1, 2, 3, 4] },
		});
		const polyline = container.querySelector("polyline");
		expect(polyline).not.toBeNull();
		const points = polyline?.getAttribute("points") ?? "";
		expect(points.split(" ")).toHaveLength(4);
	});

	test("empty data renders svg without polyline", () => {
		const { container } = render(MiniSparkline, { props: { data: [] } });
		expect(container.querySelector("svg.mini-sparkline")).not.toBeNull();
		expect(container.querySelector("polyline")).toBeNull();
	});

	test("single-point data renders svg without polyline", () => {
		const { container } = render(MiniSparkline, { props: { data: [42] } });
		expect(container.querySelector("polyline")).toBeNull();
	});

	test("auto-tone is up when last > first", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [10, 12, 15] },
		});
		expect(container.querySelector(".mini-sparkline--up")).not.toBeNull();
	});

	test("auto-tone is down when last < first", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [15, 12, 10] },
		});
		expect(container.querySelector(".mini-sparkline--down")).not.toBeNull();
	});

	test("auto-tone is neutral when first equals last", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [10, 20, 10] },
		});
		expect(container.querySelector(".mini-sparkline--neutral")).not.toBeNull();
	});

	test("explicit tone prop overrides auto", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [10, 12, 15], tone: "down" },
		});
		expect(container.querySelector(".mini-sparkline--down")).not.toBeNull();
	});

	test("width + height default to 60x18 and viewBox matches", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [1, 2, 3] },
		});
		const svg = container.querySelector("svg");
		expect(svg?.getAttribute("width")).toBe("60");
		expect(svg?.getAttribute("height")).toBe("18");
		expect(svg?.getAttribute("viewBox")).toBe("0 0 60 18");
	});

	test("custom width/height propagate to viewBox", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [1, 2], width: 120, height: 32 },
		});
		expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe(
			"0 0 120 32",
		);
	});

	test("ariaLabel omitted → aria-hidden true; provided → aria-label set", () => {
		const hidden = render(MiniSparkline, { props: { data: [1, 2] } });
		expect(hidden.container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
		const labeled = render(MiniSparkline, {
			props: { data: [1, 2], ariaLabel: "12mo NAV trend" },
		});
		const svg = labeled.container.querySelector("svg");
		expect(svg?.getAttribute("aria-label")).toBe("12mo NAV trend");
		expect(svg?.getAttribute("aria-hidden")).toBeNull();
	});

	test("points stay within viewBox for monotonic series", () => {
		const { container } = render(MiniSparkline, {
			props: { data: [1, 2, 3, 4, 5], width: 60, height: 18 },
		});
		const raw = container.querySelector("polyline")?.getAttribute("points") ?? "";
		const pairs = raw.trim().split(" ").map((p) => p.split(",").map(Number));
		for (const [x, y] of pairs) {
			expect(x).toBeGreaterThanOrEqual(0);
			expect(x).toBeLessThanOrEqual(60);
			expect(y).toBeGreaterThanOrEqual(0);
			expect(y).toBeLessThanOrEqual(18);
		}
	});
});
