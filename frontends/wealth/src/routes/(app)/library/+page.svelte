<!--
  Wealth Library landing page.

  Phase 3 of the Library frontend (spec §3.4 + §2.5). Pure
  orchestrator: receives the server-loaded `RouteData<LibraryTree>`,
  branches on error / empty / data per Stability Guardrails §3.2,
  and hands the success payload to `LibraryShell`. The shell owns
  the rest of the experience.
-->
<script lang="ts">
	import { invalidate } from "$app/navigation";
	import { page as pageState } from "$app/state";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import LibraryShell from "$lib/components/library/LibraryShell.svelte";
	import type { LibraryTree } from "$lib/types/library";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const routeData = $derived(data.tree);
	const tree = $derived(routeData.data as LibraryTree);
	const initialPath = $derived(data.initialPath);

	function retryLoad(): void {
		invalidate(pageState.url.pathname);
	}
</script>

<svelte:head>
	<title>Library — Netz Wealth OS</title>
</svelte:head>

<svelte:boundary>
	{#if routeData.error}
		<PanelErrorState
			title="Unable to load the Library"
			message={routeData.error.message}
			onRetry={routeData.error.recoverable ? retryLoad : undefined}
		/>
	{:else if !routeData.data}
		<PanelEmptyState
			title="Library is empty"
			message="No documents are available in the Library yet."
		/>
	{:else}
		<LibraryShell {tree} {initialPath} />
	{/if}

	{#snippet failed(error)}
		<PanelErrorState
			title="Library failed to render"
			message={error instanceof Error ? error.message : String(error)}
			onRetry={retryLoad}
		/>
	{/snippet}
</svelte:boundary>
