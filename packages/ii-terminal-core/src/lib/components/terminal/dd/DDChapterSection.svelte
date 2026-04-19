<!--
  DDChapterSection — collapsible chapter section for DD report viewer.

  Renders chapter header with critic badge + LiveDot, expandable body
  with rendered markdown, quant_data KeyValueStrip, and evidence refs.
  Terminal tokens only — no shadcn, no hex values.
-->
<script lang="ts">
	import { formatDateTime } from "@investintell/ui";
	import LiveDot from "../../../components/terminal/data/LiveDot.svelte";
	import KeyValueStrip from "../../../components/terminal/data/KeyValueStrip.svelte";
	import { chapterTitle } from "../../../types/dd-report";
	import { renderMarkdown, flattenObject } from "../../../utils/render-markdown";

	interface DDChapterSectionProps {
		chapterTag: string;
		chapterOrder: number;
		contentMd: string | null;
		evidenceRefs: Record<string, unknown> | null;
		quantData: Record<string, unknown> | null;
		criticIterations: number;
		criticStatus: string;
		generatedAt: string | null;
		isGenerating: boolean;
		defaultOpen: boolean;
	}

	let {
		chapterTag,
		chapterOrder,
		contentMd,
		evidenceRefs,
		quantData,
		criticIterations,
		criticStatus,
		generatedAt,
		isGenerating,
		defaultOpen,
	}: DDChapterSectionProps = $props();

	// eslint-disable-next-line -- defaultOpen is intentionally captured once as initial value
	let isOpen = $state(defaultOpen);

	const displayTitle = $derived(`${chapterOrder}. ${chapterTitle(chapterTag)}`);

	const CRITIC_MAP: Record<string, { label: string; color: string }> = {
		accepted: { label: "CRITIC: PASS", color: "var(--terminal-status-success)" },
		escalated: { label: "CRITIC: FAIL", color: "var(--terminal-status-error)" },
		pending: { label: "CRITIC: PENDING", color: "var(--terminal-fg-muted)" },
	};

	const criticBadge = $derived(CRITIC_MAP[criticStatus] ?? { label: criticStatus.toUpperCase(), color: "var(--terminal-fg-muted)" });

	const hasQuant = $derived(quantData !== null && Object.keys(quantData).length > 0);
	const hasEvidence = $derived(evidenceRefs !== null && Object.keys(evidenceRefs).length > 0);

	const quantItems = $derived(
		hasQuant
			? flattenObject(quantData!).map((item) => ({
					key: item.key,
					value: item.value,
				}))
			: [],
	);

	const evidenceList = $derived(
		hasEvidence
			? Object.entries(evidenceRefs!).map(([key, val]) => ({
					key,
					value: typeof val === "string" ? val : JSON.stringify(val),
				}))
			: [],
	);

	function toggle() {
		isOpen = !isOpen;
	}
</script>

