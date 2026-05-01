<!--
  NewPortfolioDialog — institutional portfolio creation dialog.

  Canonical port of the wealth `NewPortfolioDialog.svelte` into the
  terminal-core package per PR-UX-4 of the builder workspace redesign
  (`docs/plans/2026-04-30-builder-workspace-redesign-final.md`,
  §3.2 / §6.2.3 / §6.4 Option A / §7.4 / §9). Replaces the
  pre-PR-UX-4 stub `createPortfolioFromEmptyState` placeholder on
  the terminal allocation page.

  Form fields (post-Q165 reread):
    - `display_name` (required, maxlength 120) — UNIQUE per org
      (PR-BE-4 will tighten the constraint; this dialog already
      handles 409 with a structured `error: "duplicate_display_name"`
      payload by rendering an inline error and keeping the dialog open).
    - `description` (optional, maxlength 500).
    - `copy_from` (optional) — clones calibration + composition from
      an existing same-profile portfolio. The select is filtered to
      the active builder `profile`; cross-profile clones are not
      offered here (use the wealth surface for forks across mandates).

  Mandate dropdown:
    - Slugs: `{conservative, moderate, growth}` — the canonical
      3-profile taxonomy enforced by the terminal allocation route
      validation (`frontends/terminal/src/routes/allocation/[profile]/+page.server.ts`)
      and `ALLOCATION_PROFILES` in `types/allocation-page.ts`. A 4th
      `balanced` slug was carried over from the legacy wealth dialog
      and removed in PR-UX-4 remediation: submitting `balanced` would
      have routed `onCreated` to `/allocation/balanced`, which the
      route loader rejects as `Unknown allocation profile`.
    - Display labels flow through the canonical `profileDisplayLabel(
      value, "full")` helper from `quant-labels.ts` (PR-UX-5 /
      PR-BE-7) so `growth` renders as "Dynamic Growth" and never as
      the legacy `aggressive` slug.
    - Defaults to the URL-bound `profile` prop. Institutional users
      may override the mandate (e.g. fork a draft from one profile to
      another) — the active profile context is informational, not a
      hard lock.

  Token discipline:
    - Every visual property routes through `var(--terminal-*)` custom
      properties — mirrors the `pp-create-btn` discipline in
      `PortfolioPicker.svelte` and the `.propose-cta` spec in
      PR-UX-1. No Tailwind utilities, no hardcoded colours.

  Stability Guardrails:
    - P3 Isolated: the form body is wrapped in `<svelte:boundary>` so
      a render error in the option list cannot blank the whole
      Builder workspace tab.
    - Form state is `$state` only. No `localStorage` /
      `sessionStorage` reads or writes (DL15).

  Props are documented in the `Props` interface below. Consumers:
    - frontends/terminal/src/routes/allocation/[profile]/+page.svelte
    - frontends/wealth/src/lib/components/portfolio/NewPortfolioDialog.svelte
      (wealth re-export shim, marked `@deprecated` — see PR-UX-4).
