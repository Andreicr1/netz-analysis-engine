<!-- Low-frequency market events list for the Terminal shell. -->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import type { EChartsOption } from "echarts";
	import TerminalChart from "../charts/TerminalChart.svelte";

	interface Props {
		tags?: string[];
	}

	let { tags = ["regime"] }: Props = $props();

	interface MarketEventPayload {
		type: "regime_change" | "drift_alert" | "price_staleness" | "heartbeat";
		data: Record<string, unknown>;
		tags: string[];
		timestamp: string;
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
	const tagOptions = $derived(Array.from(new Set([...tags, "regime", "alert", "drift", "price_staleness"])));

	let selectedTag = $state("regime");
	let events = $state<MarketEventPayload[]>([]);
	let status = $state<"connecting" | "open" | "idle" | "error">("idle");
	let accentColor = $state("var(--terminal-accent-cyan)");

	onMount(() => {
		const style = getComputedStyle(document.documentElement);
		accentColor = style.getPropertyValue("--terminal-accent-cyan").trim() || accentColor;
	});

	$effect(() => {
		const firstTag = tags[0] ?? "regime";
		if (tags.length > 0 && !tags.includes(selectedTag)) {
			selectedTag = firstTag;
		}
	});

	$effect(() => {
		const tag = selectedTag;
		const controller = new AbortController();
		let frameBuffer = "";
		status = "connecting";
		events = [];

		function handleFrame(frame: string) {
			const dataLines = frame
				.split(/\r?\n/)
				.filter((line) => line.startsWith("data:"))
				.map((line) => line.slice(5).trimStart());
			if (dataLines.length === 0) return;
			try {
				const event = JSON.parse(dataLines.join("\n")) as MarketEventPayload;
				if (event.type === "heartbeat") return;
				events = [event, ...events].slice(0, 50);
			} catch {
				// Ignore malformed frames.
			}
		}

		function drainFrames(buffer: string): string {
			let remaining = buffer;
			while (true) {
				const idx = remaining.indexOf("\n\n");
				if (idx === -1) return remaining;
				handleFrame(remaining.slice(0, idx));
				remaining = remaining.slice(idx + 2);
			}
		}

		async function connect() {
			try {
				const token = await getToken();
				const response = await fetch(
					`${API_BASE}/market-data/events?tags=${encodeURIComponent(tag)}`,
					{
						method: "GET",
						headers: {
							Accept: "text/event-stream",
							Authorization: `Bearer ${token}`,
						},
						credentials: "include",
						signal: controller.signal,
					},
				);
				if (!response.ok || !response.body) {
					status = "error";
					return;
				}
				status = "open";
				const reader = response.body.getReader();
				const decoder = new TextDecoder("utf-8");
				while (true) {
					const { value, done } = await reader.read();
					if (done) break;
					frameBuffer += decoder.decode(value, { stream: true });
					frameBuffer = drainFrames(frameBuffer);
				}
				status = "idle";
			} catch (err) {
				status = (err as { name?: string })?.name === "AbortError" ? "idle" : "error";
			}
		}

		void connect();
		return () => controller.abort();
	});

	function eventTitle(event: MarketEventPayload): string {
		const label = event.data.label ?? event.data.regime ?? event.data.title ?? event.type;
		return String(label);
	}

	function eventDetail(event: MarketEventPayload): string {
		const detail = event.data.message ?? event.data.description ?? event.data.reason ?? "";
		return String(detail);
	}

	function displayTime(iso: string): string {
		if (!iso || iso.length < 19) return "--:--:--";
		return iso.slice(11, 19);
	}

	function sparklineData(event: MarketEventPayload): Array<[number, number]> {
		const raw = event.data.sparkline;
		if (!Array.isArray(raw)) return [];
		return raw
			.slice(-100)
			.map((value, index) => [index, Number(value)] as [number, number])
			.filter(([, value]) => Number.isFinite(value));
	}

	function optionFor(event: MarketEventPayload): EChartsOption {
		return {
			animation: false,
			grid: { left: 0, right: 0, top: 2, bottom: 2 },
			xAxis: { type: "value", show: false },
			yAxis: { type: "value", show: false, scale: true },
			series: [
				{
					name: event.type,
					type: "line",
					data: sparklineData(event),
					showSymbol: false,
					sampling: "lttb",
					lineStyle: { width: 1, color: accentColor },
					areaStyle: { opacity: 0.08, color: accentColor },
				},
			],
		};
	}
</script>

<div class="mfl-root">
	<div class="mfl-head">
		<div class="mfl-title">
			<span>MARKET EVENTS</span>
			<span class="mfl-status" class:mfl-status--open={status === "open"}>{status}</span>
		</div>
		<label class="mfl-filter">
			<span>TAG</span>
			<select bind:value={selectedTag} aria-label="Event tag">
				{#each tagOptions as option (option)}
					<option value={option}>{option.toUpperCase()}</option>
				{/each}
			</select>
		</label>
	</div>

	<div class="mfl-list">
		{#if events.length === 0}
			<div class="mfl-empty">WAITING FOR {selectedTag.toUpperCase()}</div>
		{:else}
			{#each events as event (`${event.type}:${event.timestamp}`)}
				<div class="mfl-event">
					<div class="mfl-meta">
						<span class="mfl-time">{displayTime(event.timestamp)}</span>
						<span class="mfl-badge">{event.type.replace("_", " ")}</span>
					</div>
					<div class="mfl-body">
						<div class="mfl-copy">
							<span class="mfl-event-title">{eventTitle(event)}</span>
							{#if eventDetail(event)}
								<span class="mfl-event-detail">{eventDetail(event)}</span>
							{/if}
						</div>
						<div class="mfl-chart">
							<TerminalChart
								option={optionFor(event)}
								renderer="svg"
								height={26}
								ariaLabel={`${event.type} sparkline`}
								empty={sparklineData(event).length === 0}
								emptyMessage="--"
							/>
						</div>
					</div>
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.mfl-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.mfl-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 30px;
		flex-shrink: 0;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.mfl-title,
	.mfl-filter {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
	}

	.mfl-status {
		color: var(--terminal-fg-muted);
	}

	.mfl-status--open {
		color: var(--terminal-status-success);
	}

	.mfl-filter select {
		height: 22px;
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		color: var(--terminal-fg-secondary);
		font: inherit;
		letter-spacing: 0;
	}

	.mfl-list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.mfl-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 88px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.mfl-event {
		padding: var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.mfl-meta,
	.mfl-body {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.mfl-meta {
		margin-bottom: 3px;
	}

	.mfl-time {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
	}

	.mfl-badge {
		color: var(--terminal-accent-cyan);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.mfl-copy {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}

	.mfl-event-title {
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-11);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.mfl-event-detail {
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-10);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.mfl-chart {
		width: 84px;
		height: 26px;
		flex-shrink: 0;
		overflow: hidden;
	}

	.mfl-chart :global(.terminal-chart) {
		background: transparent;
		border: 0;
	}
</style>
