<!--
  NewPortfolioDialog — Phase 5 Task 5.1 of the portfolio-enterprise-workbench
  plan. Closes the "+Portfolio" button no-op flagged by Phase 0 Task 0.1
  Step 2 (the legacy ``<button class="bld-pill bld-pill--new">`` had no
  onclick handler).

  Form fields per the plan + memory ``feedback_smart_backend_dumb_frontend``:
    - Name (required) — display_name on the backend
    - Mandate (required) — backend ``profile`` column. Conservative /
      Moderate / Balanced / Aggressive (matches CalibrationPanel).
    - Description (optional) — free-form notes
    - Copy from existing (optional) — clones calibration + composition
      from an existing portfolio so PMs can fork an institutional model
      without re-doing the 63-input calibration setup.

  On success the dialog routes to ``/portfolio?portfolio={new_id}`` so
  the new draft is selected on the Builder. The Phase 1 + Phase 5 backend
  guarantees the response carries ``allowed_actions=["construct","archive"]``.

  Per CLAUDE.md Stability Guardrails charter §3 — DL15 (no localStorage),
  DL16 (formatters via @investintell/ui), DL17 (no @tanstack/svelte-table).
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import {
		Dialog,
		Button,
		FormField,
		Input,
		Select,
	} from "@investintell/ui";
	import type { ModelPortfolio } from "$wealth/types/model-portfolio";
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";

	interface Props {
		open: boolean;
		onOpenChange: (open: boolean) => void;
		/** Optional pre-loaded portfolio list for the "Copy from" select. */
		portfolios?: readonly ModelPortfolio[];
	}

	let { open, onOpenChange, portfolios = [] }: Props = $props();

	// ── Form state ───────────────────────────────────────────────
	let name = $state("");
	let mandate = $state<"conservative" | "moderate" | "balanced" | "aggressive">("moderate");
	let description = $state("");
	let copyFrom = $state<string>(""); // empty string means "no clone"

	let isSubmitting = $state(false);
	let submitError = $state<string | null>(null);

	const MANDATE_OPTIONS: { value: string; label: string }[] = [
		{ value: "conservative", label: "Conservative" },
		{ value: "moderate", label: "Moderate" },
		{ value: "balanced", label: "Balanced" },
		{ value: "aggressive", label: "Aggressive" },
	];

	const copyFromOptions = $derived.by(() => {
		const baseline = [{ value: "", label: "— start fresh —" }];
		const sources = portfolios.map((p) => ({
			value: p.id,
			label: p.display_name,
		}));
		return [...baseline, ...sources];
	});

	const canSubmit = $derived(name.trim().length > 0 && !isSubmitting);

	function reset() {
		name = "";
		mandate = "moderate";
		description = "";
		copyFrom = "";
		submitError = null;
		isSubmitting = false;
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
			const created = await workspace.createPortfolio(payload);
			if (!created) {
				submitError = workspace.lastError?.message ?? "Failed to create portfolio";
				isSubmitting = false;
				return;
			}
			// Close + reset before navigation so the dialog isn't visible
			// when the new draft loads in the Builder.
			onOpenChange(false);
			reset();
			await goto(`/portfolio?portfolio=${created.id}`);
		} catch (err) {
			submitError = err instanceof Error ? err.message : "Failed to create portfolio";
			isSubmitting = false;
		}
	}

	function handleCancel() {
		if (isSubmitting) return;
		onOpenChange(false);
		reset();
	}
</script>

<Dialog {open} {onOpenChange} title="New Portfolio">
	<form class="npd-form" onsubmit={handleSubmit}>
		<FormField label="Name" required>
			<Input
				type="text"
				placeholder="e.g. Institutional Balanced 60/40"
				bind:value={name}
				maxlength={120}
				disabled={isSubmitting}
				required
			/>
		</FormField>

		<FormField label="Mandate" required>
			<Select bind:value={mandate} options={MANDATE_OPTIONS} disabled={isSubmitting} />
		</FormField>

		<FormField label="Description">
			<Input
				type="text"
				placeholder="Optional — investment thesis or mandate notes"
				bind:value={description}
				maxlength={500}
				disabled={isSubmitting}
			/>
		</FormField>

		<FormField label="Copy from existing">
			<Select bind:value={copyFrom} options={copyFromOptions} disabled={isSubmitting} />
		</FormField>

		{#if submitError}
			<p class="npd-error" role="alert">{submitError}</p>
		{/if}

		<footer class="npd-footer">
			<Button variant="ghost" type="button" onclick={handleCancel} disabled={isSubmitting}>
				Cancel
			</Button>
			<Button variant="default" type="submit" disabled={!canSubmit}>
				{isSubmitting ? "Creating…" : "Create Portfolio"}
			</Button>
		</footer>
	</form>
</Dialog>

<style>
	.npd-form {
		display: flex;
		flex-direction: column;
		gap: 16px;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.npd-error {
		margin: 0;
		padding: 8px 12px;
		background: rgba(252, 26, 26, 0.08);
		border: 1px solid rgba(252, 26, 26, 0.32);
		border-radius: 6px;
		color: var(--ii-danger, #fc1a1a);
		font-size: 12px;
		font-weight: 600;
	}

	.npd-footer {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding-top: 8px;
		border-top: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
</style>
