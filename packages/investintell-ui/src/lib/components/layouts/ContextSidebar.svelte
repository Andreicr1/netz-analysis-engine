<!--
  @component ContextSidebar
  Persistent sidebar for detail pages (e.g. /funds/[fundId], /model-portfolios/[portfolioId]).
  Shows back link with entity name + contextual nav items (Resumo, DD Report, Docs, etc.).
  Only rendered when contextNav prop is passed to AppLayout.
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { ContextNav } from "../../utils/types.js";

	let {
		contextNav,
		class: className,
	}: {
		contextNav: ContextNav;
		class?: string;
	} = $props();

	function isActive(href: string): boolean {
		return contextNav.activeHref === href || contextNav.activeHref.startsWith(href + "/");
	}
</script>

<aside class={cn("ii-context-sidebar", className)} aria-label="Entity navigation">
	<!-- Back link -->
	<a href={contextNav.backHref} class="ii-context-sidebar__back">
		<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
			<path d="M10 3L5 8L10 13" />
		</svg>
		<span>{contextNav.backLabel}</span>
	</a>

	<!-- Nav items -->
	<ul class="ii-context-sidebar__nav" role="list">
		{#each contextNav.items as item (item.href)}
			<li>
				<a
					href={item.href}
					class={cn("ii-context-sidebar__item", isActive(item.href) && "ii-context-sidebar__item--active")}
					aria-current={isActive(item.href) ? "page" : undefined}
				>
					<span>{item.label}</span>
					{#if item.badge != null}
						<span class="ii-context-sidebar__badge">{item.badge}</span>
					{/if}
				</a>
			</li>
		{/each}
	</ul>
</aside>

<style>
	.ii-context-sidebar {
		display: flex;
		flex-direction: column;
		width: 220px;
		min-width: 220px;
		height: 100%;
		overflow-y: auto;
		background: var(--ii-surface, #ffffff);
		border-right: 1px solid var(--ii-border, #e5e7eb);
	}

	.ii-context-sidebar__back {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 14px 16px;
		font-size: 13px;
		font-weight: 600;
		color: var(--ii-text-primary, #111827);
		text-decoration: none;
		border-bottom: 1px solid var(--ii-border, #e5e7eb);
		transition: background-color 120ms ease;
	}

	.ii-context-sidebar__back:hover {
		background: var(--ii-surface-alt, #f3f4f6);
	}

	.ii-context-sidebar__nav {
		list-style: none;
		margin: 0;
		padding: 8px;
	}

	.ii-context-sidebar__item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		font-size: 13px;
		font-weight: 500;
		color: var(--ii-text-secondary, #6b7280);
		text-decoration: none;
		border-radius: 6px;
		border-left: 2px solid transparent;
		transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease;
	}

	.ii-context-sidebar__item:hover {
		background: var(--ii-surface-alt, #f3f4f6);
		color: var(--ii-text-primary, #111827);
	}

	.ii-context-sidebar__item--active {
		background: color-mix(in srgb, var(--ii-brand-primary, #2563eb) 8%, transparent);
		color: var(--ii-brand-primary, #2563eb);
		border-left-color: var(--ii-brand-primary, #2563eb);
		font-weight: 600;
	}

	.ii-context-sidebar__badge {
		font-size: 11px;
		font-weight: 600;
		padding: 1px 6px;
		border-radius: 9999px;
		background: var(--ii-surface-alt, #f3f4f6);
		color: var(--ii-text-secondary, #6b7280);
	}

	.ii-context-sidebar__item--active .ii-context-sidebar__badge {
		background: color-mix(in srgb, var(--ii-brand-primary, #2563eb) 15%, transparent);
		color: var(--ii-brand-primary, #2563eb);
	}
</style>
