<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface Props {
		title: string;
		subtitle?: string;
		collapsible?: boolean;
		collapsed?: boolean;
		loading?: boolean;
		class?: string;
		actions?: Snippet;
		children: Snippet;
	}

	let {
		title,
		subtitle,
		collapsible = false,
		collapsed = $bindable(false),
		loading = false,
		class: className,
		actions,
		children,
	}: Props = $props();

	function toggle() {
		if (collapsible) collapsed = !collapsed;
	}
</script>

<section
	class={cn(
		"rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] shadow-sm",
		className,
	)}
>
	<!-- Header -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		class={cn(
			"flex items-center justify-between gap-3 px-5 py-4",
			collapsible && "cursor-pointer select-none",
		)}
		role={collapsible ? "button" : undefined}
		tabindex={collapsible ? 0 : -1}
		aria-expanded={collapsible ? !collapsed : undefined}
		onclick={toggle}
		onkeydown={(e) => {
			if (collapsible && (e.key === "Enter" || e.key === " ")) {
				e.preventDefault();
				toggle();
			}
		}}
	>
		<div class="min-w-0 flex-1">
			<h3 class="text-sm font-semibold text-[var(--netz-text-primary)]">{title}</h3>
			{#if subtitle}
				<p class="mt-0.5 text-xs text-[var(--netz-text-muted)]">{subtitle}</p>
			{/if}
		</div>

		<div class="flex shrink-0 items-center gap-2">
			<!-- Actions slot -->
			{#if actions}
				<!-- svelte-ignore a11y_interactive_supports_focus -->
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<div role="presentation" onclick={(e) => e.stopPropagation()}>
					{@render actions()}
				</div>
			{/if}

			<!-- Collapse chevron -->
			{#if collapsible}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					class="shrink-0 text-[var(--netz-text-muted)] transition-transform duration-200"
					style={collapsed ? "transform: rotate(-90deg);" : "transform: rotate(0deg);"}
					aria-hidden="true"
				>
					<path d="m6 9 6 6 6-6" />
				</svg>
			{/if}
		</div>
	</div>

	<!-- Body -->
	{#if !collapsed}
		<div class="relative border-t border-[var(--netz-border)] px-5 py-4">
			<!-- Loading skeleton overlay -->
			{#if loading}
				<div
					class="absolute inset-0 z-10 flex flex-col gap-3 rounded-b-lg bg-[var(--netz-surface)] p-5"
					aria-busy="true"
					aria-label="Carregando…"
				>
					<div
						class="h-4 w-3/4 animate-pulse rounded bg-[var(--netz-surface-inset)]"
					></div>
					<div
						class="h-4 w-1/2 animate-pulse rounded bg-[var(--netz-surface-inset)]"
					></div>
					<div
						class="h-4 w-2/3 animate-pulse rounded bg-[var(--netz-surface-inset)]"
					></div>
				</div>
			{/if}

			{@render children()}
		</div>
	{/if}
</section>
