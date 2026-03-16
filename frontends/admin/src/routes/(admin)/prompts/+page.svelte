<!--
  Prompt list — grouped by vertical, showing override status and source level.
-->
<script lang="ts">
	import { PageHeader, Badge } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	interface PromptInfo {
		vertical: string;
		template_name: string;
		description: string | null;
		has_org_override: boolean;
		has_global_override: boolean;
		source_level: string;
	}

	const groups = [
		{ vertical: "private_credit", label: "Private Credit", prompts: data.creditPrompts as PromptInfo[] },
		{ vertical: "liquid_funds", label: "Liquid Funds", prompts: data.wealthPrompts as PromptInfo[] },
	];

	function sourceBadge(source: string): { variant: "default" | "outline" | "secondary"; label: string } {
		switch (source) {
			case "org": return { variant: "default", label: "Org Override" };
			case "global": return { variant: "secondary", label: "Global Override" };
			default: return { variant: "outline", label: "Filesystem" };
		}
	}
</script>

<PageHeader title="Prompt Templates" />

<div class="space-y-8 p-6">
	{#each groups as group}
		<section>
			<h2 class="mb-3 text-lg font-semibold text-[var(--netz-text-primary)]">{group.label}</h2>
			{#if group.prompts.length === 0}
				<p class="text-sm text-[var(--netz-text-muted)]">No templates found.</p>
			{:else}
				<div class="divide-y divide-[var(--netz-border)] rounded-lg border border-[var(--netz-border)]">
					{#each group.prompts as prompt}
						{@const badge = sourceBadge(prompt.source_level)}
						<a
							href="/prompts/{prompt.vertical}/{prompt.template_name}"
							class="flex items-center justify-between px-4 py-3 transition-colors hover:bg-[var(--netz-surface-alt)]"
						>
							<div>
								<span class="font-medium text-[var(--netz-text-primary)]">{prompt.template_name}</span>
								{#if prompt.description}
									<p class="text-xs text-[var(--netz-text-muted)]">{prompt.description}</p>
								{/if}
							</div>
							<Badge variant={badge.variant}>{badge.label}</Badge>
						</a>
					{/each}
				</div>
			{/if}
		</section>
	{/each}
</div>
