<!--
  LibraryFilterBar — chip-style secondary taxonomies for the Library.

  Phase 4 of the Library frontend (spec §3.4 Fase 4 + §2.3). Surfaces
  the orthogonal filters that don't belong in the navigation tree:
  status, kind, language, starred, plus a coarse date range. Every
  chip writes through the URL adapter so the entire filter set is
  shareable / deep-linkable / back-button-safe.
-->
<script lang="ts">
	import Star from "lucide-svelte/icons/star";
	import X from "lucide-svelte/icons/x";
	import type { UrlAdapter } from "$wealth/state/library/url-adapter.svelte";

	interface Props {
		adapter: UrlAdapter;
	}

	let { adapter }: Props = $props();

	const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
		{ value: "approved", label: "Approved" },
		{ value: "published", label: "Published" },
		{ value: "pending_approval", label: "Pending" },
		{ value: "rejected", label: "Rejected" },
		{ value: "archived", label: "Archived" },
	];

	const KIND_OPTIONS: Array<{ value: string; label: string }> = [
		{ value: "dd_report", label: "DD Report" },
		{ value: "investment_outlook", label: "Outlook" },
		{ value: "flash_report", label: "Flash" },
		{ value: "manager_spotlight", label: "Spotlight" },
		{ value: "macro_review", label: "Macro Review" },
		{ value: "fact_sheet", label: "Fact Sheet" },
	];

	const LANG_OPTIONS: Array<{ value: string; label: string }> = [
		{ value: "pt", label: "PT" },
		{ value: "en", label: "EN" },
	];

	const DATE_PRESETS: Array<{ id: string; label: string; days: number }> = [
		{ id: "today", label: "Today", days: 1 },
		{ id: "week", label: "This Week", days: 7 },
		{ id: "month", label: "This Month", days: 30 },
		{ id: "quarter", label: "Quarter", days: 90 },
		{ id: "year", label: "Year", days: 365 },
	];

	function applyDatePreset(days: number): void {
		const to = new Date();
		const from = new Date();
		from.setDate(from.getDate() - days);
		adapter.setDateRange(
			from.toISOString().slice(0, 10),
			to.toISOString().slice(0, 10),
		);
	}

	function clearDateRange(): void {
		adapter.setDateRange(null, null);
	}

	const hasActiveFilters = $derived(
		adapter.state.q.length > 0 ||
			adapter.state.statuses.length > 0 ||
			adapter.state.kinds.length > 0 ||
			adapter.state.from !== null ||
			adapter.state.to !== null ||
			adapter.state.language !== null ||
			adapter.state.starred,
	);

	const activeDatePresetDays = $derived.by(() => {
		if (!adapter.state.from || !adapter.state.to) return null;
		const from = new Date(adapter.state.from).getTime();
		const to = new Date(adapter.state.to).getTime();
		return Math.round((to - from) / (1000 * 60 * 60 * 24));
	});
</script>

<div class="filter-bar" role="toolbar" aria-label="Library filters">
	<div class="group" role="group" aria-label="Date range">
		<span class="group__label">When</span>
		{#each DATE_PRESETS as preset (preset.id)}
			<button
				type="button"
				class="chip"
				class:chip--active={activeDatePresetDays === preset.days}
				onclick={() => applyDatePreset(preset.days)}
			>
				{preset.label}
			</button>
		{/each}
		{#if adapter.state.from || adapter.state.to}
			<button
				type="button"
				class="chip chip--clear"
				onclick={clearDateRange}
				aria-label="Clear date range"
			>
				<X size={12} />
			</button>
		{/if}
	</div>

	<div class="group" role="group" aria-label="Status filter">
		<span class="group__label">Status</span>
		{#each STATUS_OPTIONS as option (option.value)}
			<button
				type="button"
				class="chip"
				class:chip--active={adapter.state.statuses.includes(option.value)}
				aria-pressed={adapter.state.statuses.includes(option.value)}
				onclick={() => adapter.toggleStatus(option.value)}
			>
				{option.label}
			</button>
		{/each}
	</div>

	<div class="group" role="group" aria-label="Kind filter">
		<span class="group__label">Kind</span>
		{#each KIND_OPTIONS as option (option.value)}
			<button
				type="button"
				class="chip"
				class:chip--active={adapter.state.kinds.includes(option.value)}
				aria-pressed={adapter.state.kinds.includes(option.value)}
				onclick={() => adapter.toggleKind(option.value)}
			>
				{option.label}
			</button>
		{/each}
	</div>

	<div class="group" role="group" aria-label="Language filter">
		<span class="group__label">Lang</span>
		{#each LANG_OPTIONS as option (option.value)}
			<button
				type="button"
				class="chip"
				class:chip--active={adapter.state.language === option.value}
				aria-pressed={adapter.state.language === option.value}
				onclick={() =>
					adapter.setLanguage(
						adapter.state.language === option.value ? null : option.value,
					)}
			>
				{option.label}
			</button>
		{/each}
	</div>

	<button
		type="button"
		class="chip chip--star"
		class:chip--active={adapter.state.starred}
		aria-pressed={adapter.state.starred}
		onclick={() => adapter.setStarred(!adapter.state.starred)}
		title="Show only starred"
	>
		<Star size={12} />
		Starred
	</button>

	{#if hasActiveFilters}
		<button
			type="button"
			class="chip chip--reset"
			onclick={() => adapter.clearAllFilters()}
		>
			Clear all
		</button>
	{/if}
</div>

<style>
	.filter-bar {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 10px 20px;
		background: #141519;
		border-bottom: 1px solid #404249;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		flex-wrap: wrap;
	}

	.group {
		display: flex;
		align-items: center;
		gap: 6px;
		padding-right: 14px;
		border-right: 1px solid #404249;
	}

	.group:last-of-type {
		border-right: none;
		padding-right: 0;
	}

	.group__label {
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: #85a0bd;
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 5px 10px;
		border: 1px solid #404249;
		background: #1d1f25;
		color: #cbccd1;
		font-family: inherit;
		font-size: 12px;
		font-weight: 500;
		border-radius: 999px;
		cursor: pointer;
		transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.chip:hover {
		border-color: #85a0bd;
		color: #ffffff;
	}

	.chip--active {
		background: color-mix(in srgb, #0177fb 22%, #141519);
		border-color: #0177fb;
		color: #ffffff;
	}

	.chip--clear {
		padding: 5px 6px;
		color: #85a0bd;
	}

	.chip--star {
		border-color: #404249;
	}

	.chip--reset {
		margin-left: auto;
		background: transparent;
		color: #85a0bd;
	}

	.chip--reset:hover {
		color: #ffffff;
		border-color: #ffffff;
	}
</style>
