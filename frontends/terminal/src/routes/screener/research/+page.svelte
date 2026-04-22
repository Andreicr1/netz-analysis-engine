<script lang="ts">
	import "@investintell/ui/styles/surfaces/screener";
	import { getContext, onDestroy } from "svelte";
	import { PageHeader } from "@investintell/ui";
	import { createClientApiClient } from "@investintell/ii-terminal-core/api/client";
	import CorrelationHeatmap from "@investintell/ii-terminal-core/components/research/CorrelationHeatmap.svelte";
	import RiskReturnScatter from "@investintell/ii-terminal-core/components/research/RiskReturnScatter.svelte";

	interface ScatterResponse {
		instrument_ids: string[];
		names: string[];
		tickers: Array<string | null>;
		expected_returns: Array<number | null>;
		tail_risks: Array<number | null>;
		volatilities: Array<number | null>;
		strategies: string[];
		strategy_map: Record<string, string>;
		as_of_dates: Array<string | null>;
	}

	interface CorrelationResponse {
		labels: string[];
		historical_matrix: number[][];
		structural_matrix: number[][];
		regime_state_at_calc: string | null;
		effective_window_days: number;
		cache_key: string;
	}

	interface CorrelationAccepted {
		job_id: string;
		stream_url: string;
		status: "accepted";
		cache_key: string;
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);
	const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
	const apiOrigin = apiBase.replace(/\/api\/v1$/, "");

	let scatter = $state<ScatterResponse | null>(null);
	let correlation = $state<CorrelationResponse | null>(null);
	let correlationMode = $state<"structural" | "historical">("structural");
	let scatterLoading = $state(true);
	let correlationLoading = $state(true);
	let scatterError = $state<string | null>(null);
	let correlationError = $state<string | null>(null);
	let scatterController = $state<AbortController | null>(null);
	let correlationController = $state<AbortController | null>(null);
	let scatterInflight = $state(false);
	let correlationInflight = $state(false);

	function buildStreamUrl(path: string): string {
		return path.startsWith("http") ? path : `${apiOrigin}${path}`;
	}

	function abortScatter() {
		scatterController?.abort();
		scatterController = null;
		scatterInflight = false;
	}

	function abortCorrelation() {
		correlationController?.abort();
		correlationController = null;
		correlationInflight = false;
	}

	async function readSseResult(url: string, signal: AbortSignal): Promise<CorrelationResponse> {
		const token = await getToken();
		const response = await fetch(url, {
			headers: {
				Authorization: `Bearer ${token}`,
				Accept: "text/event-stream",
			},
			signal,
		});
		if (!response.ok || !response.body) {
			throw new Error(`Correlation stream failed: HTTP ${response.status}`);
		}

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";
		let currentData = "";

		try {
			while (true) {
				if (signal.aborted) throw new DOMException("Aborted", "AbortError");
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					if (line.startsWith("data:")) {
						currentData += `${currentData ? "\n" : ""}${line.slice(5).replace(/^ /, "")}`;
					} else if (line === "") {
						if (!currentData) continue;
						const event = JSON.parse(currentData) as {
							event?: string;
							result?: CorrelationResponse;
							detail?: string;
						};
						currentData = "";
						if (event.event === "done" && event.result) {
							return event.result;
						}
						if (event.event === "error") {
							throw new Error(event.detail ?? "Correlation job failed.");
						}
					}
				}
			}
		} finally {
			reader.cancel().catch(() => {});
		}

		throw new Error("Correlation stream ended before a terminal payload arrived.");
	}

	async function loadScatter() {
		abortScatter();
		const controller = new AbortController();
		scatterController = controller;
		scatterInflight = true;
		scatterLoading = true;
		scatterError = null;

		try {
			const data = await api.get<ScatterResponse>("/research/scatter?limit=80&approved_only=true", undefined, {
				signal: controller.signal,
			});
			scatter = data;
			await loadCorrelation(data.instrument_ids);
		} catch (error: unknown) {
			if (error instanceof DOMException && error.name === "AbortError") return;
			scatterError = error instanceof Error ? error.message : "Failed to load research universe.";
			scatter = null;
		} finally {
			if (scatterController === controller) {
				scatterController = null;
				scatterInflight = false;
			}
			scatterLoading = false;
		}
	}

	async function loadCorrelation(instrumentIds: string[]) {
		abortCorrelation();
		const controller = new AbortController();
		correlationController = controller;
		correlationInflight = true;
		correlationLoading = true;
		correlationError = null;
		correlation = null;

		try {
			const token = await getToken();
			const response = await fetch(`${apiBase}/research/correlation/matrix`, {
				method: "POST",
				headers: {
					Authorization: `Bearer ${token}`,
					"Content-Type": "application/json",
					Accept: "application/json",
				},
				body: JSON.stringify({
					instrument_ids: instrumentIds,
					window_days: 252,
				}),
				signal: controller.signal,
			});

			if (response.status === 202) {
				const accepted = (await response.json()) as CorrelationAccepted;
				correlation = await readSseResult(buildStreamUrl(accepted.stream_url), controller.signal);
			} else if (response.ok) {
				correlation = (await response.json()) as CorrelationResponse;
			} else {
				const detail = (await response.json().catch(() => null)) as { detail?: string } | null;
				throw new Error(detail?.detail ?? `Correlation request failed: HTTP ${response.status}`);
			}
		} catch (error: unknown) {
			if (error instanceof DOMException && error.name === "AbortError") return;
			correlationError = error instanceof Error ? error.message : "Failed to load structural correlation.";
		} finally {
			if (correlationController === controller) {
				correlationController = null;
				correlationInflight = false;
			}
			correlationLoading = false;
		}
	}

	$effect(() => {
		loadScatter();
		return () => {
			abortScatter();
			abortCorrelation();
		};
	});

	onDestroy(() => {
		abortScatter();
		abortCorrelation();
	});
</script>

<svelte:head>
	<title>Research Surface</title>
</svelte:head>

<div class="research-page">
	<PageHeader
		title="Research Surface"
		subtitle="Institutional cross-fund view of risk, return and structural linkage."
	/>

	<div class="research-grid">
		<RiskReturnScatter payload={scatter} loading={scatterLoading || scatterInflight} error={scatterError} />
		<CorrelationHeatmap
			payload={correlation}
			mode={correlationMode}
			loading={correlationLoading || correlationInflight}
			error={correlationError}
			onModeChange={(nextMode) => correlationMode = nextMode}
		/>
	</div>
</div>

<style>
	.research-page {
		display: flex;
		flex-direction: column;
		gap: 20px;
		padding: 24px;
		min-height: 100%;
		background:
			radial-gradient(circle at top left, color-mix(in srgb, var(--ii-brand-primary) 10%, transparent), transparent 36%),
			linear-gradient(180deg, var(--ii-surface), color-mix(in srgb, var(--ii-surface-elevated) 84%, transparent));
	}

	.research-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
		gap: 20px;
		align-items: start;
	}

	@media (max-width: 1120px) {
		.research-grid {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 640px) {
		.research-page {
			padding: 16px;
		}
	}
</style>
