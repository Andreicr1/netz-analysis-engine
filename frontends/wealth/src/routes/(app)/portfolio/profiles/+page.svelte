<!--
  PR-A26.3 Section H — Profile selection page.
  Three cards (Conservative / Moderate / Growth) linking to the
  per-profile Strategic Allocation surface.
-->
<script lang="ts">
	import { resolve } from "$app/paths";
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import { PROFILE_LABELS } from "$lib/types/allocation-page";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
</script>

<div class="h-[calc(100vh-88px)] overflow-y-auto p-6">
	<header class="mb-6">
		<h1 class="text-2xl font-semibold text-foreground">Allocation Profiles</h1>
		<p class="text-sm text-muted-foreground mt-1">
			Review, propose, and approve the Strategic IPS for each risk profile.
		</p>
	</header>

	<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
		{#each data.summaries as summary (summary.profile)}
			<a
				href={resolve(`/portfolio/profiles/${summary.profile}/allocation`)}
				class="block rounded-lg border border-border bg-card p-5 hover:border-primary/60 hover:bg-accent/30 transition-colors"
			>
				<div class="flex items-start justify-between mb-3">
					<h2 class="text-lg font-medium text-foreground">
						{PROFILE_LABELS[summary.profile]}
					</h2>
					{#if summary.error}
						<span class="text-xs text-destructive">Error</span>
					{:else if summary.has_active_approval}
						<span class="text-xs px-2 py-0.5 rounded-full bg-success/10 text-success">
							Active
						</span>
					{:else}
						<span class="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
							Never Approved
						</span>
					{/if}
				</div>

				<dl class="space-y-1.5 text-sm">
					<div class="flex justify-between">
						<dt class="text-muted-foreground">CVaR Limit</dt>
						<dd class="text-foreground tabular-nums">
							{summary.cvar_limit !== null ? formatPercent(summary.cvar_limit) : "—"}
						</dd>
					</div>
					<div class="flex justify-between">
						<dt class="text-muted-foreground">Last Approved</dt>
						<dd class="text-foreground">
							{summary.last_approved_at
								? formatDateTime(summary.last_approved_at)
								: "—"}
						</dd>
					</div>
					<div class="flex justify-between">
						<dt class="text-muted-foreground">By</dt>
						<dd class="text-foreground truncate max-w-[50%]">
							{summary.last_approved_by ?? "—"}
						</dd>
					</div>
				</dl>

				<div class="mt-4 text-xs text-primary">
					View allocation →
				</div>
			</a>
		{/each}
	</div>
</div>