-->
<script lang="ts">
	import {
		Dialog,
		Button,
		FormField,
		Input,
		Select,
	} from "@investintell/ui";
	import { ConflictError } from "@investintell/ui/utils";
	import { profileDisplayLabel } from "../../i18n/quant-labels";
	import type { ModelPortfolio } from "../../types/model-portfolio";

	interface Props {
		/** Whether the dialog is currently open. Two-way controlled. */
		open: boolean;
		/** Invoked when the Dialog wrapper requests an open-state change. */
		onOpenChange: (open: boolean) => void;
		/**
		 * Active builder profile slug — drives the mandate dropdown
		 * default and filters the `copy_from` select to same-profile
		 * portfolios. The dialog inherits the URL profile; the parent
		 * page is the source of truth for which profile is active.
		 */
		profile: string;
		/**
		 * Currently-loaded portfolios for the active org. Used to
		 * populate the `copy_from` select after filtering by profile.
		 * `readonly` to make the contract clear — the dialog never
		 * mutates the parent's list.
		 */
		portfolios: ReadonlyArray<ModelPortfolio>;
		/**
		 * Async creator. Returns the persisted ModelPortfolio on
		 * success; throws on transport / 4xx / 5xx errors. Backed by
		 * `workspace.createPortfolio(payload)` in the parent.
		 */
		create: (
			payload: Record<string, unknown>,
		) => Promise<ModelPortfolio | null>;
		/**
		 * Invoked with the persisted portfolio after a successful
		 * create. Parent uses this to invalidate loader data and
		 * navigate to the new draft (PR-UX-4 §9 — terminal allocation
		 * page wires `invalidateAll()` + goto with `?portfolio_id=…`).
		 */
		onCreated: (portfolio: ModelPortfolio) => void;
	}

	let {
		open,
		onOpenChange,
		profile,
		portfolios,
		create,
		onCreated,
	}: Props = $props();

	// ── Mandate enum + labels ───────────────────────────────────
	// Canonical 3-profile taxonomy — must stay in lockstep with
	// `ALLOCATION_PROFILES` in `types/allocation-page.ts` and the
	// `+page.server.ts` validation in the terminal allocation route.
	// A `balanced` slug was carried over from the legacy wealth
	// dialog and removed in PR-UX-4 remediation (Codex P1): a
	// successful `balanced` submit would route `onCreated` to
	// `/allocation/balanced` which the loader rejects.
	type MandateSlug = "conservative" | "moderate" | "growth";
	const MANDATE_SLUGS: ReadonlyArray<MandateSlug> = [
		"conservative",
		"moderate",
		"growth",
	];

	function defaultMandate(slug: string): MandateSlug {
		// PR-BE-7 collapsed `aggressive` → `growth`. URL profile may
		// arrive as one of the canonical slugs; if the profile is not
		// recognised we fall back to `moderate` (the institutional
		// neutral default, matches wealth source dialog).
		if (slug === "aggressive") return "growth";
		if (MANDATE_SLUGS.includes(slug as MandateSlug)) {
			return slug as MandateSlug;
		}
		return "moderate";
	}

	// ── Form state — `$state` only, never localStorage (DL15) ───
	// `mandate` is seeded with the URL profile via the open-state
	// effect below. Initial value `"moderate"` is a placeholder; it
	// is overwritten before the dialog is shown to the user.
	let name = $state("");
	let mandate = $state<MandateSlug>("moderate");
	let description = $state("");
	let copyFrom = $state<string>(""); // empty string === "no clone"

	let isSubmitting = $state(false);
	let submitError = $state<string | null>(null);

	const MANDATE_OPTIONS = $derived<{ value: string; label: string }[]>(
		MANDATE_SLUGS.map((slug) => ({
			value: slug,
			label: profileDisplayLabel(slug, "full"),
		})),
	);

	/**
	 * `copy_from` select is filtered to the active builder profile.
	 * Cross-profile forks are an explicit institutional decision and
	 * happen via the wealth surface — not surfaced here.
	 */
	const copyFromOptions = $derived.by(() => {
		const baseline = [{ value: "", label: "— start fresh —" }];
		const sources = portfolios
			.filter((p) => p.profile === profile)
			.map((p) => ({ value: p.id, label: p.display_name }));
		return [...baseline, ...sources];
	});

	const canSubmit = $derived(name.trim().length > 0 && !isSubmitting);

	function reset() {
		name = "";
		mandate = defaultMandate(profile);
		description = "";
		copyFrom = "";
		submitError = null;
		isSubmitting = false;
	}

	// Form-state lifecycle effect:
	//   - When the dialog transitions to closed → clear all fields.
	//     Spec: "`onOpenChange(false)` clears form state".
	//   - When the URL profile prop changes while closed → re-seed
	//     mandate with the new default (no stomp on in-flight edits
	//     in an open dialog).
	$effect(() => {
		if (!open) {
			reset();
		}
	});

	// Seed the mandate with the URL profile when the dialog OPENS
	// (one-shot — only when the user has not already edited it).
	// Tracking `open` keeps this effect re-running on each show.
	$effect(() => {
		if (open) {
			mandate = defaultMandate(profile);
		}
	});

	function extractDuplicateMessage(err: unknown): string | null {
		// Backend (post PR-BE-4) returns a structured 409 with
		// `error: "duplicate_display_name"`. The api-client folds the
		// payload into `ConflictError.message` via `parsed.detail`.
		// Until PR-BE-4 lands the dialog falls back to the generic
		// 409 message.
		if (err instanceof ConflictError) {
			return (
				err.message ||
				"A portfolio with this name already exists. Choose a different name."
			);
		}
		return null;
	}

	async function handleSubmit(event: Event) {
		event.preventDefault();
		if (!canSubmit) return;
		isSubmitting = true;
		submitError = null;

		const payload: Record<string, unknown> = {
			profile: mandate,
			display_name: name.trim(),
		};
		if (description.trim().length > 0) {
			payload.description = description.trim();
		}
		if (copyFrom !== "") {
			payload.copy_from = copyFrom;
		}

		try {
			const created = await create(payload);
			if (!created) {
				// Post-Codex-P2: `workspace.createPortfolio` now rethrows
				// every transport / 4xx / 5xx error. The only path that
				// still resolves with `null` is the pre-Clerk guard
				// (`!this._getToken`), which from the user's perspective
				// reads as a session-expired condition. Render a neutral
				// fallback and keep the dialog open so the user can
				// recover after refreshing auth.
				submitError = "Session expired. Please refresh and try again.";
				isSubmitting = false;
				return;
			}
			// Invoke onCreated BEFORE closing — so the parent can wire
			// `invalidateAll()` + navigate before the dialog unmounts.
			onCreated(created);
			onOpenChange(false);
			// reset() runs via the open-state effect.
		} catch (err) {
			const dup = extractDuplicateMessage(err);
			if (dup) {
				submitError = dup;
			} else if (err instanceof Error) {
				submitError = err.message;
			} else {
				submitError = "Failed to create portfolio.";
			}
			isSubmitting = false;
		}
	}

	function handleCancel() {
		if (isSubmitting) return;
		onOpenChange(false);
	}
