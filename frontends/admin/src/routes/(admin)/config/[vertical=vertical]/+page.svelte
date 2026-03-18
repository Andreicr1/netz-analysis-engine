<!--
  Config Editor page — JSON config editor with guardrail validation, consequence-aware
  save, inline diff view, and audit trail. Section 3.Admin.1.
-->
<script lang="ts">
	import { SectionCard, StatusBadge, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";
	import ConfigEditor from "$lib/components/ConfigEditor.svelte";

	let { data }: { data: PageData } = $props();
	let selectedConfig = $state<string | null>(null);
</script>

<div class="space-y-6 p-6">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">
			Config — {data.vertical.replace("_", " ")}
		</h1>
		<div class="flex gap-2">
			<a
				href="/config/liquid_funds"
				class="rounded-md px-3 py-1 text-sm {data.vertical === 'liquid_funds'
					? 'bg-[var(--netz-brand-primary)] text-white'
					: 'text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]'}"
			>
				Liquid Funds
			</a>
			<a
				href="/config/private_credit"
				class="rounded-md px-3 py-1 text-sm {data.vertical === 'private_credit'
					? 'bg-[var(--netz-brand-primary)] text-white'
					: 'text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]'}"
			>
				Private Credit
			</a>
		</div>
	</div>

	<!-- Invalid Overrides Warning -->
	{#if data.invalidConfigs?.length > 0}
		<SectionCard title="Invalid Overrides">
			<div class="space-y-2">
				{#each data.invalidConfigs as invalid}
					<button
						onclick={() => {
							selectedConfig = invalid.config_type;
						}}
						class="flex w-full items-center gap-3 rounded-md border border-[var(--netz-danger)]/30 bg-[var(--netz-danger)]/5 px-4 py-2 text-left hover:bg-[var(--netz-danger)]/10"
					>
						<StatusBadge status="error" label="Invalid" />
						<div>
							<span class="text-sm font-medium text-[var(--netz-text-primary)]">
								{invalid.vertical}/{invalid.config_type}
							</span>
							{#if invalid.reason}
								<p class="text-xs text-[var(--netz-text-muted)]">{invalid.reason}</p>
							{/if}
						</div>
					</button>
				{/each}
			</div>
		</SectionCard>
	{/if}

	<!-- Config List -->
	{#if data.configs.length > 0}
		<SectionCard title="Config Types">
			<div class="divide-y divide-[var(--netz-border)]">
				{#each data.configs as config}
					<button
						onclick={() => {
							selectedConfig = config.config_type;
						}}
						class="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-[var(--netz-surface-alt)] {selectedConfig === config.config_type ? 'bg-[var(--netz-surface-alt)]' : ''}"
					>
						<div>
							<span class="text-sm font-medium text-[var(--netz-text-primary)]">
								{config.config_type}
							</span>
							{#if config.description}
								<p class="text-xs text-[var(--netz-text-muted)]">{config.description}</p>
							{/if}
						</div>
						<div class="flex items-center gap-2">
							{#if config.has_override}
								<StatusBadge status="warning" label="Override" />
							{:else}
								<StatusBadge status="success" label="Default" />
							{/if}
						</div>
					</button>
				{/each}
			</div>
		</SectionCard>
	{:else}
		<SectionCard title="Config Types">
			<EmptyState title="No config types" message="No config types found for {data.vertical}." />
		</SectionCard>
	{/if}

	<!-- Config Editor Panel — diff view and audit trail rendered inline by ConfigEditor -->
	{#if selectedConfig}
		<ConfigEditor
			vertical={data.vertical}
			configType={selectedConfig}
			token={data.token}
		/>
	{/if}
</div>
