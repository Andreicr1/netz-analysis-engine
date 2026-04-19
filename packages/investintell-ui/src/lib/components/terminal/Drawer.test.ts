import { render, fireEvent } from "@testing-library/svelte";
import { describe, expect, test, vi } from "vitest";
import { createRawSnippet } from "svelte";
import Drawer from "./Drawer.svelte";

function bodySnippet(html: string) {
	return createRawSnippet(() => ({
		render: () => html,
	}));
}

describe("Drawer", () => {
	test("closed state renders nothing", () => {
		const { container } = render(Drawer, {
			props: {
				open: false,
				label: "Committee",
				onClose: () => {},
				children: bodySnippet("<p>body</p>"),
			},
		});
		expect(container.querySelector(".drawer")).toBeNull();
		expect(container.querySelector(".drawer-scrim")).toBeNull();
	});

	test("open state renders dialog + scrim with aria-modal + aria-label", () => {
		const { container } = render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				onClose: () => {},
				children: bodySnippet("<p>body</p>"),
			},
		});
		const dialog = container.querySelector(".drawer");
		expect(dialog).not.toBeNull();
		expect(dialog?.getAttribute("role")).toBe("dialog");
		expect(dialog?.getAttribute("aria-modal")).toBe("true");
		expect(dialog?.getAttribute("aria-label")).toBe("Committee");
		expect(container.querySelector(".drawer-scrim")).not.toBeNull();
	});

	test("ESC keydown triggers onClose", async () => {
		const onClose = vi.fn();
		render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				onClose,
				children: bodySnippet("<p>body</p>"),
			},
		});
		await fireEvent.keyDown(window, { key: "Escape" });
		expect(onClose).toHaveBeenCalledOnce();
	});

	test("ESC when closed does not fire onClose", async () => {
		const onClose = vi.fn();
		render(Drawer, {
			props: {
				open: false,
				label: "Committee",
				onClose,
				children: bodySnippet("<p>body</p>"),
			},
		});
		await fireEvent.keyDown(window, { key: "Escape" });
		expect(onClose).not.toHaveBeenCalled();
	});

	test("scrim click fires onClose", async () => {
		const onClose = vi.fn();
		const { container } = render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				onClose,
				children: bodySnippet("<p>body</p>"),
			},
		});
		const scrim = container.querySelector(".drawer-scrim") as HTMLElement;
		await fireEvent.click(scrim);
		expect(onClose).toHaveBeenCalledOnce();
	});

	test("close button fires onClose", async () => {
		const onClose = vi.fn();
		const { container } = render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				onClose,
				children: bodySnippet("<p>body</p>"),
			},
		});
		const closeBtn = container.querySelector(".drawer__close") as HTMLElement;
		await fireEvent.click(closeBtn);
		expect(onClose).toHaveBeenCalledOnce();
	});

	test("side=left applies modifier class and inline width", () => {
		const { container } = render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				side: "left",
				width: 420,
				onClose: () => {},
				children: bodySnippet("<p>body</p>"),
			},
		});
		const dialog = container.querySelector(".drawer") as HTMLElement;
		expect(dialog.classList.contains("drawer--left")).toBe(true);
		expect(dialog.style.width).toBe("420px");
	});

	test("default side=right applies modifier class", () => {
		const { container } = render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				onClose: () => {},
				children: bodySnippet("<p>body</p>"),
			},
		});
		expect(container.querySelector(".drawer--right")).not.toBeNull();
	});

	test("Tab from last focusable wraps to the close button (first in DOM order)", async () => {
		const onClose = vi.fn();
		const { container } = render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				onClose,
				children: bodySnippet(
					'<div><button type="button" id="a">A</button><button type="button" id="b">B</button></div>',
				),
			},
		});
		const b = container.querySelector("#b") as HTMLElement;
		b.focus();
		expect(document.activeElement).toBe(b);
		await fireEvent.keyDown(window, { key: "Tab" });
		const closeBtn = container.querySelector(".drawer__close") as HTMLElement;
		expect(document.activeElement).toBe(closeBtn);
	});

	test("Shift+Tab from close button (first) wraps to last focusable", async () => {
		const { container } = render(Drawer, {
			props: {
				open: true,
				label: "Committee",
				onClose: () => {},
				children: bodySnippet(
					'<div><button type="button" id="a">A</button><button type="button" id="b">B</button></div>',
				),
			},
		});
		const closeBtn = container.querySelector(".drawer__close") as HTMLElement;
		closeBtn.focus();
		expect(document.activeElement).toBe(closeBtn);
		await fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
		const b = container.querySelector("#b") as HTMLElement;
		expect(document.activeElement).toBe(b);
	});
});