<div class="dcs-root">
	<button
		class="dcs-header"
		type="button"
		onclick={toggle}
		aria-expanded={isOpen}
	>
		<span class="dcs-chevron" class:dcs-chevron--open={isOpen}></span>
		<span class="dcs-title">{displayTitle}</span>
		<span class="dcs-badges">
			<span class="dcs-critic" style:color={criticBadge.color}>{criticBadge.label}</span>
			{#if isGenerating}
				<LiveDot status="warn" pulse label="Generating chapter" />
			{/if}
		</span>
	</button>

	{#if isOpen}
		<div class="dcs-body">
			{#if isGenerating && !contentMd}
				<div class="dcs-generating">Generating chapter content...</div>
			{:else}
				<div class="dcs-content">
					{@html renderMarkdown(contentMd)}
				</div>
			{/if}

			{#if hasQuant}
				<div class="dcs-section">
					<div class="dcs-section-label">QUANTITATIVE DATA</div>
					<KeyValueStrip items={quantItems} direction="column" />
				</div>
			{/if}

			{#if hasEvidence}
				<div class="dcs-section">
					<div class="dcs-section-label">EVIDENCE</div>
					<div class="dcs-evidence-list">
						{#each evidenceList as ref (ref.key)}
							<div class="dcs-evidence-item">
								<span class="dcs-evidence-key">{ref.key}</span>
								{#if ref.value.startsWith("http")}
									<a
										class="dcs-evidence-link"
										href={ref.value}
										target="_blank"
										rel="noopener noreferrer"
									>{ref.value}</a>
								{:else}
									<span class="dcs-evidence-value">{ref.value}</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<div class="dcs-footer">
				<span class="dcs-footer-item">Critic iterations: {criticIterations}</span>
				{#if generatedAt}
					<span class="dcs-footer-item">{formatDateTime(generatedAt)}</span>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.dcs-root {
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}

	.dcs-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		width: 100%;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		background: var(--terminal-bg-surface);
		border: none;
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		text-align: left;
		cursor: pointer;
		transition: background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.dcs-header:hover {
		background: var(--terminal-bg-panel);
	}

	.dcs-header:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -1px;
	}

	.dcs-chevron {
		display: inline-block;
		width: 0;
		height: 0;
		flex-shrink: 0;
		border-top: 4px solid transparent;
		border-bottom: 4px solid transparent;
		border-left: 5px solid var(--terminal-fg-tertiary);
		transition: transform var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.dcs-chevron--open {
		transform: rotate(90deg);
	}

	.dcs-title {
		flex: 1;
		font-size: var(--terminal-text-11);
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}

	.dcs-badges {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.dcs-critic {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.dcs-body {
		padding: var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
	}

	.dcs-generating {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		font-style: italic;
		padding: var(--terminal-space-2) 0;
	}

	.dcs-content {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-primary);
		line-height: 1.65;
	}

	/* Terminal-native overrides for rendered markdown */
	.dcs-content :global(h1),
	.dcs-content :global(h2),
	.dcs-content :global(h3) {
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
	}

	.dcs-content :global(h1) {
		font-size: var(--terminal-text-13);
		margin: var(--terminal-space-3) 0 var(--terminal-space-2);
	}

	.dcs-content :global(h2) {
		font-size: var(--terminal-text-12);
		margin: var(--terminal-space-3) 0 var(--terminal-space-2);
	}

	.dcs-content :global(h3) {
		font-size: var(--terminal-text-11);
		margin: var(--terminal-space-2) 0 var(--terminal-space-1);
	}

	.dcs-content :global(p) {
		margin: 0 0 var(--terminal-space-2);
		color: var(--terminal-fg-secondary);
	}

	.dcs-content :global(ul),
	.dcs-content :global(ol) {
		margin: 0 0 var(--terminal-space-2);
		padding-left: var(--terminal-space-4);
		color: var(--terminal-fg-secondary);
	}

	.dcs-content :global(li) {
		margin: 0 0 var(--terminal-space-1);
	}

	.dcs-content :global(strong) {
		color: var(--terminal-fg-primary);
	}

	.dcs-content :global(code) {
		font-family: var(--terminal-font-mono);
		background: var(--terminal-bg-surface);
		padding: 1px 4px;
		border-radius: var(--terminal-radius-none);
	}

	.dcs-content :global(table) {
		width: 100%;
		border-collapse: collapse;
		margin: var(--terminal-space-2) 0;
		font-size: var(--terminal-text-10);
	}

	.dcs-content :global(th),
	.dcs-content :global(td) {
		border: var(--terminal-border-hairline);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		text-align: left;
	}

	.dcs-content :global(th) {
		background: var(--terminal-bg-surface);
		font-weight: 700;
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.dcs-content :global(blockquote) {
		border-left: 2px solid var(--terminal-accent-amber);
		margin: 0 0 var(--terminal-space-2);
		padding-left: var(--terminal-space-3);
		color: var(--terminal-fg-muted);
	}

	.dcs-content :global(hr) {
		border: none;
		border-top: var(--terminal-border-hairline);
		margin: var(--terminal-space-3) 0;
	}

	.dcs-content :global(a) {
		color: var(--terminal-accent-cyan);
		text-decoration: underline;
	}

	.dcs-section {
		margin-top: var(--terminal-space-3);
		padding-top: var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
	}

	.dcs-section-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		margin-bottom: var(--terminal-space-2);
	}

	.dcs-evidence-list {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}

	.dcs-evidence-item {
		display: flex;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
	}

	.dcs-evidence-key {
		color: var(--terminal-fg-tertiary);
		flex-shrink: 0;
	}

	.dcs-evidence-link {
		color: var(--terminal-accent-cyan);
		text-decoration: underline;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dcs-evidence-value {
		color: var(--terminal-fg-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dcs-footer {
		display: flex;
		gap: var(--terminal-space-3);
		margin-top: var(--terminal-space-3);
		padding-top: var(--terminal-space-2);
		border-top: var(--terminal-border-hairline);
	}

	.dcs-footer-item {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}
</style>
