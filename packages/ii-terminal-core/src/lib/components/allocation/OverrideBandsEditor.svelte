<!--
  PR-A26.3 Section F — Override bands editor modal.

  Validation: at least one of min/max when saving; min <= max when
  both given; rationale required (min 10 chars) when setting bounds.
  Clear Override bypasses rationale and posts both-NULL.

  PR-4b — terminal-density re-skin. Modal shell + inputs + actions
  consume --terminal-* tokens. No Tailwind semantic colors.
-->
<script lang="ts">
	import { formatNumber, formatPercent } from "@investintell/ui";
	import type {
		AllocationProfile,
		SetOverrideRequest,
		StrategicAllocationBlock,
	} from "$wealth/types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		block: StrategicAllocationBlock;
		onClose: () => void;
		onSaved: () => Promise<void> | void;
		apiPost: <T>(path: string, body: unknown) => Promise<T>;
	}
	let { profile, block, onClose, onSaved, apiPost }: Props = $props();

	function toPctString(v: number | null): string {
		return v !== null ? formatNumber(v * 100, 2, "en-US") : "";
	}

	let overrideMinRaw = $state("");
	let overrideMaxRaw = $state("");

	$effect(() => {
		overrideMinRaw = toPctString(block.override_min);
		overrideMaxRaw = toPctString(block.override_max);
	});
	let rationale = $state("");
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);

	function parseOrNull(raw: string): number | null {
		const trimmed = raw.trim();
		if (trimmed === "") return null;
		const n = Number(trimmed);
		if (!Number.isFinite(n)) return null;
		return n / 100;
	}

	async function save(): Promise<void> {
		errorMsg = null;
		const min = parseOrNull(overrideMinRaw);
		const max = parseOrNull(overrideMaxRaw);
		if (min === null && max === null) {
			errorMsg =
				"Provide at least one bound or use Clear Override to remove the override.";
			return;
		}
		if (min !== null && (min < 0 || min > 1)) {
			errorMsg = "Override min must be between 0 and 100%.";
			return;
		}
		if (max !== null && (max < 0 || max > 1)) {
			errorMsg = "Override max must be between 0 and 100%.";
			return;
		}
		if (min !== null && max !== null && min > max) {
			errorMsg = "Override min must be less than or equal to override max.";
			return;
		}
		if (rationale.trim().length < 10) {
			errorMsg = "Rationale must be at least 10 characters.";
			return;
		}

		saving = true;
		try {
			const body: SetOverrideRequest = {
				block_id: block.block_id,
				override_min: min,
				override_max: max,
				rationale: rationale.trim(),
			};
			await apiPost(`/portfolio/profiles/${profile}/set-override`, body);
			await onSaved();
			onClose();
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : "Save failed";
		} finally {
			saving = false;
		}
	}

	async function clear(): Promise<void> {
		errorMsg = null;
		saving = true;
		try {
			const body: SetOverrideRequest = {
				block_id: block.block_id,
				override_min: null,
				override_max: null,
				rationale: rationale.trim() || "Override cleared",
			};
			await apiPost(`/portfolio/profiles/${profile}/set-override`, body);
			await onSaved();
			onClose();
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : "Clear failed";
		} finally {
			saving = false;
		}
	}
</script>

<div
	class="modal-backdrop"
	role="dialog"
	aria-modal="true"
	aria-labelledby="override-editor-title"
>
	<div class="modal">
		<header class="modal__header">
			<h3 id="override-editor-title" class="modal__title">
				Edit Override — {block.block_name}
			</h3>
			<p class="modal__subtitle">
				Current target: {block.target_weight !== null
					? formatPercent(block.target_weight)
					: "—"}. Override takes effect on next proposal. Current holdings are
				unaffected.
			</p>
		</header>

		<div class="modal__fields">
			<label class="field">
				<span class="field__label">Override Min (%)</span>
				<input
					type="number"
					min="0"
					max="100"
					step="0.1"
					class="field__input"
					bind:value={overrideMinRaw}
					placeholder="e.g. 5"
				/>
			</label>
			<label class="field">
				<span class="field__label">Override Max (%)</span>
				<input
					type="number"
					min="0"
					max="100"
					step="0.1"
					class="field__input"
					bind:value={overrideMaxRaw}
					placeholder="e.g. 15"
				/>
			</label>
			<label class="field">
				<span class="field__label">Rationale (min 10 chars)</span>
				<textarea
					rows="3"
					class="field__textarea"
					bind:value={rationale}
					placeholder="Why is this override needed?"
				></textarea>
			</label>
		</div>

		{#if errorMsg}
			<p class="modal__error">{errorMsg}</p>
		{/if}

		<footer class="modal__footer">
			<button
				type="button"
				class="action action--destructive-ghost"
				onclick={() => void clear()}
				disabled={saving}
			>
				Clear Override
			</button>
			<div class="modal__footer-right">
				<button
					type="button"
					class="action action--ghost"
					onclick={onClose}
					disabled={saving}
				>
					Cancel
				</button>
				<button
					type="button"
					class="action action--primary"
					onclick={() => void save()}
					disabled={saving}
				>
					{saving ? "Saving…" : "Save Override"}
				</button>
			</div>
		</footer>
	</div>
</div>

<style>
	.modal-backdrop {
		position: fixed;
		inset: 0;
		z-index: var(--terminal-z-modal);
		background: var(--terminal-bg-scrim);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--terminal-space-4);
	}
	.modal {
		width: 100%;
		max-width: 480px;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		padding: var(--terminal-space-4);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}
	.modal__header {
		margin-bottom: var(--terminal-space-3);
	}
	.modal__title {
		font-size: var(--terminal-text-14);
		font-weight: 500;
		margin: 0;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-primary);
	}
	.modal__subtitle {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		margin: var(--terminal-space-1) 0 0;
		line-height: var(--terminal-leading-snug);
	}

	.modal__fields {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}
	.field__label {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.field__input,
	.field__textarea {
		width: 100%;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		background: var(--terminal-bg-panel-sunken);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-12);
		font-variant-numeric: tabular-nums;
	}
	.field__input:focus-visible,
	.field__textarea:focus-visible {
		outline: none;
		border-color: var(--terminal-accent-amber);
	}
	.field__textarea {
		resize: vertical;
		min-height: 72px;
	}

	.modal__error {
		margin-top: var(--terminal-space-3);
		font-size: var(--terminal-text-10);
		color: var(--terminal-status-error);
	}

	.modal__footer {
		margin-top: var(--terminal-space-4);
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--terminal-space-2);
	}
	.modal__footer-right {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.action {
		display: inline-flex;
		align-items: center;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		background: transparent;
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		transition: color var(--terminal-motion-tick)
				var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.action:disabled {
		color: var(--terminal-fg-disabled);
		border-color: var(--terminal-fg-disabled);
		cursor: not-allowed;
	}
	.action--ghost {
		color: var(--terminal-fg-tertiary);
	}
	.action--ghost:hover:not(:disabled),
	.action--ghost:focus-visible:not(:disabled) {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
		outline: none;
	}
	.action--primary {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}
	.action--primary:hover:not(:disabled),
	.action--primary:focus-visible:not(:disabled) {
		background: var(--terminal-bg-panel-sunken);
		outline: none;
	}
	.action--destructive-ghost {
		color: var(--terminal-status-error);
		border-color: transparent;
	}
	.action--destructive-ghost:hover:not(:disabled),
	.action--destructive-ghost:focus-visible:not(:disabled) {
		border-color: var(--terminal-status-error);
		outline: none;
	}
</style>
