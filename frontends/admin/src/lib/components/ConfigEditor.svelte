<!--
  Config Editor — JSON textarea with validation and save.
  MVP: textarea instead of CodeMirror (added later).
-->
<script lang="ts">
	import { SectionCard } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";

	let {
		vertical,
		configType,
		token,
	}: {
		vertical: string;
		configType: string;
		token: string;
	} = $props();

	let content = $state("{}");
	let version = $state(0);
	let isDefault = $state(true);
	let jsonError = $state<string | null>(null);
	let saveError = $state<string | null>(null);
	let saving = $state(false);
	let loading = $state(true);

	async function loadConfig() {
		loading = true;
		try {
			const api = createClientApiClient(() => Promise.resolve(token));
			const result = await api.get<{
				config: Record<string, unknown>;
				vertical: string;
				config_type: string;
			}>(`/admin/configs/${vertical}/${configType}`);
			content = JSON.stringify(result.config, null, 2);
			version = 0; // Will be set from override if exists
			isDefault = true;
		} catch (e) {
			saveError = "Failed to load config";
		} finally {
			loading = false;
		}
	}

	function validateJson(value: string) {
		try {
			JSON.parse(value);
			jsonError = null;
		} catch (e) {
			jsonError = "Invalid JSON";
		}
		content = value;
	}

	async function save() {
		if (jsonError) return;
		saving = true;
		saveError = null;
		try {
			const api = createClientApiClient(() => Promise.resolve(token));
			const parsed = JSON.parse(content);
			await api.post(`/admin/configs/validate`, parsed);
		} catch (e: any) {
			saveError = e.message ?? "Save failed";
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		void loadConfig();
	});

	const jsonValid = $derived(jsonError === null);
</script>

<SectionCard title="{configType} — {isDefault ? 'Default (read-only)' : 'Override'}">
	{#if loading}
		<p class="text-sm text-[var(--netz-text-muted)]">Loading...</p>
	{:else}
		<div class="space-y-3">
			<div class="flex items-center gap-2">
				<span
					class="h-2 w-2 rounded-full {jsonValid ? 'bg-green-500' : 'bg-red-500'}"
				></span>
				<span class="text-xs text-[var(--netz-text-muted)]">
					{jsonValid ? "Valid JSON" : jsonError}
				</span>
			</div>

			<textarea
				value={content}
				oninput={(e) => validateJson(e.currentTarget.value)}
				rows={20}
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3 font-mono text-xs text-[var(--netz-text-primary)] focus:border-[var(--netz-brand-primary)] focus:outline-none"
				spellcheck="false"
			></textarea>

			{#if saveError}
				<p class="text-xs text-red-500">{saveError}</p>
			{/if}

			<div class="flex justify-end gap-2">
				<button
					onclick={() => loadConfig()}
					class="rounded-md border border-[var(--netz-border)] px-4 py-2 text-sm text-[var(--netz-text-primary)] hover:bg-[var(--netz-surface-alt)]"
				>
					Reset
				</button>
				<button
					onclick={save}
					disabled={!jsonValid || saving}
					class="rounded-md bg-[var(--netz-brand-primary)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-50"
				>
					{saving ? "Saving..." : "Validate & Save"}
				</button>
			</div>
		</div>
	{/if}
</SectionCard>
