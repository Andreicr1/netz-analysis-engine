<!--
  Settings > Config — JSON config editor for liquid_funds vertical.
  Adapted from admin config page, hardcoded to liquid_funds.
-->
<script lang="ts">
	import { SectionCard, StatusBadge, EmptyState, ConfigEditor, resolveAdminStatus } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let selectedConfig = $state<string | null>(null);

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
</script>

<!-- Invalid Overrides Warning -->
{#if data.invalidConfigs?.length > 0}
	<SectionCard title="Invalid Overrides">
		<div class="space-y-2">
			{#each data.invalidConfigs as invalid (invalid.config_type)}
				<button
					onclick={() => {
						selectedConfig = invalid.config_type;
					}}
					class="flex w-full items-center gap-3 rounded-md border border-(--netz-danger)/30 bg-(--netz-danger)/5 px-4 py-2 text-left hover:bg-(--netz-danger)/10"
				>
					<StatusBadge status="error" label="Invalid" resolve={resolveAdminStatus} />
					<div>
						<span class="text-sm font-medium text-(--netz-text-primary)">
							{invalid.vertical}/{invalid.config_type}
						</span>
						{#if invalid.reason}
							<p class="text-xs text-(--netz-text-muted)">{invalid.reason}</p>
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
		<div class="divide-y divide-(--netz-border)">
			{#each data.configs as config (config.config_type)}
				<button
					onclick={() => {
						selectedConfig = config.config_type;
					}}
					class="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-(--netz-surface-alt) {selectedConfig === config.config_type ? 'bg-(--netz-surface-alt)' : ''}"
				>
					<div>
						<span class="text-sm font-medium text-(--netz-text-primary)">
							{config.config_type}
						</span>
						{#if config.description}
							<p class="text-xs text-(--netz-text-muted)">{config.description}</p>
						{/if}
					</div>
					<div class="flex items-center gap-2">
						{#if config.has_override}
							<StatusBadge status="warning" label="Override" resolve={resolveAdminStatus} />
						{:else}
							<StatusBadge status="success" label="Default" resolve={resolveAdminStatus} />
						{/if}
					</div>
				</button>
			{/each}
		</div>
	</SectionCard>
{:else}
	<SectionCard title="Config Types">
		<EmptyState title="No config types" message="No config types found for liquid_funds." />
	</SectionCard>
{/if}

<!-- Config Editor Panel -->
{#if selectedConfig}
	<ConfigEditor
		vertical={data.vertical}
		configType={selectedConfig}
		token={data.token}
		apiBaseUrl={API_BASE}
	/>
{/if}
