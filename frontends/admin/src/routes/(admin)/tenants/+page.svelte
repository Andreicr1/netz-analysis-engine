<!--
  Tenant Manager — list all tenants with config/asset counts.
  Create tenant dialog, seed configs, navigate to tenant detail.
-->
<script lang="ts">
	import { DataTable, PageHeader, Button, Badge, EmptyState, Dialog, Input, Select } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";

	let { data }: { data: PageData } = $props();
	let showCreateDialog = $state(false);
	let creating = $state(false);
	let newTenant = $state({ organization_id: "", organization_slug: "", name: "", verticals: ["private_credit", "liquid_funds"] });

	const columns = [
		{ accessorKey: "name", header: "Name" },
		{ accessorKey: "slug", header: "Slug" },
		{ accessorKey: "config_count", header: "Configs" },
		{ accessorKey: "asset_count", header: "Assets" },
	];

	async function handleCreate() {
		creating = true;
		try {
			const api = createClientApiClient(async () => data.token);
			await api.post("/admin/tenants", newTenant);
			showCreateDialog = false;
			newTenant = { organization_id: "", organization_slug: "", name: "", verticals: ["private_credit", "liquid_funds"] };
			await invalidateAll();
		} catch (e) {
			console.error("Failed to create tenant:", e);
		} finally {
			creating = false;
		}
	}
</script>

<PageHeader title="Tenant Management">
	{#snippet actions()}
		<Button onclick={() => showCreateDialog = true}>Create Tenant</Button>
	{/snippet}
</PageHeader>

<div class="p-6">
	{#if data.tenants.length === 0}
		<EmptyState
			message="No tenants yet"
			description="Create your first tenant to get started."
		/>
	{:else}
		<DataTable
			data={data.tenants}
			{columns}
			onRowClick={(row) => window.location.href = `/tenants/${row.organization_id}`}
		/>
	{/if}
</div>

{#if showCreateDialog}
	<Dialog open={showCreateDialog} onClose={() => showCreateDialog = false} title="Create Tenant">
		<form onsubmit={(e) => { e.preventDefault(); handleCreate(); }} class="space-y-4">
			<Input
				label="Organization ID (UUID)"
				bind:value={newTenant.organization_id}
				placeholder="From Clerk organization"
				required
			/>
			<Input
				label="Organization Slug"
				bind:value={newTenant.organization_slug}
				placeholder="e.g. acme-capital"
				required
			/>
			<Input
				label="Name"
				bind:value={newTenant.name}
				placeholder="e.g. ACME Capital"
				required
			/>
			<div class="flex justify-end gap-3 pt-4">
				<Button variant="ghost" onclick={() => showCreateDialog = false}>Cancel</Button>
				<Button type="submit" disabled={creating}>
					{creating ? "Creating..." : "Create & Seed"}
				</Button>
			</div>
		</form>
	</Dialog>
{/if}
