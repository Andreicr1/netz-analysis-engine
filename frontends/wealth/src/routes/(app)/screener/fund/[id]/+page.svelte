<!--
  Fund Fact Sheet route — now a thin shell around FundFactSheetContent.

  The visual surface lives in
  `$lib/components/screener/FundFactSheetContent.svelte`, which is
  also reused by the floating preview Sheet on /screener. This route
  is preserved because Playwright still targets it for PDF
  generation (`fact-sheet/pdf` endpoint).

  Responsibilities kept here:
    - Own the server-loaded `routeData` (Stability Guardrails §3)
    - Own the outer scroll container + rounded-2xl background
    - Own the back-button navigation (manager context query params)
    - Own the PDF download handler (auth + blob download)
    - Provide an `invalidate`-based retry for recoverable errors
-->
<script lang="ts">
	import { goto, invalidate } from "$app/navigation";
	import { page as pageState } from "$app/state";
	import { getContext } from "svelte";
	import FundFactSheetContent from "$lib/components/screener/FundFactSheetContent.svelte";

	let { data } = $props();
	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const routeData = $derived(data.factSheet as any);

	// ── Back navigation — return to L2 (manager fund list) if the
	// user navigated here from inside ManagerDetailPanel. Otherwise
	// go back to the manager grid. ──
	const managerId = $derived(pageState.url.searchParams.get("manager"));
	const managerName = $derived(pageState.url.searchParams.get("manager_name"));
	const backLabel = $derived(managerId ? "Back to Fund List" : "Back to Managers");

	function goBack(): void {
		if (managerId) {
			const params = new URLSearchParams({ manager: managerId });
			if (managerName) params.set("manager_name", managerName);
			goto(`/screener?${params.toString()}`);
		} else {
			goto("/screener");
		}
	}

	function retryLoad(): void {
		invalidate(pageState.url.pathname);
	}

	// ── PDF download (kept here because it needs the route's
	// `fund.external_id` + manager query param context). ──
	let pdfLoading = $state(false);

	async function handleDownloadPdf(): Promise<void> {
		const fund = routeData?.data?.fund;
		if (pdfLoading || !fund) return;
		pdfLoading = true;
		try {
			const apiBase =
				import.meta.env.VITE_API_BASE_URL ??
				"http://localhost:8000/api/v1";
			const params = new URLSearchParams();
			if (managerId) params.set("manager", managerId);
			if (managerName) params.set("manager_name", managerName);
			const qs = params.toString() ? `?${params.toString()}` : "";
			const token = getToken ? await getToken() : "";
			const res = await fetch(
				`${apiBase}/screener/catalog/${fund.external_id}/fact-sheet/pdf${qs}`,
				{
					method: "POST",
					headers: { Authorization: `Bearer ${token}` },
				},
			);
			if (!res.ok) throw new Error(`PDF generation failed: ${res.status}`);
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `fact-sheet-${fund.ticker || fund.external_id}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (err) {
			console.error("PDF download failed:", err);
		} finally {
			pdfLoading = false;
		}
	}

	const pageTitle = $derived(routeData?.data?.fund?.name ?? "Fund");
</script>

<svelte:head>
	<title>{pageTitle} | Fact Sheet</title>
</svelte:head>

<!--
  The outer scroll + rounded-2xl background lives in the parent
  fund-detail +layout.svelte now, so both Fact Sheet and Risk
  Analysis inherit the same shell. This page renders content only.
-->
<FundFactSheetContent
	{routeData}
	showBackButton={true}
	onBack={goBack}
	{backLabel}
	onDownloadPdf={handleDownloadPdf}
	{pdfLoading}
	onRetry={retryLoad}
/>
