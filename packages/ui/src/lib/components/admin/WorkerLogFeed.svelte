<!--
  WorkerLogFeed — Live SSE stream of worker logs with severity filtering.
  Migrated from frontends/admin to @netz/ui for reuse across verticals.
  Accepts apiBaseUrl as prop instead of reading from import.meta.env.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { formatDateTime } from "../../utils/format.js";
	import { createSSEStream, type SSEConnection } from "../../utils/sse-client.svelte.js";

	type WorkerLogSeverity = "critical" | "error" | "warning" | "info" | "debug";
	type SeverityFilter = "all" | WorkerLogSeverity;

	type WorkerLogEntry = {
		id: string;
		message: string;
		severity: WorkerLogSeverity;
		source: string | null;
		timestamp: string | null;
		raw: string;
	};

	let {
		token,
		apiBaseUrl,
	}: {
		token: string;
		apiBaseUrl: string;
	} = $props();

	const MAX_LINES = 100;
	const severityFilters = ["all", "critical", "error", "warning", "info", "debug"] as const;

	let connection = $state<SSEConnection<WorkerLogEntry> | null>(null);
	let logs = $state<WorkerLogEntry[]>([]);
	let severityFilter = $state<SeverityFilter>("all");
	let searchQuery = $state("");
	let autoScroll = $state(true);
	let logContainer: HTMLDivElement | undefined = $state();
	let nextLogId = 0;

	const severityMeta: Record<
		WorkerLogSeverity,
		{ label: string; tone: string }
	> = {
		critical: { label: "Critical", tone: "var(--netz-danger)" },
		error: { label: "Error", tone: "var(--netz-danger)" },
		warning: { label: "Warning", tone: "var(--netz-warning)" },
		info: { label: "Info", tone: "var(--netz-info)" },
		debug: { label: "Debug", tone: "var(--netz-text-secondary)" },
	};

	function normalizeSeverity(value: unknown): WorkerLogSeverity | null {
		const normalized = String(value ?? "").trim().toLowerCase();
		if (!normalized) return null;
		if (normalized === "critical" || normalized === "fatal") return "critical";
		if (normalized === "error" || normalized === "err") return "error";
		if (normalized === "warning" || normalized === "warn") return "warning";
		if (normalized === "info" || normalized === "information") return "info";
		if (normalized === "debug" || normalized === "trace") return "debug";
		return null;
	}

	function inferSeverity(message: string): WorkerLogSeverity {
		const lower = message.toLowerCase();
		if (lower.includes("critical") || lower.includes("fatal")) return "critical";
		if (lower.includes("error") || lower.includes("failed") || lower.includes("exception")) {
			return "error";
		}
		if (lower.includes("warn")) return "warning";
		if (lower.includes("debug") || lower.includes("trace")) return "debug";
		return "info";
	}

	function coerceMessage(payload: unknown, raw: string): string {
		if (typeof payload === "string") return payload.trim() || raw;
		if (payload && typeof payload === "object") {
			const record = payload as Record<string, unknown>;
			const candidate = record.message ?? record.msg ?? record.text ?? record.log ?? record.detail;
			if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
		}
		return raw;
	}

	function coerceTimestamp(payload: unknown): string | null {
		if (!payload || typeof payload !== "object") return null;
		const record = payload as Record<string, unknown>;
		const candidate =
			record.timestamp ??
			record.created_at ??
			record.createdAt ??
			record.time ??
			record.ts ??
			null;
		return typeof candidate === "string" && candidate.trim() ? candidate.trim() : null;
	}

	function coerceSource(payload: unknown): string | null {
		if (!payload || typeof payload !== "object") return null;
		const record = payload as Record<string, unknown>;
		const candidate =
			record.worker ?? record.source ?? record.name ?? record.service ?? record.component ?? null;
		return typeof candidate === "string" && candidate.trim() ? candidate.trim() : null;
	}

	function parseWorkerLogEvent(rawData: string): WorkerLogEntry | null {
		const raw = rawData.trim();
		if (!raw) return null;

		let payload: unknown = raw;
		if (raw.startsWith("{") || raw.startsWith("[")) {
			try {
				payload = JSON.parse(raw) as unknown;
			} catch {
				payload = raw;
			}
		}

		const message = coerceMessage(payload, raw);
		const severity =
			normalizeSeverity(
				payload && typeof payload === "object"
					? (payload as Record<string, unknown>).severity ??
							(payload as Record<string, unknown>).level ??
							(payload as Record<string, unknown>).status
					: null,
			) ?? inferSeverity(message);

		return {
			id: `${Date.now()}-${nextLogId++}`,
			message,
			severity,
			source: coerceSource(payload),
			timestamp: coerceTimestamp(payload),
			raw,
		};
	}

	function appendLog(entry: WorkerLogEntry) {
		logs = [...logs, entry].slice(-MAX_LINES);
	}

	function startStream() {
		if (connection) {
			connection.disconnect();
		}

		const nextConnection = createSSEStream<WorkerLogEntry>({
			url: `${apiBaseUrl}/admin/health/workers/logs`,
			getToken: () => Promise.resolve(token),
			parseEvent: parseWorkerLogEvent,
			onEvent: appendLog,
			onError: () => {
				// The shared SSE client handles retries; the UI only reflects the latest state.
			},
		} as any);

		connection = nextConnection;
		nextConnection.connect();
	}

	function stopStream() {
		connection?.disconnect();
		connection = null;
	}

	function handleScroll() {
		if (!logContainer) return;
		const { scrollTop, scrollHeight, clientHeight } = logContainer;
		autoScroll = scrollHeight - scrollTop - clientHeight < 50;
	}

	$effect(() => {
		if (autoScroll && logContainer && logs.length > 0) {
			logContainer.scrollTop = logContainer.scrollHeight;
		}
	});

	const visibleLogs = $derived(
		logs.filter((entry) => {
			if (severityFilter !== "all" && entry.severity !== severityFilter) {
				return false;
			}

			const query = searchQuery.trim().toLowerCase();
			if (!query) return true;

			return [entry.message, entry.source, entry.raw].some((value) =>
				value?.toLowerCase().includes(query),
			);
		}),
	);
	const isLive = $derived(
		connection?.status === "connected" || connection?.status === "connecting",
	);
	const connectionTone = $derived.by(() => {
		switch (connection?.status) {
			case "connected":
				return "var(--netz-success)";
			case "connecting":
				return "var(--netz-warning)";
			case "error":
				return "var(--netz-danger)";
			default:
				return "var(--netz-text-muted)";
		}
	});

	const logCounts = $derived(
		logs.reduce(
			(acc, entry) => {
				acc[entry.severity]++;
				return acc;
			},
			{
				critical: 0,
				error: 0,
				warning: 0,
				info: 0,
				debug: 0,
			} satisfies Record<WorkerLogSeverity, number>,
		),
	);

	onMount(() => {
		startStream();
		return stopStream;
	});
