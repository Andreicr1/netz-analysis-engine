import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import Button from "../Button.svelte";

describe("Button", () => {
	it("renders with default variant", () => {
		render(Button, { props: {} });
		const btn = screen.getByRole("button");
		expect(btn).toBeTruthy();
	});

	it("applies disabled attribute", () => {
		render(Button, { props: { disabled: true } });
		const btn = screen.getByRole("button");
		expect(btn.hasAttribute("disabled")).toBe(true);
	});

	it("applies custom class", () => {
		render(Button, { props: { class: "custom-class" } });
		const btn = screen.getByRole("button");
		expect(btn.className).toContain("custom-class");
	});
});
