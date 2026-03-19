<!--
  @component PageHeader
  Page title + breadcrumb navigation + right-aligned actions area.
-->
<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	let {
		title,
		breadcrumbs = [],
		class: className,
		actions,
	}: {
		title: string;
		breadcrumbs?: { label: string; href?: string }[];
		class?: string;
		actions?: Snippet;
	} = $props();
</script>

<div class={cn("netz-page-header", className)}>
	{#if breadcrumbs.length > 0}
		<nav class="netz-page-header__breadcrumbs" aria-label="Breadcrumb">
			<ol>
				{#each breadcrumbs as crumb, i (i)}
					<li>
						{#if crumb.href}
							<a href={crumb.href} class="netz-page-header__crumb-link">{crumb.label}</a>
						{:else}
							<span class="netz-page-header__crumb-text">{crumb.label}</span>
						{/if}
						{#if i < breadcrumbs.length - 1}
							<span class="netz-page-header__crumb-sep" aria-hidden="true">&gt;</span>
						{/if}
					</li>
				{/each}
			</ol>
		</nav>
	{/if}

	<div class="netz-page-header__row">
		<h1 class="netz-page-header__title">{title}</h1>
		{#if actions}
			<div class="netz-page-header__actions">
				{@render actions()}
			</div>
		{/if}
	</div>
</div>

<style>
	.netz-page-header {
		padding: 24px 0 16px;
	}

	.netz-page-header__breadcrumbs ol {
		display: flex;
		align-items: center;
		gap: 0;
		list-style: none;
		margin: 0 0 8px;
		padding: 0;
		font-size: 13px;
	}

	.netz-page-header__breadcrumbs li {
		display: flex;
		align-items: center;
	}

	.netz-page-header__crumb-link {
		color: var(--netz-text-muted, #9ca3af);
		text-decoration: none;
		transition: color 120ms ease;
	}

	.netz-page-header__crumb-link:hover {
		color: var(--netz-text-primary, #111827);
		text-decoration: underline;
	}

	.netz-page-header__crumb-text {
		color: var(--netz-text-secondary, #6b7280);
	}

	.netz-page-header__crumb-sep {
		margin: 0 6px;
		color: var(--netz-text-muted, #9ca3af);
		font-size: 11px;
	}

	.netz-page-header__row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		flex-wrap: wrap;
	}

	.netz-page-header__title {
		margin: 0;
		font-size: var(--netz-text-h2, 1.5rem);
		font-weight: 700;
		color: var(--netz-text-primary, #111827);
		line-height: 1.3;
	}

	.netz-page-header__actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	@media (max-width: 599px) {
		.netz-page-header__title {
			font-size: 20px;
		}
		.netz-page-header__row {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