</script>

<div class="space-y-3">
	<div class="flex flex-wrap items-center gap-2">
		<div class="flex items-center gap-2 rounded-full border border-(--netz-border) bg-(--netz-surface) px-3 py-1 text-xs text-(--netz-text-secondary)">
			<span class="h-2 w-2 rounded-full" style={`background-color: ${connectionTone};`}></span>
			<span>{connection?.status ?? "disconnected"}</span>
			<span>•</span>
			<span>{visibleLogs.length} shown</span>
			<span>•</span>
			<span>{logs.length} buffered</span>
		</div>
		<button
			type="button"
			onclick={isLive ? stopStream : startStream}
			class="rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-1 text-xs text-(--netz-text-primary) hover:bg-(--netz-surface-alt)"
		>
			{isLive ? "Disconnect" : "Reconnect"}
		</button>

		{#if connection?.error}
			<p class="text-xs text-(--netz-danger)">{connection.error.message}</p>
		{/if}
	</div>

	<div class="flex flex-wrap items-center gap-2">
		<div class="flex flex-wrap gap-2">
			{#each severityFilters as severity (severity)}
				<button
					type="button"
					onclick={() => (severityFilter = severity)}
					class={`rounded-full border px-3 py-1 text-xs transition ${
						severityFilter === severity
							? "border-(--netz-brand-primary) bg-(--netz-brand-primary) text-white"
							: "border-(--netz-border) bg-(--netz-surface) text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)"
					}`}
				>
					{severity === "all"
						? `All (${logs.length})`
						: `${severityMeta[severity].label} (${logCounts[severity]})`}
				</button>
			{/each}
		</div>

		<input
			type="search"
			class="min-w-0 flex-1 rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary) placeholder:text-(--netz-text-muted) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--netz-brand-secondary)"
			bind:value={searchQuery}
			placeholder="Search worker logs"
		/>
	</div>

	<div
		bind:this={logContainer}
		onscroll={handleScroll}
		class="max-h-[28rem] overflow-auto rounded-xl border border-(--netz-border) bg-(--netz-surface)"
		role="log"
		aria-live="polite"
		aria-relevant="additions text"
	>
		{#if visibleLogs.length > 0}
			<div class="divide-y divide-(--netz-border)">
				{#each visibleLogs as entry (entry.id)}
					<article class="border-l-4 px-4 py-3" style={`border-left-color: ${severityMeta[entry.severity].tone};`}>
						<div class="flex flex-wrap items-start gap-3">
							<span
								class="rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
								style={`border-color: ${severityMeta[entry.severity].tone}; background-color: color-mix(in srgb, ${severityMeta[entry.severity].tone} 12%, var(--netz-surface)); color: ${severityMeta[entry.severity].tone};`}
							>
								{severityMeta[entry.severity].label}
							</span>
							<div class="min-w-0 flex-1">
								<p class="break-words font-mono text-xs text-(--netz-text-primary)">
									{entry.message}
								</p>
								<div class="mt-1 flex flex-wrap gap-3 text-[11px] text-(--netz-text-muted)">
									{#if entry.source}
										<span>{entry.source}</span>
									{/if}
									{#if entry.timestamp}
										<time datetime={entry.timestamp}>
											{formatDateTime(entry.timestamp, "en-US")}
										</time>
									{/if}
								</div>
							</div>
						</div>
					</article>
				{/each}
			</div>
		{:else}
			<div class="px-4 py-8 text-sm text-(--netz-text-muted)">
				No logs yet. The feed connects automatically when this panel loads.
			</div>
		{/if}
	</div>
</div>
