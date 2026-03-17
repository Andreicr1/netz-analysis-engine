<!--
  Tenant list — grid of TenantCards with Create button.
-->
<script lang="ts">
	import { SectionCard, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";
	import TenantCard from "$lib/components/TenantCard.svelte";

	let { data }: { data: PageData } = $props();
	let showCreate = $state(false);
	let newName = $state("");
	let newSlug = $state("");
	let newVertical = $state("liquid_funds");
	let creating = $state(false);
</script>

<div class="space-y-6 p-6">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">Tenants</h1>
		<button
			onclick={() => (showCreate = true)}
			class="rounded-md bg-[var(--netz-brand-primary)] px-4 py-2 text-sm text-white hover:opacity-90"
		>
			Create Tenant
		</button>
	</div>

	{#if data.tenants.length > 0}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each data.tenants as tenant}
				<TenantCard {tenant} />
			{/each}
		</div>
	{:else}
		<SectionCard title="Tenants">
			<EmptyState message="No tenants found. Create one to get started." />
		</SectionCard>
	{/if}

	{#if showCreate}
		<div
			class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
			onclick={() => (showCreate = false)}
			onkeydown={(e) => e.key === "Escape" && (showCreate = false)}
			role="dialog"
			tabindex="-1"
		>
			<div
				class="w-full max-w-md rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-6 shadow-xl"
				onclick={(e) => e.stopPropagation()}
				onkeydown={() => {}}
				role="document"
			>
				<h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">
					Create Tenant
				</h2>
				<div class="space-y-4">
					<div>
						<label
							for="tenant-name"
							class="mb-1 block text-sm text-[var(--netz-text-secondary)]"
						>
							Organization Name
						</label>
						<input
							id="tenant-name"
							bind:value={newName}
							class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
							placeholder="Acme Capital"
						/>
					</div>
					<div>
						<label
							for="tenant-slug"
							class="mb-1 block text-sm text-[var(--netz-text-secondary)]"
						>
							Slug
						</label>
						<input
							id="tenant-slug"
							bind:value={newSlug}
							class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
							placeholder="acme-capital"
						/>
					</div>
					<div>
						<label
							for="tenant-vertical"
							class="mb-1 block text-sm text-[var(--netz-text-secondary)]"
						>
							Vertical
						</label>
						<select
							id="tenant-vertical"
							bind:value={newVertical}
							class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
						>
							<option value="liquid_funds">Liquid Funds</option>
							<option value="private_credit">Private Credit</option>
						</select>
					</div>
					<div class="flex justify-end gap-2">
						<button
							onclick={() => (showCreate = false)}
							class="rounded-md border border-[var(--netz-border)] px-4 py-2 text-sm text-[var(--netz-text-primary)] hover:bg-[var(--netz-surface-alt)]"
						>
							Cancel
						</button>
						<button
							disabled={creating || !newName || !newSlug}
							class="rounded-md bg-[var(--netz-brand-primary)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-50"
						>
							Create
						</button>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
