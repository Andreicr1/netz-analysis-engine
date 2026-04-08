<!--
  NarrativeHeadline — 1-sentence headline + key-point bullets from the
  Jinja2 templater output (backend Phase 3 Task 3.2). ``constraint_story``
  is rendered as a single muted paragraph beneath the bullets.
-->
<script lang="ts">
	interface Props {
		headline?: string;
		keyPoints?: string[];
		constraintStory?: string;
	}

	let { headline, keyPoints = [], constraintStory }: Props = $props();
</script>

<section class="nh-root">
	{#if headline}
		<h2 class="nh-headline">{headline}</h2>
	{/if}

	{#if keyPoints.length > 0}
		<ul class="nh-points">
			{#each keyPoints as point}
				<li>{point}</li>
			{/each}
		</ul>
	{/if}

	{#if constraintStory}
		<p class="nh-constraint">{constraintStory}</p>
	{/if}
</section>

<style>
	.nh-root {
		display: flex;
		flex-direction: column;
		gap: 16px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.nh-headline {
		margin: 0;
		font-size: 18px;
		font-weight: 700;
		line-height: 1.35;
		color: var(--ii-text-primary, #ffffff);
	}
	.nh-points {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.nh-points li {
		position: relative;
		padding-left: 16px;
		font-size: 13px;
		line-height: 1.55;
		color: var(--ii-text-secondary, #cbccd1);
	}
	.nh-points li::before {
		content: "";
		position: absolute;
		left: 0;
		top: 9px;
		width: 5px;
		height: 5px;
		border-radius: 999px;
		background: var(--ii-primary, #0177fb);
	}
	.nh-constraint {
		margin: 0;
		font-size: 12px;
		line-height: 1.55;
		color: var(--ii-text-muted, #85a0bd);
		padding: 12px 14px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
	}
</style>
