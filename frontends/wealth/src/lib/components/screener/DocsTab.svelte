<!--
  Docs tab — brochure sections list + full-text search with 300ms debounce.
  Lazy-loaded when tab is activated.
-->
<script lang="ts">
	import "./screener.css";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { formatDate } from "@netz/ui";
	import type { BrochureSectionsResponse, BrochureSearchResponse } from "$lib/types/manager-screener";

	interface Props {
		crd: string | null;
	}

	let { crd }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let loading = $state(false);
	let error = $state<string | null>(null);
	let sections = $state<BrochureSectionsResponse | null>(null);
	let searchQuery = $state("");
	let searchResults = $state<BrochureSearchResponse | null>(null);
	let searching = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	$effect(() => {
		if (!crd) {
			sections = null;
			searchResults = null;
			return;
		}

		const currentCrd = crd;
		const controller = new AbortController();
		searchQuery = "";
		searchResults = null;

		loadSections(currentCrd, controller);

		return () => {
			controller.abort();
			if (debounceTimer) clearTimeout(debounceTimer);
		};
	});

	async function loadSections(targetCrd: string, controller?: AbortController) {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.get<BrochureSectionsResponse>(
				`/manager-screener/managers/${targetCrd}/brochure/sections`,
			);
			if (!controller?.signal.aborted) {
				sections = result;
			}
		} catch (e) {
			if (!controller?.signal.aborted) {
				error = e instanceof Error ? e.message : "Failed to load docs";
			}
		} finally {
			if (!controller?.signal.aborted) {
				loading = false;
			}
		}
	}

	function handleSearchInput() {
		if (debounceTimer) clearTimeout(debounceTimer);

		if (!searchQuery.trim() || searchQuery.trim().length < 2) {
			searchResults = null;
			return;
		}

		debounceTimer = setTimeout(() => {
			void executeSearch();
		}, 300);
	}

	async function executeSearch() {
		if (!crd || !searchQuery.trim()) return;
		searching = true;
		try {
			const api = createClientApiClient(getToken);
			searchResults = await api.get<BrochureSearchResponse>(
				`/manager-screener/managers/${crd}/brochure`,
				{ q: searchQuery.trim() },
			);
		} catch {
			searchResults = null;
		} finally {
			searching = false;
		}
	}
</script>

{#if !crd}
	<div class="dt-section">
		<p class="dt-empty-text">Institutional data unavailable — This manager is not registered with the SEC.</p>
	</div>
{:else if loading}
	<div class="dt-loading">Loading docs…</div>
{:else if error}
	<div class="dt-section">
		<p class="dt-empty-text" style="color: var(--netz-danger)">{error}</p>
	</div>
{:else}
	<!-- Search -->
	<div class="docs-search">
		<input
			class="scr-input"
			type="text"
			placeholder="Search brochure content…"
			bind:value={searchQuery}
			oninput={handleSearchInput}
		/>
		{#if searching}
			<span class="docs-searching">Searching…</span>
		{/if}
	</div>

	{#if searchResults}
		<!-- Search results -->
		<div class="dt-section">
			<h4 class="dt-section-title">
				{searchResults.total_results} result{searchResults.total_results !== 1 ? "s" : ""} for "{searchResults.query}"
			</h4>
			{#if searchResults.results.length === 0}
				<p class="dt-empty-text">No matches found.</p>
			{:else}
				{#each searchResults.results as hit (hit.section + hit.filing_date)}
					<div class="docs-result">
						<div class="docs-result-header">
							<span class="docs-section-name">{hit.section}</span>
							<span class="docs-filing-date">{formatDate(hit.filing_date)}</span>
						</div>
						<div class="docs-headline">{@html hit.headline}</div>
					</div>
				{/each}
			{/if}
		</div>
	{:else if sections}
		<!-- Sections listing -->
		<div class="dt-section">
			<h4 class="dt-section-title">Sections ({sections.total_sections})</h4>
			{#if sections.sections.length === 0}
				<p class="dt-empty-text">No brochure data available.</p>
			{:else}
				{#each sections.sections as section (section.section + section.filing_date)}
					<div class="docs-section-row">
						<div class="docs-section-header">
							<span class="docs-section-name">{section.section}</span>
							<span class="docs-filing-date">{formatDate(section.filing_date)}</span>
						</div>
						<p class="docs-excerpt">{section.content_excerpt}</p>
					</div>
				{/each}
			{/if}
		</div>
	{/if}
{/if}

<style>
	.docs-search {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.docs-searching {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		white-space: nowrap;
	}

	.docs-section-row, .docs-result {
		padding: var(--netz-space-stack-xs, 8px) 0;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.docs-section-header, .docs-result-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 4px;
	}

	.docs-section-name {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.docs-filing-date {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.docs-excerpt {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		line-height: 1.4;
		overflow: hidden;
		text-overflow: ellipsis;
		display: -webkit-box;
		-webkit-line-clamp: 3;
		-webkit-box-orient: vertical;
	}

	.docs-headline {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		line-height: 1.5;
	}

	.docs-headline :global(b) {
		color: var(--netz-brand-primary);
		font-weight: 600;
	}
</style>
