<script lang="ts">
	import { cn } from "../../utils/cn.js";

	interface Props {
		retryIn?: number;
		onRetry?: () => void;
		class?: string;
	}

	let { retryIn, onRetry, class: className }: Props = $props();
</script>

<div
	class={cn(
		"fixed left-0 right-0 top-0 z-[100] flex items-center justify-center gap-3 bg-amber-500 px-4 py-2 text-sm font-medium text-white shadow-md",
		className,
	)}
	role="alert"
>
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width="16"
		height="16"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
	>
		<path
			d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"
		/>
		<path d="m6.08 9.5-3.5 1.6a1 1 0 0 0 0 1.81l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9a1 1 0 0 0 0-1.83l-3.5-1.59" />
		<path d="m6.08 14.5-3.5 1.6a1 1 0 0 0 0 1.81l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9a1 1 0 0 0 0-1.83l-3.5-1.59" />
	</svg>
	<span>Connection lost. Reconnecting...</span>
	{#if retryIn != null && retryIn > 0}
		<span class="text-white/80">({retryIn}s)</span>
	{/if}
	{#if onRetry}
		<button
			class="ml-2 rounded bg-white/20 px-2 py-0.5 text-xs font-medium transition-colors hover:bg-white/30"
			onclick={onRetry}
		>
			Retry now
		</button>
	{/if}
</div>
