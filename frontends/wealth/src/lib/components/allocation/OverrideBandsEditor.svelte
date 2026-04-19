<!--
  PR-A26.3 Section F — Override bands editor modal.

  Validation: at least one of min/max when saving; min <= max when
  both given; rationale required (min 10 chars) when setting bounds.
  Clear Override bypasses rationale and posts both-NULL.
-->
<script lang="ts">
	import { formatNumber, formatPercent } from "@investintell/ui";
	import type {
		AllocationProfile,
		SetOverrideRequest,
		StrategicAllocationBlock,
	} from "$lib/types/allocation-page";

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
	class="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
	role="dialog"
	aria-modal="true"
	aria-labelledby="override-editor-title"
>
	<div class="w-full max-w-md rounded-lg bg-card border border-border p-5">
		<header class="mb-3">
			<h3
				id="override-editor-title"
				class="text-base font-medium text-foreground"
			>
				Edit Override — {block.block_name}
			</h3>
			<p class="text-xs text-muted-foreground mt-1">
				Current target: {block.target_weight !== null
					? formatPercent(block.target_weight)
					: "—"}. Override takes effect on next proposal. Current holdings
				are unaffected.
			</p>
		</header>

		<div class="space-y-3">
			<label class="block">
				<span class="text-xs uppercase tracking-wide text-muted-foreground">
					Override Min (%)
				</span>
				<input
					type="number"
					min="0"
					max="100"
					step="0.1"
					class="mt-1 w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground"
					bind:value={overrideMinRaw}
					placeholder="e.g. 5"
				/>
			</label>
			<label class="block">
				<span class="text-xs uppercase tracking-wide text-muted-foreground">
					Override Max (%)
				</span>
				<input
					type="number"
					min="0"
					max="100"
					step="0.1"
					class="mt-1 w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground"
					bind:value={overrideMaxRaw}
					placeholder="e.g. 15"
				/>
			</label>
			<label class="block">
				<span class="text-xs uppercase tracking-wide text-muted-foreground">
					Rationale (min 10 chars)
				</span>
				<textarea
					rows="3"
					class="mt-1 w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground"
					bind:value={rationale}
					placeholder="Why is this override needed?"
				></textarea>
			</label>
		</div>

		{#if errorMsg}
			<p class="mt-3 text-xs text-destructive">{errorMsg}</p>
		{/if}

		<footer class="mt-4 flex items-center justify-between gap-2">
			<button
				type="button"
				class="px-3 py-1.5 rounded-md text-xs text-destructive hover:bg-destructive/10"
				onclick={() => void clear()}
				disabled={saving}
			>
				Clear Override
			</button>
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="px-3 py-1.5 rounded-md text-sm text-muted-foreground hover:text-foreground"
					onclick={onClose}
					disabled={saving}
				>
					Cancel
				</button>
				<button
					type="button"
					class="px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
					onclick={() => void save()}
					disabled={saving}
				>
					{saving ? "Saving…" : "Save Override"}
				</button>
			</div>
		</footer>
	</div>
</div>
