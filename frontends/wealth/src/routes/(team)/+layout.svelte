<!--
  Team layout — initializes risk store once, shares via Svelte context.
  Risk store: SSE-primary, poll-fallback, in-memory $state, no localStorage.
  Degraded-state banner: amber for "degraded", red for "offline".
-->
<script lang="ts">
	import { setContext, onMount, type Snippet } from "svelte";
	import { getContext } from "svelte";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";
	import { formatLastUpdated } from "$lib/stores/stale";
	import { formatDateTime } from "@netz/ui";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { children }: { children: Snippet } = $props();

	// Create risk store once — shared across all (team) routes
	const riskStore = createRiskStore({
		profileIds: ["conservative", "moderate", "growth"],
		getToken,
		pollingFallbackMs: 30_000,
	});

	setContext<RiskStore>("netz:riskStore", riskStore);

	onMount(() => {
		riskStore.start();
		return () => riskStore.destroy();
	});

	// Derived banner state
	const quality = $derived(riskStore.connectionQuality);
	const bannerVisible = $derived(quality === "degraded" || quality === "offline");
	const lastComputedLabel = $derived(
		riskStore.computedAt ? formatDateTime(riskStore.computedAt) : formatLastUpdated(null)
	);
</script>

{#if bannerVisible}
	<div
		class="flex items-center gap-2 px-4 py-2 text-sm font-medium"
		class:bg-[var(--netz-warning-surface)]={quality === "degraded"}
		class:text-[var(--netz-warning-on-surface)]={quality === "degraded"}
		class:bg-[var(--netz-error-surface)]={quality === "offline"}
		class:text-[var(--netz-error-on-surface)]={quality === "offline"}
		role="status"
		aria-live="polite"
	>
		{#if quality === "degraded"}
			<span>Live connection interrupted. Showing data from {lastComputedLabel}. Reconnecting...</span>
		{:else}
			<span>Unable to reach server. Last update: {lastComputedLabel}.</span>
			<button
				class="underline hover:no-underline"
				onclick={() => riskStore.refresh()}
			>
				Retry
			</button>
		{/if}
	</div>
{/if}

{@render children()}
