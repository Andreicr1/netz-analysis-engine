<!--
  Manager detail page — full-page wrapper for ManagerDetailPanel.
  Route: /screener/managers/[crd]
-->
<script lang="ts">
	import { ManagerDetailPanel } from "$lib/components/screener";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
</script>

<svelte:head>
	<title>{data.firmName} — Netz Wealth</title>
</svelte:head>

<div class="mgr-page">
	<div class="mgr-page-header">
		<a href="/screener" class="mgr-back-link">&larr; Back to Screener</a>
		<h1 class="mgr-page-title">{data.firmName}</h1>
		<span class="mgr-page-crd">CRD {data.crd}</span>
	</div>
	<div class="mgr-page-body">
		<ManagerDetailPanel panelCrd={data.crd} panelFirm={data.firmName} />
	</div>
</div>

<style>
	.mgr-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 48px);
		overflow: hidden;
	}

	.mgr-page-header {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 16px 24px;
		border-bottom: 1px solid var(--ii-border);
		flex-shrink: 0;
	}

	.mgr-back-link {
		font-size: 13px;
		color: var(--ii-text-muted);
		text-decoration: none;
	}

	.mgr-back-link:hover {
		color: var(--ii-text-primary);
	}

	.mgr-page-title {
		font-size: 20px;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0;
	}

	.mgr-page-crd {
		font-size: 12px;
		color: var(--ii-text-muted);
		font-family: var(--ii-font-mono, monospace);
	}

	.mgr-page-body {
		flex: 1;
		overflow-y: auto;
	}
</style>
