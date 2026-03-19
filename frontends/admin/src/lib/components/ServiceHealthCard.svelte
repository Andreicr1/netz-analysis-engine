<!--
  Service health card — shows status, latency, and error for a single service.
-->
<script lang="ts">
	import { StatusBadge, formatDateTime, formatNumber } from "@netz/ui";
	import { resolveAdminStatus } from "$lib/utils/status-maps.js";

	let {
		service,
	}: {
		service: {
			name: string;
			status: string;
			latency_ms: number | null;
			error: string | null;
			checked_at?: string | null;
		};
	} = $props();

	const statusType = $derived(
		service.status === "ok"
			? "low"
			: service.status === "degraded"
				? "medium"
				: "critical",
	);
</script>

<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-4">
	<div class="mb-2 flex items-center justify-between">
		<span class="text-sm font-medium text-[var(--netz-text-primary)]">{service.name}</span>
		<StatusBadge status={statusType} type="risk" resolve={resolveAdminStatus} />
	</div>
	{#if service.latency_ms != null}
		<p class="text-xs text-[var(--netz-text-muted)]">
			Latency: {formatNumber(service.latency_ms, 1, "en-US")}ms
		</p>
	{/if}
	{#if service.error}
		<p class="mt-1 text-xs text-[var(--netz-text-secondary)]">{service.error}</p>
	{/if}
	{#if service.checked_at}
		<p class="mt-1 text-xs text-[var(--netz-text-muted)]">
			Checked at
			<time datetime={service.checked_at}>{formatDateTime(service.checked_at, "en-US")}</time>
		</p>
	{/if}
</div>
