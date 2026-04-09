<!--
  PortfolioSelector — Master view (Phase 10 Master-Detail pattern).

  Renders when no portfolio is selected. Full-width centered layout
  with the portfolio list and a prominent "+ New Portfolio" CTA.
  Clicking a portfolio row fires ``onSelect`` which transitions the
  page to the Detail (Builder) view.

  This component is extracted from the old "Models" tab that was
  previously crammed into the left sidebar sub-pills alongside
  Universe and Policy — causing loss of context when the PM
  switched tabs.
-->
<script lang="ts">
	import { StatusBadge, formatDateTime, EmptyState } from "@investintell/ui";
	import Plus from "lucide-svelte/icons/plus";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import { profileColor, blockLabel } from "$lib/types/model-portfolio";
	import { portfolioDisplayName } from "$lib/constants/blocks";

	interface Props {
		portfolios: ModelPortfolio[];
		onSelect: (portfolio: ModelPortfolio) => void;
		onNewPortfolio: () => void;
	}

	let { portfolios, onSelect, onNewPortfolio }: Props = $props();

	const drafts = $derived(portfolios.filter((p) => p.state === "draft"));
	const active = $derived(
		portfolios.filter((p) => p.state !== "draft" && p.state !== "archived"),
	);
	const archived = $derived(portfolios.filter((p) => p.state === "archived"));
</script>

<div class="ps-root">
	<div class="ps-container">
		<header class="ps-header">
			<div class="ps-title-block">
				<h1 class="ps-title">Model Portfolios</h1>
				<p class="ps-subtitle">
					Select a portfolio to open the Builder, or create a new one.
				</p>
			</div>
			<button type="button" class="ps-new-btn" onclick={onNewPortfolio}>
				<Plus size={16} />
				New Portfolio
			</button>
		</header>

		{#if portfolios.length === 0}
			<div class="ps-empty">
				<EmptyState
					title="No model portfolios yet"
					message="Create your first model portfolio to begin constructing allocation strategies."
				/>
			</div>
		{:else}
			{#if active.length > 0}
				<section class="ps-section" aria-label="Active portfolios">
					<h2 class="ps-section-title">Active</h2>
					<div class="ps-grid">
						{#each active as mp (mp.id)}
							<button
								type="button"
								class="ps-card"
								onclick={() => onSelect(mp)}
							>
								<div class="ps-card-top">
									<span
										class="ps-card-profile"
										style:color={profileColor(mp.profile)}
									>
										{portfolioDisplayName(mp.profile)}
									</span>
									<StatusBadge status={mp.state} />
								</div>
								<span class="ps-card-name">
									{mp.display_name}
								</span>
								<div class="ps-card-meta">
									{#if mp.fund_selection_schema}
										<span>
											{mp.fund_selection_schema.funds.length} funds
										</span>
									{/if}
									<span>{formatDateTime(mp.created_at)}</span>
								</div>
							</button>
						{/each}
					</div>
				</section>
			{/if}

			{#if drafts.length > 0}
				<section class="ps-section" aria-label="Draft portfolios">
					<h2 class="ps-section-title">Drafts</h2>
					<div class="ps-grid">
						{#each drafts as mp (mp.id)}
							<button
								type="button"
								class="ps-card"
								onclick={() => onSelect(mp)}
							>
								<div class="ps-card-top">
									<span
										class="ps-card-profile"
										style:color={profileColor(mp.profile)}
									>
										{portfolioDisplayName(mp.profile)}
									</span>
									<StatusBadge status={mp.state} />
								</div>
								<span class="ps-card-name">
									{mp.display_name}
								</span>
								<div class="ps-card-meta">
									<span>{formatDateTime(mp.created_at)}</span>
								</div>
							</button>
						{/each}
					</div>
				</section>
			{/if}

			{#if archived.length > 0}
				<section class="ps-section" aria-label="Archived portfolios">
					<h2 class="ps-section-title">Archived</h2>
					<div class="ps-grid ps-grid--archived">
						{#each archived as mp (mp.id)}
							<button
								type="button"
								class="ps-card ps-card--archived"
								onclick={() => onSelect(mp)}
							>
								<span class="ps-card-name">{mp.display_name}</span>
								<div class="ps-card-meta">
									<StatusBadge status={mp.state} />
									<span>{formatDateTime(mp.created_at)}</span>
								</div>
							</button>
						{/each}
					</div>
				</section>
			{/if}
		{/if}
	</div>
</div>

<style>
	.ps-root {
		display: flex;
		align-items: flex-start;
		justify-content: center;
		height: 100%;
		overflow-y: auto;
		background: #0e0f13;
		padding: 32px 24px;
	}
	.ps-container {
		width: 100%;
		max-width: 860px;
	}
	.ps-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		margin-bottom: 32px;
	}
	.ps-title-block {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.ps-title {
		margin: 0;
		font-size: 22px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.ps-subtitle {
		margin: 0;
		font-size: 13px;
		color: var(--ii-text-muted, #85a0bd);
	}
	.ps-new-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 10px 20px;
		border: 1px solid #ffffff;
		border-radius: 36px;
		background: #000000;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
		font-size: 13px;
		font-weight: 400;
		cursor: pointer;
		transition: background 120ms ease;
		white-space: nowrap;
		flex-shrink: 0;
	}
	.ps-new-btn:hover {
		background: #1a1b20;
	}
	.ps-new-btn:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}

	.ps-section {
		margin-bottom: 28px;
	}
	.ps-section-title {
		margin: 0 0 12px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--ii-text-muted, #85a0bd);
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.ps-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 12px;
	}
	.ps-grid--archived {
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
	}

	.ps-card {
		appearance: none;
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 16px;
		background: #141519;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
		cursor: pointer;
		text-align: left;
		font-family: "Urbanist", system-ui, sans-serif;
		transition: border-color 120ms ease, background 120ms ease;
	}
	.ps-card:hover {
		border-color: rgba(255, 255, 255, 0.2);
		background: #1a1b22;
	}
	.ps-card:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
	.ps-card--archived {
		opacity: 0.6;
	}

	.ps-card-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.ps-card-profile {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.ps-card-name {
		font-size: 15px;
		font-weight: 600;
		color: var(--ii-text-primary, #ffffff);
	}
	.ps-card-meta {
		display: flex;
		gap: 8px;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
	}

	.ps-empty {
		padding: 48px 24px;
		display: flex;
		justify-content: center;
	}
</style>
