import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import ConsequenceDialog from "../ConsequenceDialog.svelte";

describe("ConsequenceDialog", () => {
	it("renders as an alertdialog and marks rationale as required", () => {
		render(ConsequenceDialog, {
			props: {
				open: true,
				title: "Approve tenant change",
				impactSummary: "This will publish a tenant-scoped configuration.",
				destructive: true,
				requireRationale: true,
				onConfirm: vi.fn(),
			},
		});

		expect(screen.getByRole("alertdialog")).toBeTruthy();
		expect(screen.getByLabelText("Rationale").getAttribute("aria-required")).toBe("true");
		expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
	});

	it("blocks confirm until rationale satisfies the minimum length", async () => {
		const onConfirm = vi.fn();

		render(ConsequenceDialog, {
			props: {
				open: true,
				title: "Approve tenant change",
				impactSummary: "This will publish a tenant-scoped configuration.",
				requireRationale: true,
				rationaleMinLength: 12,
				onConfirm,
			},
		});

		const confirmButton = screen.getByRole("button", { name: "Confirm action" });
		expect((confirmButton as HTMLButtonElement).disabled).toBe(true);

		await fireEvent.input(screen.getByLabelText("Rationale"), {
			target: { value: "Documented basis for approval." },
		});

		expect((confirmButton as HTMLButtonElement).disabled).toBe(false);
	});
});
