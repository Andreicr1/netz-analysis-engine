/**
 * portfolio-workspace.createPortfolio — rethrow contract.
 *
 * PR-UX-4 Codex P2 — `createPortfolio` previously swallowed every
 * api-client exception and resolved with `null`. That bypassed
 * `NewPortfolioDialog`'s `try { … } catch (ConflictError)` path: a
 * structured 409 from PR-BE-4 would degrade to a generic "Failed to
 * create portfolio." message.
 *
 * The remediation:
 *   - On `!_getToken` → resolve with `null` (pre-Clerk guard, the
 *     dialog renders a session-expired fallback).
 *   - On any api-client error → capture on `lastError` for
 *     telemetry, then `throw err` so the caller can render the
 *     backend's actionable detail.
 *
 * Mock: `vi.mock("../../api/client", …)` so we don't pull in the
 * real fetch layer. We exercise the contract through the public
 * `setGetToken` + `createPortfolio` surface.
 */
import { describe, expect, test, vi, beforeEach } from "vitest";
import { ConflictError, ServerError } from "@investintell/ui/utils";

const apiPostMock = vi.fn();

vi.mock("../../api/client", () => ({
	createClientApiClient: vi.fn(() => ({
		post: apiPostMock,
		get: vi.fn(),
		patch: vi.fn(),
		put: vi.fn(),
		delete: vi.fn(),
	})),
}));

import { PortfolioWorkspaceState } from "../portfolio-workspace.svelte";

beforeEach(() => {
	apiPostMock.mockReset();
});

function makeWorkspace() {
	const ws = new PortfolioWorkspaceState();
	ws.setGetToken(async () => "test-jwt");
	return ws;
}

describe("PortfolioWorkspaceState.createPortfolio — rethrow contract", () => {
	test("returns null when no token provider configured", async () => {
		const ws = new PortfolioWorkspaceState();
		const result = await ws.createPortfolio({ display_name: "X" });
		expect(result).toBeNull();
		expect(apiPostMock).not.toHaveBeenCalled();
	});

	test("rethrows ConflictError + records lastError", async () => {
		const ws = makeWorkspace();
		const dup = new ConflictError(
			"A portfolio named 'Dup' already exists for this organization.",
		);
		apiPostMock.mockRejectedValueOnce(dup);

		await expect(
			ws.createPortfolio({ display_name: "Dup", profile: "growth" }),
		).rejects.toBe(dup);

		expect(ws.lastError).not.toBeNull();
		expect(ws.lastError?.action).toBe("create-portfolio");
		expect(ws.lastError?.message).toContain("already exists");
	});

	test("rethrows ServerError so the dialog can render backend message", async () => {
		const ws = makeWorkspace();
		const sv = new ServerError("Calibration profile is locked.", 423);
		apiPostMock.mockRejectedValueOnce(sv);

		await expect(
			ws.createPortfolio({ display_name: "Locked", profile: "growth" }),
		).rejects.toBe(sv);
		expect(ws.lastError?.message).toContain("locked");
	});

	test("returns the persisted ModelPortfolio on 2xx", async () => {
		const ws = makeWorkspace();
		const created = {
			id: "00000000-0000-0000-0000-000000000001",
			profile: "growth",
			display_name: "Fresh",
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
		};
		apiPostMock.mockResolvedValueOnce(created);

		const result = await ws.createPortfolio({
			display_name: "Fresh",
			profile: "growth",
		});

		expect(result).toEqual(created);
		expect(ws.lastError).toBeNull();
	});
});
