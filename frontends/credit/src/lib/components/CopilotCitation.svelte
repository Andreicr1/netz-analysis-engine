<!--
  @component CopilotCitation
  Displays a source document citation with page number.
-->
<script lang="ts">
	import type { Citation } from "$lib/types/api";
	let { citation }: { citation: Citation } = $props();
	let c = $derived(citation);
</script>

<a
	href={String(c.url ?? "#")}
	class="mt-1 block rounded border border-(--netz-border) bg-(--netz-surface-alt) px-2 py-1 text-xs text-(--netz-text-secondary) transition-colors hover:bg-(--netz-border)"
	target="_blank"
	rel="noopener noreferrer"
>
	{c.document_title ?? c.source ?? "Source document"}
	{#if c.page_number}
		<span class="text-(--netz-text-muted)">— p.{c.page_number}</span>
	{/if}
</a>