</script>

<Dialog {open} {onOpenChange} title="New Portfolio">
	<svelte:boundary>
		<form
			class="npd-form"
			onsubmit={handleSubmit}
			data-testid="new-portfolio-dialog"
		>
			<FormField label="Name" required>
				<Input
					type="text"
					placeholder="e.g. Institutional Balanced 60/40"
					bind:value={name}
					maxlength={120}
					disabled={isSubmitting}
					required
					data-testid="npd-name-input"
				/>
			</FormField>

			<FormField label="Mandate" required>
				<div data-testid="npd-mandate-select-wrap">
					<Select
						bind:value={mandate}
						options={MANDATE_OPTIONS}
						disabled={isSubmitting}
					/>
				</div>
			</FormField>

			<FormField label="Description">
				<Input
					type="text"
					placeholder="Optional — investment thesis or mandate notes"
					bind:value={description}
					maxlength={500}
					disabled={isSubmitting}
					data-testid="npd-description-input"
				/>
			</FormField>

			<FormField label="Copy from existing">
				<div data-testid="npd-copy-from-select-wrap">
					<Select
						bind:value={copyFrom}
						options={copyFromOptions}
						disabled={isSubmitting}
					/>
				</div>
			</FormField>

			{#if submitError}
				<p
					class="npd-error"
					role="alert"
					data-testid="npd-submit-error"
				>
					{submitError}
				</p>
			{/if}

			<footer class="npd-footer">
				<Button
					variant="ghost"
					type="button"
					onclick={handleCancel}
					disabled={isSubmitting}
				>
					Cancel
				</Button>
				<Button
					variant="default"
					type="submit"
					disabled={!canSubmit}
					data-testid="npd-submit-btn"
				>
					{isSubmitting ? "Creating…" : "Create Portfolio"}
				</Button>
			</footer>
		</form>
	</svelte:boundary>
</Dialog>

<style>
	/* Terminal-tokenised shell — mirrors `pp-create-btn` discipline
	   in PortfolioPicker and `.propose-cta` from PR-UX-1. */
	.npd-form {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	/* Inline error pill — matches the institutional alert palette
	   already used by `IPSGateNotice` / `PortfolioGateNotice`. */
	.npd-error {
		margin: 0;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		background: color-mix(
			in srgb,
			var(--terminal-status-error) 10%,
			transparent
		);
		border: 1px solid var(--terminal-status-error);
		color: var(--terminal-status-error);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.npd-footer {
		display: flex;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
		padding-top: var(--terminal-space-2);
		border-top: var(--terminal-border-hairline);
	}
</style>
