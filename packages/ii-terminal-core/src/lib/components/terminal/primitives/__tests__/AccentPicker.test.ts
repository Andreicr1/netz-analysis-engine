import { render, fireEvent } from "@testing-library/svelte";
import { describe, expect, test, vi } from "vitest";
import AccentPicker from "../AccentPicker.svelte";

describe("AccentPicker", () => {
	test("renders three radiogroup swatches", () => {
		const { container } = render(AccentPicker, {
			props: { value: "amber", onChange: () => {} },
		});
		const group = container.querySelector("[role='radiogroup']");
		expect(group).not.toBeNull();
		expect(container.querySelectorAll(".terminal-accent-swatch").length).toBe(3);
	});

	test("active swatch reflects value prop", () => {
		const { container } = render(AccentPicker, {
			props: { value: "cyan", onChange: () => {} },
		});
		const active = container.querySelector(".terminal-accent-swatch.is-active");
		expect(active?.className).toContain("terminal-accent-swatch--cyan");
		expect(active?.getAttribute("aria-pressed")).toBe("true");
	});

	test("click fires onChange with the clicked value", async () => {
		const onChange = vi.fn();
		const { container } = render(AccentPicker, {
			props: { value: "amber", onChange },
		});
		const violet = container.querySelector(".terminal-accent-swatch--violet")!;
		await fireEvent.click(violet);
		expect(onChange).toHaveBeenCalledWith("violet");
	});
});
