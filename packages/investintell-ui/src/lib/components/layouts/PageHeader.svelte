<!--
  @component PageHeader
  Page title + breadcrumb navigation + right-aligned actions area.
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";

	let {
		title,
		subtitle,
		breadcrumbs = [],
		class: className,
		actions,
	}: {
		title: string;
		subtitle?: string;
		breadcrumbs?: { label: string; href?: string }[];
		class?: string;
		actions?: Snippet;
	} = $props();
</script>

<div class={cn("ii-page-header", className)}>
	{#if breadcrumbs.length > 0}
		<nav class="ii-page-header__breadcrumbs" aria-label="Breadcrumb">
			<ol>
				{#each breadcrumbs as crumb, i (i)}
					<li>
						{#if crumb.href}
							<a href={crumb.href} class="ii-page-header__crumb-link">{crumb.label}</a>
						{:else}
							<span class="ii-page-header__crumb-text">{crumb.label}</span>
						{/if}
						{#if i < breadcrumbs.length - 1}
							<span class="ii-page-header__crumb-sep" aria-hidden="true">&gt;</span>
						{/if}
					</li>
				{/each}
			</ol>
		</nav>
	{/if}

	<div class="ii-page-header__row">
		<div class="ii-page-header__titles">
			<h1 class="ii-page-header__title">{title}</h1>
			{#if subtitle}
				<p class="ii-page-header__subtitle">{subtitle}</p>
			{/if}
		</div>
		{#if actions}
			<div class="ii-page-header__actions">
				{@render actions()}
			</div>
		{/if}
	</div>
</div>

<style>
	.ii-page-header {
		padding: 0;
	}

	.ii-page-header__breadcrumbs ol {
		display: flex;
		align-items: center;
		gap: 0;
		list-style: none;
		margin: 0 0 6px;
		padding: 0;
		font-size: var(--ii-text-sm, 14px);
		font-weight: var(--ii-weight-normal, 400);
		line-height: 20px;
		color: var(--ii-text-muted);
	}

	.ii-page-header__breadcrumbs li {
		display: flex;
		align-items: center;
	}

	.ii-page-header__crumb-link {
		color: var(--ii-text-muted);
		text-decoration: none;
		transition: color 120ms ease;
	}

	.ii-page-header__crumb-link:hover {
		color: var(--ii-text-primary);
		text-decoration: underline;
	}

	.ii-page-header__crumb-text {
		color: var(--ii-text-secondary);
	}

	.ii-page-header__crumb-sep {
		margin: 0 6px;
		color: var(--ii-text-muted);
		font-size: 11px;
	}

	.ii-page-header__row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		flex-wrap: wrap;
	}

	.ii-page-header__title {
		margin: 16px 0 0;
		font-size: var(--ii-text-h1, 30.4px);
		font-weight: var(--ii-weight-semibold, 600);
		line-height: var(--ii-leading-tight, 1.11);
		letter-spacing: var(--ii-tracking-tight, -0.025em);
		color: var(--ii-text-secondary);
		font-feature-settings: var(--ii-font-features, "rlig" 1, "calt" 1, "ss01" 1);
		-webkit-font-smoothing: antialiased;
	}

	.ii-page-header__titles {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.ii-page-header__subtitle {
		margin: 0;
		font-size: var(--ii-text-sm, 14px);
		font-weight: var(--ii-weight-normal, 400);
		line-height: 20px;
		color: var(--ii-text-muted);
	}

	.ii-page-header__actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	@media (max-width: 599px) {
		.ii-page-header__title {
			font-size: 20px;
		}
		.ii-page-header__row {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
