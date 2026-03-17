<!--
  Team layout — initializes risk store once, shares via Svelte context.
  Risk store: in-memory $state, polling fallback (30s), no localStorage.
-->
<script lang="ts">
	import { setContext, onMount, type Snippet } from "svelte";
	import { getContext } from "svelte";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	let { children }: { children: Snippet } = $props();

	// Create risk store once — shared across all (team) routes
	const riskStore = createRiskStore({
		profileIds: ["conservative", "moderate", "growth"],
		getToken,
		apiBaseUrl: API_BASE,
		pollingFallbackMs: 30_000,
	});

	setContext<RiskStore>("netz:riskStore", riskStore);

	onMount(() => {
		riskStore.fetchAll();
		riskStore.startPolling();
		return () => riskStore.stopPolling();
	});
</script>

{@render children()}
