<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Column } from "@tanstack/svelte-table";

	interface Props {
		column: Column<any, any>;
		title: string;
		class?: string;
	}

	let { column, title, class: className }: Props = $props();
</script>

{#if column.getCanSort()}
	<button
		class={cn("flex items-center gap-1 hover:opacity-80", className)}
		onclick={() => column.toggleSorting(column.getIsSorted() === "asc")}
	>
		{title}
		{#if column.getIsSorted() === "asc"}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="12"
				height="12"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"><path d="m5 15 7-7 7 7" /></svg
			>
		{:else if column.getIsSorted() === "desc"}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="12"
				height="12"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"><path d="m19 9-7 7-7-7" /></svg
			>
		{:else}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="12"
				height="12"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				opacity="0.4"><path d="m7 15 5 5 5-5" /><path d="m7 9 5-5 5 5" /></svg
			>
		{/if}
	</button>
{:else}
	<span class={className}>{title}</span>
{/if}
