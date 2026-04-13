<!--
  DDQueueCard — terminal-native kanban card for a single DD report.

  Renders as a keyboard-accessible <button> with instrument label,
  status badge, version, confidence score, and decision anchor.
  Terminal tokens only — no shadcn, no hex values.
-->
<script lang="ts">
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import LiveDot from "$lib/components/terminal/data/LiveDot.svelte";

	interface DDQueueCardProps {
		id: string;
		instrumentId: string;
		instrumentLabel: string | null;
		status: string;
		version: number;
		confidenceScore: number | null;
		decisionAnchor: string | null;
		createdAt: string;
		approvedAt: string | null;
		onClick: () => void;
	}

	let {
		instrumentLabel,
		status,
		version,
		confidenceScore,
		decisionAnchor,
		createdAt,
		onClick,
	}: DDQueueCardProps = $props();

	const STATUS_LABELS: Record<string, string> = {
		draft: "Queued",
		generating: "Generating...",
		pending_approval: "Pending Review",
		approved: "Approved",
		rejected: "Rejected",
		failed: "Failed",
	};

	const STATUS_COLORS: Record<string, string> = {
		draft: "var(--terminal-fg-secondary)",
		generating: "var(--terminal-accent-amber)",
		pending_approval: "var(--terminal-accent-cyan)",
		approved: "var(--terminal-status-success)",
		rejected: "var(--terminal-status-error)",
		failed: "var(--terminal-status-error)",
	};

	const ANCHOR_LABELS: Record<string, { text: string; color: string }> = {
		APPROVE: { text: "Recommend Approve", color: "var(--terminal-status-success)" },
		REJECT: { text: "Recommend Reject", color: "var(--terminal-status-error)" },
		CONDITIONAL: { text: "Conditional", color: "var(--terminal-accent-amber)" },
	};

	const statusLabel = $derived(STATUS_LABELS[status] ?? status);
	const statusColor = $derived(STATUS_COLORS[status] ?? "var(--terminal-fg-secondary)");
	const isGenerating = $derived(status === "generating");
	const anchor = $derived(decisionAnchor ? ANCHOR_LABELS[decisionAnchor] ?? null : null);
</script>

<button
	class="dqc-card"
	type="button"
	onclick={onClick}
	aria-label={`${instrumentLabel ?? "Unknown Fund"} — ${statusLabel}`}
>
	<span class="dqc-label">{instrumentLabel ?? "Unknown Fund"}</span>

	<span class="dqc-meta">
		<span class="dqc-version">v{version}</span>
		<span class="dqc-status" style:color={statusColor}>{statusLabel}</span>
		{#if isGenerating}
			<LiveDot status="warn" pulse label="Generating" />
		{/if}
	</span>

	<span class="dqc-date">{formatDateTime(createdAt)}</span>

	{#if confidenceScore !== null || anchor}
		<span class="dqc-bottom">
			{#if confidenceScore !== null}
				<span class="dqc-conf">CONF: {formatPercent(confidenceScore / 100, 0)}</span>
			{/if}
			{#if anchor}
				<span class="dqc-anchor" style:color={anchor.color}>{anchor.text}</span>
			{/if}
		</span>
	{/if}
</button>

<style>
	.dqc-card {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		width: 100%;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		background: var(--terminal-bg-surface);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		text-align: left;
		cursor: pointer;
		transition: border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.dqc-card:hover {
		border-color: var(--terminal-accent-amber);
	}

	.dqc-card:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -1px;
	}

	.dqc-label {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		color: var(--terminal-fg-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dqc-meta {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
	}

	.dqc-version {
		color: var(--terminal-fg-tertiary);
		font-weight: 600;
	}

	.dqc-status {
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.dqc-date {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	.dqc-bottom {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
	}

	.dqc-conf {
		font-weight: 600;
		color: var(--terminal-fg-secondary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.dqc-anchor {
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
</style>
