/**
 * NewPortfolioDialog — institutional portfolio creation dialog.
 *
 * Specs (PR-UX-4):
 *   - Empty form → Create button disabled.
 *   - Filled form → Create enabled → POST fires → onCreated called →
 *     dialog closes via onOpenChange(false).
 *   - 409 ConflictError → inline error visible, dialog stays open.
 *   - `onOpenChange(false)` clears form state (when reopened, the
 *     fields are blank).
 *   - `copy_from` filtered to same-profile portfolios only.
 *   - Mandate options use canonical `profileDisplayLabel(_, "full")`
 *     so `growth` renders as "Dynamic Growth".
 *
 * Mock setup: `resetAllMocks` (not `clearAllMocks`) so queued
 * `mockResolvedValueOnce` / `mockRejectedValueOnce` flush between
 * tests (memory note `feedback_vitest_mock_reset_pitfall`).
 *
 * `@investintell/ui`'s barrel transitively loads DataTable +
 * @tanstack/svelte-table, which the vitest ESM resolver cannot
 * transform outside the Vite plugin's reach. We `vi.mock` the
 * barrel with the lightweight stubs in `./__ui-stub__/`; those
 * render plain HTML primitives (Dialog inline, Select as native)
 * so the dialog's contract — bound state, submit, copy_from filter,
 * 409 error path — is covered without depending on bits-ui Portal
 * or the custom Select trigger interaction.
 */
import { render, fireEvent } from "@testing-library/svelte";
import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";

vi.mock("@investintell/ui", async () => {
	return await import("./__ui-stub__/index.js");
});

import { ConflictError } from "@investintell/ui/utils";
import NewPortfolioDialog from "../NewPortfolioDialog.svelte";
import type { ModelPortfolio } from "../../../types/model-portfolio";

function makePortfolio(overrides: Partial<ModelPortfolio> = {}): ModelPortfolio {
	return {
		id: overrides.id ?? "00000000-0000-0000-0000-000000000001",
		profile: overrides.profile ?? "growth",
		display_name: overrides.display_name ?? "Existing Portfolio",
		description: null,
		benchmark_composite: null,
		inception_date: null,
		backtest_start_date: null,
		inception_nav: 1000,
		status: "draft",
		state: "draft",
		state_metadata: {},
		state_changed_at: null,
		state_changed_by: null,
		allowed_actions: ["construct", "archive"],
		fund_selection_schema: null,
		created_at: "2026-01-01T00:00:00Z",
		created_by: null,
		...overrides,
	};
}

beforeEach(() => {
	// `resetAllMocks` (not `clearAllMocks`) so queued mockXxxValueOnce
	// chains flush between tests — see project memory note
	// `feedback_vitest_mock_reset_pitfall`.
	vi.resetAllMocks();
});

afterEach(() => {
	vi.resetAllMocks();
});

describe("NewPortfolioDialog — token + label discipline", () => {
	test("mandate dropdown labels use profileDisplayLabel(_, 'full')", () => {
		// `growth` MUST render as "Dynamic Growth" via the canonical
		// helper from PR-UX-5 / PR-BE-7. The legacy `aggressive` slug
		// MUST NOT appear anywhere in the option list.
		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "growth",
				portfolios: [],
				create: vi.fn(),
				onCreated: vi.fn(),
			},
		});
		const select = container.querySelector(
			'[data-testid="npd-mandate-select-wrap"] select',
		) as HTMLSelectElement;
		expect(select).not.toBeNull();
		const optionLabels = Array.from(select.options).map((o) => o.text);
		const optionValues = Array.from(select.options).map((o) => o.value);
		// Canonical 3-profile taxonomy enforced by the terminal allocation
		// route validation. The mandate slug `moderate` is rendered as
		// "Balanced" — the institutional name for the middle risk profile.
		expect(optionLabels).toEqual([
			"Conservative",
			"Balanced",
			"Dynamic Growth",
		]);
		// Slug-level regression: only `{conservative, moderate, growth}`
		// are valid VALUES — `balanced` and `aggressive` are display-only
		// labels that must never appear as enum values.
		expect(optionValues).toEqual(["conservative", "moderate", "growth"]);
	});

	test("form renders Name + Mandate + Description + Copy from labels", () => {
		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "moderate",
				portfolios: [],
				create: vi.fn(),
				onCreated: vi.fn(),
			},
		});
		const text = container.textContent ?? "";
		expect(text).toContain("Name");
		expect(text).toContain("Mandate");
		expect(text).toContain("Description");
		expect(text).toContain("Copy from existing");
	});

	test("profileDisplayLabel('growth', 'full') === 'Dynamic Growth'", async () => {
		const { profileDisplayLabel } = await import(
			"../../../i18n/quant-labels"
		);
		expect(profileDisplayLabel("growth", "full")).toBe("Dynamic Growth");
		expect(profileDisplayLabel("conservative", "full")).toBe("Conservative");
		expect(profileDisplayLabel("moderate", "full")).toBe("Balanced");
	});
});

