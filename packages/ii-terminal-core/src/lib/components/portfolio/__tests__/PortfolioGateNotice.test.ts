/**
 * PortfolioGateNotice — empty state shown on STRESS stage when the
 * tenant has no portfolios for the active profile.
 *
 * Specs:
 *   - Title resolves the profile via `profileDisplayLabel(_, "full")`.
 *   - No CTA — operator navigates back via the stage strip.
 *   - Wrapper is `role="status"`.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, test } from "vitest";
import PortfolioGateNotice from "../PortfolioGateNotice.svelte";

describe("PortfolioGateNotice", () => {
	test("renders title with profileDisplayLabel('growth', 'full')", () => {
		const { container } = render(PortfolioGateNotice, {
			props: { profile: "growth" },
		});
		const text = container.textContent ?? "";
		expect(text).toContain("Dynamic Growth");
		expect(text).toContain("No portfolios yet");
		expect(text).toContain("Create a portfolio in the Portfolio stage first.");
	});

	test("renders title with profileDisplayLabel('conservative', 'full')", () => {
		const { container } = render(PortfolioGateNotice, {
			props: { profile: "conservative" },
		});
		expect(container.textContent ?? "").toContain("Conservative");
	});

	test("does not render any CTA button", () => {
		const { container } = render(PortfolioGateNotice, {
			props: { profile: "moderate" },
		});
		expect(container.querySelector("button")).toBeNull();
	});

	test("wrapper exposes role='status' for a11y", () => {
		const { container } = render(PortfolioGateNotice, {
			props: { profile: "moderate" },
		});
		expect(container.querySelector('[role="status"]')).not.toBeNull();
	});
});
