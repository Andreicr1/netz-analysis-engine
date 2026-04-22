import { render, fireEvent } from "@testing-library/svelte";
import { describe, expect, test, vi } from "vitest";
import Pill from "../Pill.svelte";

describe("Pill", () => {
	test("renders as span by default", () => {
		const { container } = render(Pill, { props: { label: "LIVE" } });
		expect(container.querySelector("span.terminal-pill")?.textContent?.trim()).toBe("LIVE");
		expect(container.querySelector("button")).toBeNull();
	});

	test("as=button renders button with aria-pressed when pressed set", () => {
		const { container } = render(Pill, {
			props: { label: "CANDLE", as: "button", pressed: true },
		});
		const btn = container.querySelector("button.terminal-pill");
		expect(btn).not.toBeNull();
		expect(btn?.getAttribute("aria-pressed")).toBe("true");
	});

	test("button fires onclick", async () => {
		const onclick = vi.fn();
		const { container } = render(Pill, {
			props: { label: "GO", as: "button", onclick },
		});
		await fireEvent.click(container.querySelector("button")!);
		expect(onclick).toHaveBeenCalledOnce();
	});

	test("tone applies modifier class", () => {
		const { container } = render(Pill, { props: { label: "OK", tone: "success" } });
		expect(container.querySelector(".terminal-pill--success")).not.toBeNull();
	});
});
