<!--
  IpsSummaryStrip.svelte
  ======================

  Dense identifier bar for the allocation page. Answers "which IPS am
  I looking at" in a single horizontal strip; complements the numerical
  KPI row below. All pills are read-only.

  Reads data already returned by ``GET /portfolio/profiles/{profile}/
  strategic-allocation``; no new endpoint.

  Source: docs/plans/2026-04-19-netz-terminal-parity-builder-macro-screener.md §B.7.
-->
<script lang="ts">
	import {
		TerminalPill,
		formatPercent,
		formatRelativeDate,
	} from "@investintell/ui";
	import type { AllocationProfile } from "$wealth/types/allocation-page";

	interface Props {
		cvarLimit: number | null;
		lastApprovedAt: string | null;
		lastApprovedBy: string | null;
		profile: AllocationProfile;
		cadenceLabel?: string;
		class?: string;
	}

	let {
		cvarLimit,
		lastApprovedAt,
		lastApprovedBy,
		profile,
		cadenceLabel = "Quarterly review",
		class: className,
	}: Props = $props();

	const PROFILE_PILL_LABEL: Record<AllocationProfile, string> = {
		conservative: "Conservative",
		moderate: "Moderate",
		growth: "Growth",
	};

	const cvarPillLabel = $derived(
		cvarLimit !== null ? `CVaR ≤ ${formatPercent(cvarLimit)}` : "CVaR ≤ —",
	);

	const approvedPillLabel = $derived.by(() => {
		if (!lastApprovedAt) return "Never approved";
		const relative = formatRelativeDate(lastApprovedAt);
		if (lastApprovedBy) return `Approved ${relative} · ${lastApprovedBy}`;
		return `Approved ${relative}`;
	});
</script>

<div class="ips-summary-strip {className ?? ''}" role="group" aria-label="IPS summary">
	<span class="ips-summary-strip__label">IPS SUMMARY</span>
	<div class="ips-summary-strip__pills">
		<TerminalPill
			label={`Profile: ${PROFILE_PILL_LABEL[profile]}`}
			tone="neutral"
			size="xs"
		/>
		<TerminalPill
			label={cvarPillLabel}
			tone={cvarLimit !== null ? "accent" : "neutral"}
			size="xs"
		/>
		<TerminalPill
			label={approvedPillLabel}
			tone={lastApprovedAt ? "success" : "neutral"}
			size="xs"
		/>
		<TerminalPill label={cadenceLabel} tone="neutral" size="xs" />
	</div>
</div>

<style>
	.ips-summary-strip {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding: var(--terminal-space-2) 0;
		border-top: var(--terminal-border-hairline);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}
	.ips-summary-strip__label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}
	.ips-summary-strip__pills {
		display: flex;
		flex-wrap: wrap;
		gap: var(--terminal-space-2);
	}
</style>