describe("NewPortfolioDialog — submit gating", () => {
	test("empty name → Create button disabled", () => {
		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "moderate",
				portfolios: [],
				create: vi.fn(),
				onCreated: vi.fn(),
			},
		});
		const submit = container.querySelector(
			'[data-testid="npd-submit-btn"]',
		) as HTMLButtonElement | null;
		expect(submit).not.toBeNull();
		expect(submit?.disabled).toBe(true);
	});

	test("filled name enables Create button", async () => {
		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "moderate",
				portfolios: [],
				create: vi.fn(),
				onCreated: vi.fn(),
			},
		});
		const nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		await fireEvent.input(nameInput, {
			target: { value: "Institutional 60/40" },
		});
		const submit = container.querySelector(
			'[data-testid="npd-submit-btn"]',
		) as HTMLButtonElement;
		expect(submit.disabled).toBe(false);
	});
});

describe("NewPortfolioDialog — happy path", () => {
	test("submit → create called with payload → onCreated → onOpenChange(false)", async () => {
		const created = makePortfolio({
			id: "11111111-1111-1111-1111-111111111111",
			profile: "growth",
			display_name: "New Draft",
		});
		const create = vi.fn().mockResolvedValueOnce(created);
		const onCreated = vi.fn();
		const onOpenChange = vi.fn();

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange,
				profile: "growth",
				portfolios: [],
				create,
				onCreated,
			},
		});

		const nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		await fireEvent.input(nameInput, { target: { value: "New Draft" } });

		const form = container.querySelector(
			'[data-testid="new-portfolio-dialog"]',
		) as HTMLFormElement;
		await fireEvent.submit(form);

		// Assert payload sent — profile defaults to URL-bound `growth`.
		expect(create).toHaveBeenCalledOnce();
		expect(create.mock.calls[0]?.[0]).toEqual({
			profile: "growth",
			display_name: "New Draft",
		});

		// Assert onCreated received the persisted row + dialog closed
		expect(onCreated).toHaveBeenCalledWith(created);
		expect(onOpenChange).toHaveBeenCalledWith(false);
	});

	test("description included in payload when provided", async () => {
		const created = makePortfolio({
			id: "33333333-3333-3333-3333-333333333333",
			profile: "moderate",
			display_name: "Forked",
		});
		const create = vi.fn().mockResolvedValueOnce(created);

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "moderate",
				portfolios: [],
				create,
				onCreated: () => {},
			},
		});

		const nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		const descInput = container.querySelector(
			'[data-testid="npd-description-input"]',
		) as HTMLInputElement;

		await fireEvent.input(nameInput, { target: { value: "Forked" } });
		await fireEvent.input(descInput, {
			target: { value: "Forked from Sibling" },
		});

		const form = container.querySelector(
			'[data-testid="new-portfolio-dialog"]',
		) as HTMLFormElement;
		await fireEvent.submit(form);

		expect(create).toHaveBeenCalledOnce();
		expect(create.mock.calls[0]?.[0]).toEqual({
			profile: "moderate",
			display_name: "Forked",
			description: "Forked from Sibling",
		});
	});

	test("copy_from option is offered to user when same-profile siblings exist", () => {
		// Selection-bridge across the two-component bind boundary
		// (NewPortfolioDialog → stub Select) is a happy-dom rough
		// edge. The data contract — same-profile siblings appear in
		// `copyFromOptions` and are eligible to be selected — is
		// covered separately in the "copy_from filtering" describe
		// block. Here we just assert the sibling is rendered as an
		// `<option>` so the user CAN pick it; the payload-forwarding
		// path is covered by an integration test against the live
		// terminal page.
		const sibling = makePortfolio({
			id: "22222222-2222-2222-2222-222222222222",
			profile: "moderate",
			display_name: "Sibling",
		});

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "moderate",
				portfolios: [sibling],
				create: vi.fn(),
				onCreated: vi.fn(),
			},
		});

		const copySelect = container.querySelector(
			'[data-testid="npd-copy-from-select-wrap"] select',
		) as HTMLSelectElement;
		const optionValues = Array.from(copySelect.options).map((o) => o.value);
		expect(optionValues).toContain(sibling.id);
	});
});

