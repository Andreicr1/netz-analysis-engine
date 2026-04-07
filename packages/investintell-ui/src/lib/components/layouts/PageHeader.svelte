<!--
  @component PageHeader
  Page title + breadcrumb navigation + right-aligned actions area.
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";
	import * as Breadcrumb from "$lib/components/ui/breadcrumb";

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
		<Breadcrumb.Root class="mb-1.5">
			<Breadcrumb.List>
				{#each breadcrumbs as crumb, i (i)}
					<Breadcrumb.Item>
						{#if crumb.href && i < breadcrumbs.length - 1}
							<Breadcrumb.Link href={crumb.href}>{crumb.label}</Breadcrumb.Link>
						{:else}
							<Breadcrumb.Page>{crumb.label}</Breadcrumb.Page>
						{/if}
					</Breadcrumb.Item>
					{#if i < breadcrumbs.length - 1}
						<Breadcrumb.Separator />
					{/if}
				{/each}
			</Breadcrumb.List>
		</Breadcrumb.Root>
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
