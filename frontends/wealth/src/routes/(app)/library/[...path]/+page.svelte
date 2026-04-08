<!--
  Wealth Library deep-link route — same shell as `/library`.

  Phase 3 (spec §2.5). The catch-all forwards `initialPath` from the
  loader so the LibraryShell can pre-expand the right folder chain
  on first render. The page component is otherwise identical to the
  landing route.
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
