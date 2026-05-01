/**
 * IPSGateNotice — empty state shown on PORTFOLIO stage when the
 * profile's Strategic IPS has not been approved.
 *
 * Specs:
 *   - Title resolves the profile via `profileDisplayLabel(_, "full")`
 *     so all 3 default profiles render their canonical marketing
 *     phrasing ("Conservative", "Moderate", "Dynamic Growth").
 *   - CTA "Open Strategic IPS" fires the `onOpenStrategic` callback.
 *   - Wrapper is `role="status"` so screen readers pick it up as a
 *     live region.
 *
 * The component never hardcodes display strings — all profile copy
 * routes through the canonical helper extended in PR-Q165 / PR-BE-7.
 */
import { render, fireEvent } from "@testing-library/svelte";
import { describe, expect, test, vi } from "vitest";
import IPSGateNotice from "../IPSGateNotice.svelte";

describe("IPSGateNotice", () => {
	test("renders title with profileDisplayLabel('conservative', 'full')", () => {
		const { container } = render(IPSGateNotice, {
			props: { profile: "conservative", onOpenStrategic: () => {} },
		});
		const text = container.textContent ?? "";
		expect(text).toContain("Conservative");
		expect(text).toContain("Strategic IPS not approved");
		expect(text).toContain("Approve a Strategic IPS proposal");
	});

	test("renders title with profileDisplayLabel('moderate', 'full')", () => {
		const { container } = render(IPSGateNotice, {
			props: { profile: "moderate", onOpenStrategic: () => {} },
		});
		expect(container.textContent ?? "").toContain("Moderate");
	});

	test("renders title with profileDisplayLabel('growth', 'full') = 'Dynamic Growth'", () => {
		const { container } = render(IPSGateNotice, {
			props: { profile: "growth", onOpenStrategic: () => {} },
		});
		const text = container.textContent ?? "";
		// Full-context profile copy — must use the marketing phrase
		// from `profileDisplayLabel(_, "full")`, never the dense
		// chip form ("Dynamic") or the legacy slug ("aggressive").
		expect(text).toMatch(/Dynamic Growth/);
		expect(text).not.toContain("aggressive");
	});

	test("renders CTA 'Open Strategic IPS' button", () => {
		const { container } = render(IPSGateNotice, {
			props: { profile: "growth", onOpenStrategic: () => {} },
		});
		const btn = container.querySelector("button");
		expect(btn).not.toBeNull();
		expect(btn?.textContent?.trim()).toBe("Open Strategic IPS");
	});

	test("clicking CTA fires onOpenStrategic callback", async () => {
		const onOpenStrategic = vi.fn();
		const { container } = render(IPSGateNotice, {
			props: { profile: "moderate", onOpenStrategic },
		});
		const btn = container.querySelector("button");
		await fireEvent.click(btn!);
		expect(onOpenStrategic).toHaveBeenCalledOnce();
	});

	test("wrapper exposes role='status' for a11y", () => {
		const { container } = render(IPSGateNotice, {
			props: { profile: "conservative", onOpenStrategic: () => {} },
		});
		expect(container.querySelector('[role="status"]')).not.toBeNull();
	});
});
