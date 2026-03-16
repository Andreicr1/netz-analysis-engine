<!--
  Config list — grouped by vertical, showing override status per config_type.
-->
<script lang="ts">
	import { PageHeader, Badge } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	interface ConfigEntry {
		vertical: string;
		config_type: string;
		has_override: boolean;
		description: string | null;
	}

	const groups = [
		{ vertical: "private_credit", label: "Private Credit", configs: data.creditConfigs as ConfigEntry[] },
		{ vertical: "liquid_funds", label: "Liquid Funds", configs: data.wealthConfigs as ConfigEntry[] },
	];
</script>

<PageHeader title="Configuration" />

<div class="space-y-8 p-6">
	{#each groups as group}
		<section>
			<h2 class="mb-3 text-lg font-semibold text-[var(--netz-text-primary)]">{group.label}</h2>
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
				{#each group.configs as config}
					<a
						href="/config/{config.vertical}/{config.config_type}"
						class="rounded-lg border border-[var(--netz-border)] p-4 transition-colors hover:bg-[var(--netz-surface-alt)]"
					>
						<div class="flex items-center justify-between">
							<span class="font-medium text-[var(--netz-text-primary)]">{config.config_type}</span>
							{#if config.has_override}
								<Badge variant="default">Override</Badge>
							{:else}
								<Badge variant="outline">Default</Badge>
							{/if}
						</div>
						{#if config.description}
							<p class="mt-1 text-xs text-[var(--netz-text-muted)]">{config.description}</p>
						{/if}
					</a>
				{/each}
			</div>
		</section>
	{/each}
</div>
