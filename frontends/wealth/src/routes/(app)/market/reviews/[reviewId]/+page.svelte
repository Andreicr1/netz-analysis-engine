<!--
  Macro review route — delegates the body to `MacroReviewBody`
  (Phase 0 of the Wealth Library refactor).

  Thin shell: a back link plus the route data branches and
  `<MacroReviewBody {reviewId} />`. All score deltas, regime panels,
  staleness alerts and decision rendering live in
  `lib/components/library/readers/MacroReviewBody.svelte` so the
  same body powers the future LibraryPreviewPane.
-->
<script lang="ts">
	import { invalidate } from "$app/navigation";
	import { page as pageState } from "$app/state";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import MacroReviewBody from "$lib/components/library/readers/MacroReviewBody.svelte";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const routeData = $derived(data.review);
	let reviewId = $derived(pageState.params.reviewId ?? "");

	function retryLoad() {
		invalidate(pageState.url.pathname);
	}
</script>

{#if routeData.error}
	<PanelErrorState
		title="Unable to load committee review"
		message={routeData.error.message}
		onRetry={routeData.error.recoverable ? retryLoad : undefined}
	/>
{:else if !routeData.data}
	<PanelEmptyState
		title="Review unavailable"
		message="This committee review is not available."
	/>
{:else}
	<div class="route-topbar">
		<a href="/market" class="route-back">&larr; Macro Intelligence</a>
	</div>
	<MacroReviewBody {reviewId} />
{/if}

<style>
	.route-topbar {
		padding: 16px 24px 0;
	}

	.route-back {
		font-size: 13px;
		color: var(--ii-brand-primary);
		text-decoration: none;
	}

	.route-back:hover {
		text-decoration: underline;
	}
</style>
