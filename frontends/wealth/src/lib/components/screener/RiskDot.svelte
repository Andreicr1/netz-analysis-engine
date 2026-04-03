<script lang="ts">
	let { count }: { count: number } = $props();
</script>

{#if count > 0}
	<span
		class="inline-block h-2 w-2 rounded-full bg-destructive"
		title="{count} Disclosure{count !== 1 ? 's' : ''}"
	></span>
{/if}
