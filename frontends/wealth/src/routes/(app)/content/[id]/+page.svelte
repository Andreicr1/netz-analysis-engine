<!--
  Content detail route — delegates the document body to
  `ContentBody` (Phase 0 of the Wealth Library refactor).

  Thin shell: PageHeader with title + breadcrumbs, the RouteData
  branches, and `<ContentBody {id} />`. All approval, download,
  markdown rendering and content_data display now live in
  `lib/components/library/readers/ContentBody.svelte` so the same
  body powers the future LibraryPreviewPane.
-->
<script lang="ts">
	import { setContext } from "svelte";
	import { invalidate } from "$app/navigation";
	import { page as pageState } from "$app/state";
	import { PageHeader } from "@investintell/ui";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import ContentBody from "$lib/components/library/readers/ContentBody.svelte";
	import { contentTypeLabel } from "$lib/types/content";
	import type { ContentFull } from "$lib/types/content";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const routeData = $derived(data.content);
	let content = $derived(routeData.data as ContentFull);
	let id = $derived(content?.id ?? "");
	let actorId = $derived((data.actorId ?? null) as string | null);
	let actorRole = $derived((data.actorRole ?? null) as string | null);

	setContext("netz:content-actor", { actorId, actorRole });

	function retryLoad() {
		invalidate(pageState.url.pathname);
	}
</script>

{#if routeData.error}
	<PanelErrorState
		title="Unable to load content"
		message={routeData.error.message}
		onRetry={routeData.error.recoverable ? retryLoad : undefined}
	/>
{:else if !routeData.data}
	<PanelEmptyState
		title="No content available"
		message="This content is not available at the moment."
	/>
{:else}
	<PageHeader
		title={content.title ?? contentTypeLabel(content.content_type)}
		breadcrumbs={[
			{ label: "Content", href: "/content" },
			{ label: content.title ?? contentTypeLabel(content.content_type) },
		]}
	/>
	<ContentBody {id} />
{/if}
