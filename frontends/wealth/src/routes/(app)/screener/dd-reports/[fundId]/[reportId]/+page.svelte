<!--
  DD Report route — delegates the reading workbench to
  `DDReportBody` (Phase 0 of the Wealth Library refactor).

  This file is now a thin shell: PageHeader with title + breadcrumbs,
  the RouteData success/error/empty branches, and a single
  `<DDReportBody {reportId} />` render. All workbench, audit,
  approval-dialog and SSE-streaming logic now lives in
  `lib/components/library/readers/DDReportBody.svelte` so the same
  body can be embedded inside the future `LibraryPreviewPane`.
-->
<script lang="ts">
	import { setContext } from "svelte";
	import { invalidate } from "$app/navigation";
	import { page as pageState } from "$app/state";
	import { PageHeader } from "@investintell/ui";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import DDReportBody from "$lib/components/library/readers/DDReportBody.svelte";
	import type { DDReportFull } from "$lib/types/dd-report";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const routeData = $derived(data.report);
	let report = $derived(routeData.data as DDReportFull);
	let fundId = $derived(data.fundId as string);
	let reportId = $derived(data.reportId as string);
	let actorId = $derived(data.actorId as string | null);
	let actorRole = $derived(data.actorRole as string | null);

	// Expose actor info to the body via context — Library preview
	// hosts will set this only for users with approval permissions.
	setContext("netz:dd-actor", { actorId, actorRole });

	function retryLoad() {
		invalidate(pageState.url.pathname);
	}
</script>

{#if routeData.error}
	<PanelErrorState
		title="Unable to load DD report"
		message={routeData.error.message}
		onRetry={routeData.error.recoverable ? retryLoad : undefined}
	/>
{:else if !routeData.data}
	<PanelEmptyState
		title="Report unavailable"
		message="This DD report is not available at the moment."
	/>
{:else}
	<PageHeader
		title="DD Report v{report.version}"
		breadcrumbs={[
			{ label: "DD Reports", href: "/dd-reports" },
			{ label: fundId, href: `/dd-reports/${fundId}` },
			{ label: `v${report.version}` },
		]}
	/>
	<DDReportBody {reportId} />
{/if}
