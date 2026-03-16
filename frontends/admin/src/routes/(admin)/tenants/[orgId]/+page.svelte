<!--
  Tenant detail — tabs for Overview, Configuration, Assets, Usage.
  Logo upload with drag-and-drop + preview.
-->
<script lang="ts">
	import { PageHeader, Tabs, Button, DataCard, Badge, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";

	let { data }: { data: PageData } = $props();
	let activeTab = $state("overview");
	let uploading = $state(false);
	let seeding = $state(false);

	const tabs = [
		{ id: "overview", label: "Overview" },
		{ id: "config", label: "Configuration" },
		{ id: "assets", label: "Assets" },
	];

	async function handleLogoUpload(event: Event, assetType: string) {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;

		uploading = true;
		try {
			const api = createClientApiClient(async () => data.token);
			const formData = new FormData();
			formData.append("file", file);
			await api.postForm(`/admin/tenants/${data.orgId}/assets?asset_type=${assetType}`, formData);
			await invalidateAll();
		} catch (e) {
			console.error("Upload failed:", e);
		} finally {
			uploading = false;
		}
	}

	async function handleReseed() {
		seeding = true;
		try {
			const api = createClientApiClient(async () => data.token);
			await api.post(`/admin/tenants/${data.orgId}/seed`, {});
			await invalidateAll();
		} catch (e) {
			console.error("Seed failed:", e);
		} finally {
			seeding = false;
		}
	}
</script>

<PageHeader title={data.tenant?.name ?? data.orgId}>
	{#snippet actions()}
		<Button variant="outline" onclick={handleReseed} disabled={seeding}>
			{seeding ? "Seeding..." : "Re-seed Configs"}
		</Button>
	{/snippet}
</PageHeader>

<div class="p-6">
	<Tabs items={tabs} bind:active={activeTab}>
		{#snippet content(tab)}
			{#if tab === "overview"}
				<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
					<DataCard label="Organization ID" value={data.orgId} />
					<DataCard label="Configs" value={String(data.tenant?.configs?.length ?? 0)} />
					<DataCard label="Assets" value={String(data.assets?.length ?? 0)} />
				</div>

				{#if data.tenant?.configs?.length}
					<h3 class="mb-2 mt-6 text-sm font-semibold text-[var(--netz-text-secondary)]">Config Overrides</h3>
					<div class="rounded border border-[var(--netz-border)]">
						<table class="w-full text-sm">
							<thead class="bg-[var(--netz-surface-alt)]">
								<tr>
									<th class="px-4 py-2 text-left font-medium">Vertical</th>
									<th class="px-4 py-2 text-left font-medium">Config Type</th>
									<th class="px-4 py-2 text-left font-medium">Version</th>
								</tr>
							</thead>
							<tbody>
								{#each data.tenant.configs as config}
									<tr class="border-t border-[var(--netz-border)]">
										<td class="px-4 py-2">{config.vertical}</td>
										<td class="px-4 py-2">
											<a href="/config/{config.vertical}/{config.config_type}" class="text-[var(--netz-primary)] hover:underline">
												{config.config_type}
											</a>
										</td>
										<td class="px-4 py-2">v{config.version}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}

			{:else if tab === "config"}
				{#if data.tenant?.configs?.length}
					<div class="space-y-2">
						{#each data.tenant.configs as config}
							<a
								href="/config/{config.vertical}/{config.config_type}"
								class="block rounded-md border border-[var(--netz-border)] p-3 hover:bg-[var(--netz-surface-alt)]"
							>
								<span class="font-medium">{config.vertical}</span> /
								<span>{config.config_type}</span>
								<Badge variant="outline" class="ml-2">v{config.version}</Badge>
							</a>
						{/each}
					</div>
				{:else}
					<EmptyState message="No config overrides" description="This tenant uses all default configs." />
				{/if}

			{:else if tab === "assets"}
				<div class="grid grid-cols-1 gap-6 sm:grid-cols-3">
					{#each ["logo_light", "logo_dark", "favicon"] as assetType}
						{@const existing = data.assets?.find((a: {asset_type: string}) => a.asset_type === assetType)}
						<div class="rounded-md border border-[var(--netz-border)] p-4">
							<h4 class="mb-2 text-sm font-medium capitalize">{assetType.replace("_", " ")}</h4>
							{#if existing}
								<div class="mb-2 flex h-16 items-center justify-center rounded bg-[var(--netz-surface-alt)]">
									<img
										src={`/api/v1/assets/tenant/${data.orgId}/${assetType}`}
										alt={assetType}
										class="max-h-14"
									/>
								</div>
								<p class="text-xs text-[var(--netz-text-muted)]">{existing.content_type}</p>
							{:else}
								<div class="mb-2 flex h-16 items-center justify-center rounded bg-[var(--netz-surface-alt)]">
									<span class="text-xs text-[var(--netz-text-muted)]">No asset</span>
								</div>
							{/if}
							<label class="mt-2 block">
								<input
									type="file"
									accept="image/png,image/jpeg,image/x-icon"
									onchange={(e) => handleLogoUpload(e, assetType)}
									class="block w-full text-xs file:mr-2 file:rounded file:border-0 file:bg-[var(--netz-primary)] file:px-3 file:py-1 file:text-sm file:text-white"
									disabled={uploading}
								/>
							</label>
						</div>
					{/each}
				</div>
			{/if}
		{/snippet}
	</Tabs>
</div>
