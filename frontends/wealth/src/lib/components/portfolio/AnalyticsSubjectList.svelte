<!--
  AnalyticsSubjectList — left-rail subject list for /portfolio/analytics.
  Phase 6 Block A.

  Renders the list of subjects (model portfolios or approved-universe
  instruments) for the active scope. Selecting a row updates the parent
  via ``onSelect`` — the parent is responsible for routing the
  selection into the AnalysisGrid + opening a BottomTabDock tab.

  Empty / loading states use the @investintell/ui EmptyState primitive
  per OD-26 (no fabricated values). Block A renders this list against
  the props the parent provides; Block B will wire real data sources.
-->
<script lang="ts">
	import { EmptyState } from "@investintell/ui";
	import type {
		AnalyticsScope,
		AnalyticsSubject,
	} from "$wealth/portfolio/analytics-types";

	interface Props {
		scope: AnalyticsScope;
		subjects: readonly AnalyticsSubject[];
		selectedId: string | null;
		isLoading?: boolean;
		onSelect: (subject: AnalyticsSubject) => void;
	}

	let {
		scope,
		subjects,
		selectedId,
		isLoading = false,
		onSelect,
	}: Props = $props();

	const emptyMessage = $derived.by(() => {
		switch (scope) {
			case "model_portfolios":
				return "No model portfolios in this org yet. Create one from the Builder.";
			case "approved_universe":
				return "No approved instruments yet. Approve funds from the Builder universe pill.";
			case "compare_both":
				return "Compare Both lands in v1.1.";
		}
	});
</script>

<div class="asl-root">
	{#if isLoading}
		<div class="asl-loading">
			<span class="asl-loading-bar"></span>
			<span class="asl-loading-bar"></span>
			<span class="asl-loading-bar"></span>
		</div>
	{:else if subjects.length === 0}
		<EmptyState title="Nothing to analyze" message={emptyMessage} />
	{:else}
		<ul class="asl-list" role="listbox" aria-label="Analytics subjects">
			{#each subjects as subject (subject.id)}
				{@const isSelected = selectedId === subject.id}
				<li>
					<button
						type="button"
						class="asl-row"
						class:asl-row--selected={isSelected}
						role="option"
						aria-selected={isSelected}
						onclick={() => onSelect(subject)}
					>
						<span class="asl-name">{subject.name}</span>
						{#if subject.subtitle}
							<span class="asl-subtitle">{subject.subtitle}</span>
						{/if}
						{#if subject.badge}
							<span class="asl-badge">{subject.badge}</span>
						{/if}
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.asl-root {
		display: flex;
		flex-direction: column;
		min-height: 0;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.asl-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.asl-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		grid-template-rows: auto auto;
		align-items: baseline;
		gap: 2px 8px;
		width: 100%;
		padding: 10px 12px;
		border: 1px solid transparent;
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-secondary, #cbccd1);
		font-family: inherit;
		text-align: left;
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.asl-row:hover:not(.asl-row--selected) {
		background: rgba(255, 255, 255, 0.04);
		color: var(--ii-text-primary, #ffffff);
	}

	.asl-row--selected {
		background: rgba(1, 119, 251, 0.12);
		border-color: var(--ii-primary, #0177fb);
		color: var(--ii-text-primary, #ffffff);
	}

	.asl-name {
		grid-column: 1;
		grid-row: 1;
		font-size: 13px;
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.asl-subtitle {
		grid-column: 1;
		grid-row: 2;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.asl-badge {
		grid-column: 2;
		grid-row: 1 / span 2;
		align-self: center;
		padding: 2px 8px;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted, #85a0bd);
		background: rgba(255, 255, 255, 0.06);
		border-radius: 999px;
		white-space: nowrap;
	}

	.asl-loading {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
	}

	.asl-loading-bar {
		display: block;
		height: 14px;
		border-radius: 4px;
		background: linear-gradient(
			90deg,
			rgba(255, 255, 255, 0.04),
			rgba(255, 255, 255, 0.08),
			rgba(255, 255, 255, 0.04)
		);
		background-size: 200% 100%;
		animation: asl-shimmer 1.4s ease-in-out infinite;
	}

	@keyframes asl-shimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}
</style>
