<!--
  @component CopilotCitation
  Displays a source document citation with page number.
-->
<script lang="ts">
	let { citation }: { citation: unknown } = $props();
	let c = $derived(citation as Record<string, unknown>);
</script>

<a
	href={String(c.url ?? "#")}
	class="mt-1 block rounded border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] px-2 py-1 text-xs text-[var(--netz-text-secondary)] transition-colors hover:bg-[var(--netz-border)]"
	target="_blank"
	rel="noopener noreferrer"
>
	{c.document_title ?? c.source ?? "Source document"}
	{#if c.page_number}
		<span class="text-[var(--netz-text-muted)]">— p.{c.page_number}</span>
	{/if}
</a>
