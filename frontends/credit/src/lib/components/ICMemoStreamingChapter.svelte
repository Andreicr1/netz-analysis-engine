<!--
  @component ICMemoStreamingChapter
  Renders streaming text for an in-progress IC memo chapter with typing animation.
-->
<script lang="ts">
	let { content = "" }: { content: string } = $props();
</script>

<div class="mt-3 border-t border-[var(--netz-border)] pt-3">
	<div class="text-sm leading-relaxed text-[var(--netz-text-secondary)]">
		{content}<span class="inline-block h-4 w-0.5 animate-pulse bg-[var(--netz-primary)]"></span>
	</div>
</div>
