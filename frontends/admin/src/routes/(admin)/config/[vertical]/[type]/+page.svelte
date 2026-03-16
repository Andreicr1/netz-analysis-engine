<!--
  Config editor — JSON editor with diff view, guardrail validation, optimistic lock.
-->
<script lang="ts">
	import { PageHeader, Button, Tabs, Badge } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";

	let { data }: { data: PageData } = $props();

	interface ConfigDiff {
		default: Record<string, unknown>;
		override: Record<string, unknown>;
		merged: Record<string, unknown>;
		override_version: number | null;
	}

	let diff = $state(data.diff as ConfigDiff);
	let editJson = $state(JSON.stringify(diff.override || {}, null, 2));
	let saving = $state(false);
	let saveError = $state<string | null>(null);
	let activeTab = $state("editor");

	const tabs = [
		{ id: "editor", label: "Editor" },
		{ id: "diff", label: "Diff View" },
		{ id: "merged", label: "Merged Preview" },
	];

	async function handleSave() {
		saving = true;
		saveError = null;
		try {
			const parsed = JSON.parse(editJson);
			const api = createClientApiClient(async () => data.token);
			await api.post("/admin/configs", {
				vertical: data.vertical,
				config_type: data.configType,
				config: parsed,
				expected_version: diff.override_version,
			});
			await invalidateAll();
		} catch (e: unknown) {
			if (e && typeof e === "object" && "status" in e) {
				const err = e as { status: number; message?: string };
				if (err.status === 409) {
					saveError = "Config was modified by another user. Please refresh and try again.";
				} else if (err.status === 422) {
					saveError = "Validation failed. Check config values against guardrails.";
				} else {
					saveError = err.message ?? "Failed to save config";
				}
			} else {
				saveError = "Invalid JSON";
			}
		} finally {
			saving = false;
		}
	}

	async function handleDelete() {
		if (!confirm("Remove config override? This will revert to defaults.")) return;
		try {
			const api = createClientApiClient(async () => data.token);
			await api.delete(`/admin/configs/${data.vertical}/${data.configType}`);
			await invalidateAll();
		} catch (e) {
			console.error("Delete failed:", e);
		}
	}
</script>

<PageHeader title="{data.vertical} / {data.configType}">
	{#snippet actions()}
		<div class="flex items-center gap-2">
			{#if diff.override_version}
				<Badge variant="default">Override v{diff.override_version}</Badge>
				<Button variant="outline" size="sm" onclick={handleDelete}>Remove Override</Button>
			{:else}
				<Badge variant="outline">Using Default</Badge>
			{/if}
			<Button onclick={handleSave} disabled={saving}>
				{saving ? "Saving..." : "Save Override"}
			</Button>
		</div>
	{/snippet}
</PageHeader>

<div class="p-6">
	{#if saveError}
		<div class="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
			{saveError}
		</div>
	{/if}

	<Tabs items={tabs} bind:active={activeTab}>
		{#snippet content(tab)}
			{#if tab === "editor"}
				<div class="mt-4">
					<label class="mb-1 block text-sm font-medium text-[var(--netz-text-secondary)]">
						Config Override (JSON)
					</label>
					<textarea
						bind:value={editJson}
						class="h-96 w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3 font-mono text-sm focus:border-[var(--netz-primary)] focus:outline-none"
						spellcheck="false"
					></textarea>
				</div>

			{:else if tab === "diff"}
				<div class="mt-4 grid grid-cols-2 gap-4">
					<div>
						<h3 class="mb-2 text-sm font-semibold text-[var(--netz-text-secondary)]">Default</h3>
						<pre class="max-h-96 overflow-auto rounded-md bg-[var(--netz-surface-alt)] p-3 text-xs">{JSON.stringify(diff.default, null, 2)}</pre>
					</div>
					<div>
						<h3 class="mb-2 text-sm font-semibold text-[var(--netz-text-secondary)]">Override</h3>
						<pre class="max-h-96 overflow-auto rounded-md bg-[var(--netz-surface-alt)] p-3 text-xs">{JSON.stringify(diff.override, null, 2)}</pre>
					</div>
				</div>

			{:else if tab === "merged"}
				<div class="mt-4">
					<h3 class="mb-2 text-sm font-semibold text-[var(--netz-text-secondary)]">Merged Result (Default + Override)</h3>
					<pre class="max-h-96 overflow-auto rounded-md bg-[var(--netz-surface-alt)] p-3 text-xs">{JSON.stringify(diff.merged, null, 2)}</pre>
				</div>
			{/if}
		{/snippet}
	</Tabs>
</div>
