<!--
  Config Editor — JSON textarea with validation, save (PUT), delete, update default.
-->
<script lang="ts">
	import { SectionCard, ActionButton, ConfirmDialog, Button } from "@netz/ui";
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
		orgId?: string;
	} = $props();

	let content = $state("{}");
	let version = $state(0);
	let isDefault = $state(true);
	let jsonError = $state<string | null>(null);
	let saveError = $state<string | null>(null);
	let saveMessage = $state<string | null>(null);
	let saving = $state(false);
	let loading = $state(true);
	let showDeleteConfirm = $state(false);
	let showDefaultConfirm = $state(false);

	const api = createClientApiClient(() => Promise.resolve(token));

	async function loadConfig() {
		loading = true;
		saveError = null;
		saveMessage = null;
		try {
			const params = orgId ? `?org_id=${orgId}` : "";
			const result = await api.get<{
				config: Record<string, unknown>;
				vertical: string;
				config_type: string;
				version?: number;
				is_default?: boolean;
			}>(`/admin/configs/${vertical}/${configType}${params}`);
			content = JSON.stringify(result.config, null, 2);
			version = result.version ?? 0;
			isDefault = result.is_default ?? true;
			jsonError = null;
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
		} catch {
			jsonError = "Invalid JSON";
		}
		content = value;
	}

	async function save() {
		if (jsonError || !orgId) return;
		saving = true;
		saveError = null;
		saveMessage = null;
		try {
			const parsed = JSON.parse(content);
			await api.put(
				`/admin/configs/${vertical}/${configType}?org_id=${orgId}`,
				parsed,
				{ "If-Match": String(version) },
			);
			saveMessage = "Saved successfully";
			setTimeout(() => (saveMessage = null), 3000);
			await loadConfig(); // Reload to get new version
		} catch (e: unknown) {
			if (e instanceof Error) {
				if (e.message.includes("409") || e.message.includes("modified")) {
					saveError = "Config was modified by another user. Reloading...";
					setTimeout(() => loadConfig(), 1500);
				} else if (e.message.includes("428")) {
					saveError = "Please reload to get current version";
				} else {
					saveError = e.message;
				}
			} else {
				saveError = "Save failed";
			}
		} finally {
			saving = false;
		}
	}

	async function deleteOverride() {
		if (!orgId) return;
		try {
			await api.delete(`/admin/configs/${vertical}/${configType}?org_id=${orgId}`);
			saveMessage = "Override deleted — reverted to default";
			setTimeout(() => (saveMessage = null), 3000);
			await loadConfig();
		} catch (e) {
			saveError = e instanceof Error ? e.message : "Delete failed";
		}
	}

	async function updateDefault() {
		if (jsonError) return;
		try {
			const parsed = JSON.parse(content);
			await api.put(`/admin/configs/defaults/${vertical}/${configType}`, parsed);
			saveMessage = "Default updated";
			setTimeout(() => (saveMessage = null), 3000);
		} catch (e) {
			saveError = e instanceof Error ? e.message : "Update default failed";
		}
	}

	$effect(() => {
		const _v = vertical;
		const _c = configType;
		void loadConfig();
	});

	const jsonValid = $derived(jsonError === null);
</script>

<SectionCard title="{configType} — {isDefault ? 'Default' : `Override (v${version})`}">
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
				<p class="text-xs text-[var(--netz-danger)]">{saveError}</p>
			{/if}
			{#if saveMessage}
				<p class="text-xs text-[var(--netz-brand-primary)]">{saveMessage}</p>
			{/if}

			<div class="flex items-center justify-between">
				<div class="flex gap-2">
					{#if !isDefault}
						<Button variant="destructive" size="sm" onclick={() => (showDeleteConfirm = true)}>
							Revert to Default
						</Button>
					{/if}
					<Button variant="ghost" size="sm" onclick={() => (showDefaultConfirm = true)} disabled={!jsonValid}>
						Update Default
					</Button>
				</div>
				<div class="flex gap-2">
					<Button variant="outline" onclick={() => loadConfig()}>
						Reset
					</Button>
					{#if orgId}
						<ActionButton onclick={save} loading={saving} loadingText="Saving..." disabled={!jsonValid}>
							Save Override
						</ActionButton>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</SectionCard>

<ConfirmDialog
	bind:open={showDeleteConfirm}
	title="Revert to Default"
	message="This will delete the config override and revert to the global default. Continue?"
	confirmLabel="Revert"
	confirmVariant="destructive"
	onConfirm={deleteOverride}
/>

<ConfirmDialog
	bind:open={showDefaultConfirm}
	title="Update Global Default"
	message="This will update the global default config for all tenants without overrides. This is a high-impact action."
	confirmLabel="Update Default"
	confirmVariant="destructive"
	onConfirm={updateDefault}
/>
