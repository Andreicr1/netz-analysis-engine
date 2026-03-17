<!--
  Worker Log Feed — SSE stream of worker logs with ring buffer.
  Uses fetch() + ReadableStream (NOT EventSource — auth headers needed).
  Client-side ring buffer: 1,000 lines max (prevents DOM bloat).
-->
<script lang="ts">
	import { onDestroy } from "svelte";

	let { token }: { token: string } = $props();

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
	const MAX_LINES = 1000;

	let logs = $state<string[]>([]);
	let connected = $state(false);
	let error = $state<string | null>(null);
	let autoScroll = $state(true);
	let logContainer: HTMLDivElement | undefined = $state();
	let abortController: AbortController | null = null;

	function addLog(line: string) {
		logs.push(line);
		if (logs.length > MAX_LINES) {
			logs = logs.slice(-MAX_LINES);
		}
	}

	async function connect() {
		if (abortController) {
			abortController.abort();
		}
		abortController = new AbortController();
		error = null;

		try {
			const res = await fetch(`${API_BASE}/admin/health/workers/logs`, {
				headers: { Authorization: `Bearer ${token}` },
				signal: abortController.signal,
			});

			if (!res.ok || !res.body) {
				error = `Connection failed (${res.status})`;
				return;
			}

			connected = true;
			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					if (line.startsWith("data:")) {
						const data = line.slice(5).trim();
						if (data && data !== "") {
							addLog(data);
						}
					}
				}
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === "AbortError") return;
			error = "Connection lost";
			connected = false;
			// Reconnect after 3s
			setTimeout(connect, 3000);
		}
	}

	function stop() {
		if (abortController) {
			abortController.abort();
			abortController = null;
		}
		connected = false;
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

	onDestroy(stop);
</script>

<div class="space-y-2">
	<div class="flex items-center gap-2">
		{#if !connected}
			<button
				onclick={connect}
				class="rounded bg-[var(--netz-brand-primary)] px-3 py-1 text-xs text-white hover:opacity-90"
			>
				Connect
			</button>
		{:else}
			<button
				onclick={stop}
				class="rounded bg-[var(--netz-border)] px-3 py-1 text-xs text-[var(--netz-text-primary)] hover:opacity-90"
			>
				Disconnect
			</button>
		{/if}
		<span class="text-xs text-[var(--netz-text-muted)]">
			{connected ? "Connected" : "Disconnected"} · {logs.length} lines
		</span>
		{#if error}
			<span class="text-xs text-red-500">{error}</span>
		{/if}
	</div>

	<div
		bind:this={logContainer}
		onscroll={handleScroll}
		class="h-64 overflow-auto rounded border border-[var(--netz-border)] bg-[var(--netz-surface)] p-2 font-mono text-xs"
	>
		{#each logs as line}
			<div class="text-[var(--netz-text-secondary)]">{line}</div>
		{/each}
		{#if logs.length === 0}
			<div class="text-[var(--netz-text-muted)]">
				No logs yet. Click "Connect" to start streaming.
			</div>
		{/if}
	</div>
</div>
