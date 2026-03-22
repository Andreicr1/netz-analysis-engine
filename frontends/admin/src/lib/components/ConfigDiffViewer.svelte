<!--
  Config Diff Viewer — side-by-side default vs override with highlighted changes.
-->
<script lang="ts">
	import { SectionCard } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";

	let {
		vertical,
		configType,
		token,
		orgId,
	}: {
		vertical: string;
		configType: string;
		token: string;
		orgId: string;
	} = $props();

	let diff = $state<{
		default: Record<string, unknown>;
		override: Record<string, unknown> | null;
		merged: Record<string, unknown>;
		changed_keys: string[];
	} | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function loadDiff() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(() => Promise.resolve(token));
			diff = await api.get(`/admin/configs/${vertical}/${configType}/diff`, {
				org_id: orgId,
			});
		} catch (e: any) {
			error = e.message ?? "Failed to load diff";
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void loadDiff();
	});
</script>

<SectionCard title="Diff: {configType}">
	{#if loading}
		<p class="text-sm text-(--netz-text-muted)">Loading diff...</p>
	{:else if error}
		<p class="text-sm text-(--netz-danger)">{error}</p>
	{:else if diff}
		<div class="grid grid-cols-2 gap-4">
			<!-- Default (left) -->
			<div>
				<p class="mb-2 text-xs font-medium text-(--netz-text-muted)">Default</p>
				<pre
					class="max-h-96 overflow-auto rounded border border-(--netz-border) bg-(--netz-surface) p-3 font-mono text-xs text-(--netz-text-secondary)"
				>{JSON.stringify(diff.default, null, 2)}</pre>
			</div>
			<!-- Override (right) -->
			<div>
				<p class="mb-2 text-xs font-medium text-(--netz-text-muted)">
					{diff.override ? "Override" : "No Override"}
				</p>
				{#if diff.override}
					<pre
						class="max-h-96 overflow-auto rounded border border-(--netz-border) bg-(--netz-surface) p-3 font-mono text-xs text-(--netz-text-primary)"
					>{JSON.stringify(diff.override, null, 2)}</pre>
				{:else}
					<p class="text-sm text-(--netz-text-muted)">Using default values.</p>
				{/if}
			</div>
		</div>
		{#if diff.changed_keys.length > 0}
			<div class="mt-3">
				<p class="text-xs text-(--netz-text-muted)">Changed keys:</p>
				<div class="mt-1 flex flex-wrap gap-1">
					{#each diff.changed_keys as key (key)}
						<span
							class="rounded bg-(--netz-brand-highlight)/20 px-2 py-0.5 text-xs text-(--netz-text-primary)"
						>
							{key}
						</span>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
</SectionCard>
