<script lang="ts">
	import { Button } from "$lib/components/ui/button";
	import { cn } from "../../utils/cn.js";

	/**
	 * Actionable error state for detail panels.
	 *
	 * Stability Guardrails §3.4 — the "failed" slot component of the
	 * Route Data Contract + `<svelte:boundary>` pattern. Never leave
	 * the user staring at a black screen.
	 *
	 * Usage from a `+page.svelte`:
	 *
	 *   <svelte:boundary>
	 *     <FundDetailPanel data={routeData.data} />
	 *     {#snippet failed(error, reset)}
	 *       <PanelErrorState
	 *         title="Could not load this fund"
	 *         message={error.message}
	 *         onRetry={reset}
	 *       />
	 *     {/snippet}
	 *   </svelte:boundary>
	 *
	 * Or from a `+page.server.ts` load that returned a RouteError:
	 *
	 *   {#if routeData.error}
	 *     <PanelErrorState
	 *       title="Could not load this fund"
	 *       message={routeData.error.message}
	 *       onRetry={routeData.error.recoverable ? () => invalidate() : undefined}
	 *     />
	 *   {/if}
	 */

	interface Props {
		title: string;
		message?: string;
		/** Optional retry callback. Hide the button if omitted. */
		onRetry?: () => void;
		/** Optional label override for the retry button. */
		retryLabel?: string;
		class?: string;
	}

	let {
		title,
		message,
		onRetry,
		retryLabel = "Try again",
		class: className,
	}: Props = $props();
</script>

<div
	role="alert"
	class={cn(
		"flex flex-col items-center justify-center rounded-(--ii-radius-lg) border border-(--ii-danger-subtle) bg-(--ii-surface-panel) px-6 py-12 text-center",
		className,
	)}
>
	<div
		class="mb-5 flex h-16 w-16 items-center justify-center rounded-(--ii-radius-lg) border border-(--ii-danger-subtle) bg-(--ii-danger-surface) text-(--ii-danger) shadow-(--ii-shadow-1)"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="28"
			height="28"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="1.5"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"
		>
			<circle cx="12" cy="12" r="10" />
			<line x1="12" y1="8" x2="12" y2="12" />
			<line x1="12" y1="16" x2="12.01" y2="16" />
		</svg>
	</div>
	<h3 class="text-base font-semibold tracking-[-0.015em] text-(--ii-text-primary)">
		{title}
	</h3>
	{#if message}
		<p class="mt-2 max-w-[48ch] text-sm leading-6 text-(--ii-text-secondary)">
			{message}
		</p>
	{/if}
	{#if onRetry}
		<Button class="mt-5" variant="outline" onclick={onRetry}>
			{retryLabel}
		</Button>
	{/if}
</div>
