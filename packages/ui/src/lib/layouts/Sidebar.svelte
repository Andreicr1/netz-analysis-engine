<!--
  @component Sidebar
  Collapsible icon navigation sidebar with nav items, active highlighting, and header snippet.
-->
<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { NavItem } from "../utils/types.js";
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

<nav class={cn("netz-sidebar", collapsed && "netz-sidebar--collapsed", className)} aria-label="Main navigation">
	{#if header}
		<div class="netz-sidebar__header">
			{@render header()}
		</div>
	{/if}

	<ul class="netz-sidebar__nav" role="list">
		{#each items as item (item.href)}
			<li>
				<a
					href={item.href}
					class={cn("netz-sidebar__item", isActive(item.href) && "netz-sidebar__item--active")}
					title={collapsed ? item.label : undefined}
					aria-current={isActive(item.href) ? "page" : undefined}
				>
					{#if item.icon}
						<span class="netz-sidebar__icon">
							{#if typeof item.icon === "string"}
								{item.icon}
							{:else}
								{@const Icon = item.icon as any}
								<Icon size={18} strokeWidth={2} />
							{/if}
						</span>
					{/if}
					{#if !collapsed}
						<span class="netz-sidebar__label">{item.label}</span>
					{/if}
					{#if item.badge != null && !collapsed}
						<span class="netz-sidebar__badge">{item.badge}</span>
					{/if}
				</a>
				{#if item.children && item.children.length > 0 && !collapsed}
					<ul class="netz-sidebar__children" role="list">
						{#each item.children as child (child.href)}
							<li>
								<a
									href={child.href}
									class={cn("netz-sidebar__item netz-sidebar__item--child", isActive(child.href) && "netz-sidebar__item--active")}
									aria-current={isActive(child.href) ? "page" : undefined}
								>
									{#if child.icon}
										<span class="netz-sidebar__icon">
											{#if typeof child.icon === "string"}
												{child.icon}
											{:else}
												{@const Icon = child.icon as any}
												<Icon size={16} strokeWidth={2} />
											{/if}
										</span>
									{/if}
									<span class="netz-sidebar__label">{child.label}</span>
									{#if child.badge != null}
										<span class="netz-sidebar__badge">{child.badge}</span>
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
			class="netz-sidebar__toggle"
			onclick={onToggle}
			aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
			type="button"
		>
			<svg
				class="netz-sidebar__toggle-icon"
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
	.netz-sidebar {
		display: flex;
		flex-direction: column;
		height: 100%;
		width: 240px;
		transition: width 200ms ease;
		overflow: hidden;
	}

	.netz-sidebar--collapsed {
		width: 56px;
	}

	.netz-sidebar__header {
		padding: 12px;
		border-bottom: 1px solid var(--netz-border, #e5e7eb);
		flex-shrink: 0;
	}

	.netz-sidebar__nav {
		flex: 1;
		overflow-y: auto;
		padding: 8px;
		list-style: none;
		margin: 0;
	}

	.netz-sidebar__item {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 8px 12px;
		border-radius: var(--netz-radius-sm, 6px);
		color: var(--netz-text-secondary, #6b7280);
		text-decoration: none;
		font-size: 14px;
		font-weight: 500;
		line-height: 1.4;
		white-space: nowrap;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.netz-sidebar__item:hover {
		background: var(--netz-surface-alt, #f3f4f6);
		color: var(--netz-text-primary, #111827);
	}

	.netz-sidebar__item--active {
		background: color-mix(in srgb, var(--netz-brand-primary, #2563eb) 10%, transparent);
		color: var(--netz-brand-primary, #2563eb);
		font-weight: 600;
	}

	.netz-sidebar__item--child {
		padding-left: 40px;
		font-size: 13px;
	}

	.netz-sidebar__icon {
		flex-shrink: 0;
		width: 20px;
		height: 20px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 18px;
	}

	.netz-sidebar__label {
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
	}

	.netz-sidebar__badge {
		flex-shrink: 0;
		font-size: 11px;
		font-weight: 600;
		padding: 1px 6px;
		border-radius: 9999px;
		background: var(--netz-brand-primary, #2563eb);
		color: #ffffff;
		line-height: 1.4;
	}

	.netz-sidebar__children {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.netz-sidebar__toggle {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		height: 44px;
		border: none;
		border-top: 1px solid var(--netz-border, #e5e7eb);
		background: transparent;
		color: var(--netz-text-muted, #9ca3af);
		cursor: pointer;
		transition: color 120ms ease;
	}

	.netz-sidebar__toggle:hover {
		color: var(--netz-text-primary, #111827);
	}

	.netz-sidebar__toggle-icon {
		transition: transform 200ms ease;
	}

	.netz-sidebar__toggle-icon.rotated {
		transform: rotate(180deg);
	}
</style>
