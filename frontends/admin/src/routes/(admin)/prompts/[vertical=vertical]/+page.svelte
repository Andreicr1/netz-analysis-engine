<!--
  Prompt Editor — template list + split-pane editor with live preview.
-->
<script lang="ts">
	import { SectionCard, StatusBadge, EmptyState } from "@netz/ui";
	import { resolveAdminStatus } from "$lib/utils/status-maps.js";
	import type { PageData } from "./$types";
	import PromptEditor from "$lib/components/PromptEditor.svelte";

	let { data }: { data: PageData } = $props();
	let selectedPrompt = $state<string | null>(null);
</script>

<div class="space-y-6 p-6">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">
			Prompts — {data.vertical.replace("_", " ")}
		</h1>
		<div class="flex gap-2">
			<a
				href="/prompts/private_credit"
				class="rounded-md px-3 py-1 text-sm {data.vertical === 'private_credit'
					? 'bg-[var(--netz-brand-primary)] text-white'
					: 'text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]'}"
			>
				Private Credit
			</a>
			<a
				href="/prompts/liquid_funds"
				class="rounded-md px-3 py-1 text-sm {data.vertical === 'liquid_funds'
					? 'bg-[var(--netz-brand-primary)] text-white'
					: 'text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]'}"
			>
				Liquid Funds
			</a>
		</div>
	</div>

	<!-- Prompt List -->
	{#if data.prompts.length > 0}
		<SectionCard title="Templates">
			<div class="divide-y divide-[var(--netz-border)]">
				{#each data.prompts as prompt}
					<button
						onclick={() => (selectedPrompt = prompt.template_name)}
						class="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-[var(--netz-surface-alt)] {selectedPrompt ===
						prompt.template_name
							? 'bg-[var(--netz-surface-alt)]'
							: ''}"
					>
						<div>
							<span class="text-sm font-medium text-[var(--netz-text-primary)]">
								{prompt.template_name}
							</span>
							{#if prompt.description}
								<p class="text-xs text-[var(--netz-text-muted)]">{prompt.description}</p>
							{/if}
						</div>
						<div class="flex items-center gap-2">
							<StatusBadge
								status={prompt.source_level === "org"
									? "accent"
									: prompt.source_level === "global"
										? "warning"
										: "success"}
								label={prompt.source_level}
								resolve={resolveAdminStatus}
							/>
							{#if prompt.version}
								<span class="text-xs text-[var(--netz-text-muted)]">v{prompt.version}</span>
							{/if}
						</div>
					</button>
				{/each}
			</div>
		</SectionCard>
	{:else}
		<SectionCard title="Templates">
			<EmptyState message="No prompt templates found for {data.vertical}." />
		</SectionCard>
	{/if}

	<!-- Prompt Editor -->
	{#if selectedPrompt}
		<PromptEditor
			vertical={data.vertical}
			templateName={selectedPrompt}
			token={data.token}
		/>
	{/if}
</div>
