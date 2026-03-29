<!--
  @component Sidebar
  Collapsible icon navigation sidebar with nav items, active highlighting, and header snippet.
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { NavItem } from "../../utils/types.js";
	import type { Snippet } from "svelte";

	let {
		items = [],
		collapsed = false,
		onToggle,
		activeHref = "",
		class: className,
		header,
	}: {
		items?: NavItem[];
		collapsed?: boolean;
		onToggle?: () => void;
		activeHref?: string;
		class?: string;
		header?: Snippet;
	} = $props();

	function isActive(href: string): boolean {
		return activeHref === href || activeHref.startsWith(href + "/");
	}
</script>

<nav class={cn("ii-sidebar", collapsed && "ii-sidebar--collapsed", className)} aria-label="Main navigation">
	{#if header}
		<div class="ii-sidebar__header">
			{@render header()}
		</div>
	{/if}

	<ul class="ii-sidebar__nav" role="list">
		{#each items as item (item.href)}
			<li>
				<a
					href={item.href}
					class={cn("ii-sidebar__item", isActive(item.href) && "ii-sidebar__item--active")}
					title={collapsed ? item.label : undefined}
					aria-current={isActive(item.href) ? "page" : undefined}
				>
					{#if item.icon}
						<span class="ii-sidebar__icon">
							{#if typeof item.icon === "string"}
								{item.icon}
							{:else}
								{@const Icon = item.icon as any}
								<Icon size={18} strokeWidth={2} />
							{/if}
						</span>
					{/if}
					{#if !collapsed}
						<span class="ii-sidebar__label">{item.label}</span>
					{/if}
					{#if item.badge != null && !collapsed}
						<span class="ii-sidebar__badge">{item.badge}</span>
					{/if}
				</a>
				{#if item.children && item.children.length > 0 && !collapsed}
					<ul class="ii-sidebar__children" role="list">
						{#each item.children as child (child.href)}
							<li>
								<a
									href={child.href}
									class={cn("ii-sidebar__item ii-sidebar__item--child", isActive(child.href) && "ii-sidebar__item--active")}
									aria-current={isActive(child.href) ? "page" : undefined}
								>
									{#if child.icon}
										<span class="ii-sidebar__icon">
											{#if typeof child.icon === "string"}
												{child.icon}
											{:else}
												{@const Icon = child.icon as any}
												<Icon size={16} strokeWidth={2} />
											{/if}
										</span>
									{/if}
									<span class="ii-sidebar__label">{child.label}</span>
									{#if child.badge != null}
										<span class="ii-sidebar__badge">{child.badge}</span>
									{/if}
								</a>
							</li>
						{/each}
					</ul>
				{/if}
			</li>
		{/each}
	</ul>

	{#if onToggle}
		<button
			class="ii-sidebar__toggle"
			onclick={onToggle}
			aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
			type="button"
		>
			<svg
				class="ii-sidebar__toggle-icon"
				class:rotated={!collapsed}
				width="16"
				height="16"
				viewBox="0 0 16 16"
				fill="none"
				xmlns="http://www.w3.org/2000/svg"
			>
				<path
					d="M6 3L11 8L6 13"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
					stroke-linejoin="round"
				/>
			</svg>
		</button>
	{/if}
</nav>

<style>
	.ii-sidebar {
		display: flex;
		flex-direction: column;
		height: 100%;
		width: 240px;
		transition: width 200ms ease;
		overflow: hidden;
	}

	.ii-sidebar--collapsed {
		width: 56px;
	}

	.ii-sidebar__header {
		padding: 12px;
		border-bottom: 1px solid var(--ii-border, #e5e7eb);
		flex-shrink: 0;
	}

	.ii-sidebar__nav {
		flex: 1;
		overflow-y: auto;
		padding: 8px;
		list-style: none;
		margin: 0;
	}

	.ii-sidebar__item {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 8px 12px;
		border-radius: var(--ii-radius-sm, 6px);
		color: var(--ii-text-secondary, #6b7280);
		text-decoration: none;
		font-size: 14px;
		font-weight: 500;
		line-height: 1.4;
		white-space: nowrap;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.ii-sidebar__item:hover {
		background: var(--ii-surface-alt, #f3f4f6);
		color: var(--ii-text-primary, #111827);
	}

	.ii-sidebar__item--active {
		background: color-mix(in srgb, var(--ii-brand-primary, #2563eb) 10%, transparent);
		color: var(--ii-brand-primary, #2563eb);
		font-weight: 600;
	}

	.ii-sidebar__item--child {
		padding-left: 40px;
		font-size: 13px;
	}

	.ii-sidebar__icon {
		flex-shrink: 0;
		width: 20px;
		height: 20px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 18px;
	}

	.ii-sidebar__label {
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
	}

	.ii-sidebar__badge {
		flex-shrink: 0;
		font-size: 11px;
		font-weight: 600;
		padding: 1px 6px;
		border-radius: 9999px;
		background: var(--ii-brand-primary, #2563eb);
		color: #ffffff;
		line-height: 1.4;
	}

	.ii-sidebar__children {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.ii-sidebar__toggle {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		height: 44px;
		border: none;
		border-top: 1px solid var(--ii-border, #e5e7eb);
		background: transparent;
		color: var(--ii-text-muted, #9ca3af);
		cursor: pointer;
		transition: color 120ms ease;
	}

	.ii-sidebar__toggle:hover {
		color: var(--ii-text-primary, #111827);
	}

	.ii-sidebar__toggle-icon {
		transition: transform 200ms ease;
	}

	.ii-sidebar__toggle-icon.rotated {
		transform: rotate(180deg);
	}
</style>
