<!--
  Risk — SSE stream panels, regime detection, CVaR.
-->
<script lang="ts">
	import { PageHeader } from "@netz/ui";
	import { getContext } from "svelte";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";

	const riskStore = getContext<RiskStore>("netz:riskStore");
</script>

<PageHeader title="Risk Monitor" />

<div class="p-6">
	<div class="rounded-lg border border-(--netz-border-subtle) bg-(--netz-surface-elevated) p-8 text-center">
		<p class="text-sm text-(--netz-text-muted)">Live risk dashboard — CVaR, regime detection, stress scenarios</p>
		<p class="mt-2 text-xs text-(--netz-text-muted)">Connection: {riskStore.connectionQuality}</p>
	</div>
</div>