describe("NewPortfolioDialog — 409 conflict path", () => {
	test("ConflictError → inline error + dialog stays open", async () => {
		const create = vi
			.fn()
			.mockRejectedValueOnce(
				new ConflictError(
					"A portfolio named 'Dup' already exists for this organization.",
				),
			);
		const onCreated = vi.fn();
		const onOpenChange = vi.fn();

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange,
				profile: "growth",
				portfolios: [],
				create,
				onCreated,
			},
		});

		const nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		await fireEvent.input(nameInput, { target: { value: "Dup" } });

		const form = container.querySelector(
			'[data-testid="new-portfolio-dialog"]',
		) as HTMLFormElement;
		await fireEvent.submit(form);

		// Inline error visible
		const err = container.querySelector(
			'[data-testid="npd-submit-error"]',
		);
		expect(err).not.toBeNull();
		expect(err?.textContent).toContain("already exists");

		// Dialog stays open — onOpenChange(false) NOT called
		expect(onOpenChange).not.toHaveBeenCalled();
		// onCreated NOT invoked on conflict
		expect(onCreated).not.toHaveBeenCalled();
	});

	test("generic Error from create → message rendered inline", async () => {
		const create = vi
			.fn()
			.mockRejectedValueOnce(new Error("Network timeout"));

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "growth",
				portfolios: [],
				create,
				onCreated: () => {},
			},
		});

		const nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		await fireEvent.input(nameInput, { target: { value: "X" } });

		const form = container.querySelector(
			'[data-testid="new-portfolio-dialog"]',
		) as HTMLFormElement;
		await fireEvent.submit(form);

		const err = container.querySelector(
			'[data-testid="npd-submit-error"]',
		);
		expect(err?.textContent).toContain("Network timeout");
	});

	test("create returning null → session-expired fallback rendered", async () => {
		// Post-Codex-P2 (PR-UX-4): the only path through which
		// `workspace.createPortfolio` resolves with `null` is the
		// pre-Clerk token-missing guard, which surfaces to the user as
		// a session-expired condition. Every transport / 4xx / 5xx
		// failure now throws (covered by the ConflictError + generic
		// Error tests above).
		const create = vi.fn().mockResolvedValueOnce(null);

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "growth",
				portfolios: [],
				create,
				onCreated: () => {},
			},
		});

		const nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		await fireEvent.input(nameInput, { target: { value: "Y" } });

		const form = container.querySelector(
			'[data-testid="new-portfolio-dialog"]',
		) as HTMLFormElement;
		await fireEvent.submit(form);

		const err = container.querySelector(
			'[data-testid="npd-submit-error"]',
		);
		expect(err?.textContent).toContain("Session expired");
	});

	test("ServerError from create → backend message bubbles inline (Codex P2)", async () => {
		// Codex P2 — once `workspace.createPortfolio` rethrows, any
		// non-409 4xx/5xx error class (ServerError, ValidationError, …)
		// must surface its message to the user. The dialog falls
		// through to the `err instanceof Error` branch and renders
		// `err.message`. This regression-tests the rethrow contract:
		// a backend "detail.message" is no longer collapsed to a
		// generic fallback.
		const { ServerError } = await import("@investintell/ui/utils");
		const create = vi
			.fn()
			.mockRejectedValueOnce(
				new ServerError("Calibration profile is locked.", 423),
			);

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "growth",
				portfolios: [],
				create,
				onCreated: () => {},
			},
		});

		const nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		await fireEvent.input(nameInput, { target: { value: "Locked" } });

		const form = container.querySelector(
			'[data-testid="new-portfolio-dialog"]',
		) as HTMLFormElement;
		await fireEvent.submit(form);

		const err = container.querySelector(
			'[data-testid="npd-submit-error"]',
		);
		expect(err?.textContent).toContain("Calibration profile is locked.");
	});
});

describe("NewPortfolioDialog — copy_from filtering", () => {
	test("copy_from select includes only same-profile portfolios", () => {
		const samePf = makePortfolio({
			id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
			profile: "growth",
			display_name: "Growth Sibling",
		});
		const otherPf = makePortfolio({
			id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
			profile: "conservative",
			display_name: "Cons Sibling",
		});

		const { container } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "growth",
				portfolios: [samePf, otherPf],
				create: vi.fn(),
				onCreated: vi.fn(),
			},
		});

		const select = container.querySelector(
			'[data-testid="npd-copy-from-select-wrap"] select',
		) as HTMLSelectElement;
		const optionTexts = Array.from(select.options).map((o) => o.text);

		// Same-profile sibling is offered
		expect(optionTexts).toContain("Growth Sibling");
		// Cross-profile sibling is filtered out
		expect(optionTexts).not.toContain("Cons Sibling");
		// Baseline "start fresh" is always present
		expect(optionTexts.some((t) => t.includes("start fresh"))).toBe(true);
	});
});

describe("NewPortfolioDialog — close clears state", () => {
	test("close → reopen → form fields blank", async () => {
		const { container, rerender } = render(NewPortfolioDialog, {
			props: {
				open: true,
				onOpenChange: () => {},
				profile: "moderate",
				portfolios: [],
				create: vi.fn(),
				onCreated: vi.fn(),
			},
		});

		let nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		await fireEvent.input(nameInput, {
			target: { value: "Stale value" },
		});
		expect(nameInput.value).toBe("Stale value");

		// Close — open-state effect resets the form
		await rerender({
			open: false,
			onOpenChange: () => {},
			profile: "moderate",
			portfolios: [],
			create: vi.fn(),
			onCreated: vi.fn(),
		});

		// Reopen — query the freshly-mounted input
		await rerender({
			open: true,
			onOpenChange: () => {},
			profile: "moderate",
			portfolios: [],
			create: vi.fn(),
			onCreated: vi.fn(),
		});

		nameInput = container.querySelector(
			'[data-testid="npd-name-input"]',
		) as HTMLInputElement;
		expect(nameInput).not.toBeNull();
		expect(nameInput.value).toBe("");
	});
});
