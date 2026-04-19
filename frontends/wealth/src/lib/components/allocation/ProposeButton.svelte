<!--
  PR-A26.3 Section E — Propose CTA panel with SSE progress.

  Click → POST /propose-allocation → open SSE stream via fetch +
  ReadableStream (never EventSource, per CLAUDE.md) → map event types
  to human-readable progress lines → refetch latest-proposal on
  completion. User can navigate away; the propose run completes in
  the DB regardless.

  PR-4a — the SSE stream drives a live CascadeTimeline inside the
  progress area. The three phase entries are seeded on propose start
  and mutated in place as ``optimizer_phase_complete`` events arrive
  (see §G.BUILDER.4 — mutate in place, don't remount the component).
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { Loader2, Wand2 } from "lucide-svelte";
	import CascadeTimeline from "./CascadeTimeline.svelte";
	import type {
		AllocationProfile,
		CascadePhaseAttempt,
		JobCreatedResponse,
	} from "$wealth/types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		cvarLimit: number;
		onCompleted: () => Promise<void> | void;
		apiPost: <T>(path: string, body?: unknown) => Promise<T>;
		getToken: () => Promise<string>;
		apiBase: string;
	}

	let {
		profile,
		cvarLimit,
		onCompleted,
		apiPost,
		getToken,
		apiBase,
	}: Props = $props();

	const LIVE_PHASES: readonly string[] = [
		"phase_1_ru_max_return",
		"phase_2_ru_robust",
		"phase_3_min_cvar",
	];

	function seedPhases(): CascadePhaseAttempt[] {
		return LIVE_PHASES.map((phase) => ({
			phase,
			status: "pending",
			solver: null,
			wall_ms: 0,
			objective_value: null,
			cvar_within_limit: null,
		}));
	}

	let running = $state(false);
	let statusText = $state("");
	let errorMsg = $state<string | null>(null);
	let livePhases = $state<CascadePhaseAttempt[]>([]);

	const EVENT_LABELS: Record<string, string> = {
		propose_started: "Preparing universe…",
		optimizer_started: "Optimizing…",
		optimizer_phase_complete: "Optimizer phase complete",
		propose_ready: "Proposal ready",
		propose_cvar_infeasible: "Proposal ready (CVaR infeasible)",
		completed: "Finalizing…",
	};

	function applyPhaseEvent(rawPayload: string): void {
		if (!rawPayload) return;
		let parsed: unknown;
		try {
			parsed = JSON.parse(rawPayload);
		} catch {
			return;
		}
		if (!parsed || typeof parsed !== "object") return;
		const record = parsed as Record<string, unknown>;
		const phase = typeof record.phase === "string" ? record.phase : null;
		const status = typeof record.status === "string" ? record.status : null;
		if (!phase || !status) return;
		const idx = livePhases.findIndex((p) => p.phase === phase);
		if (idx === -1) return;
		livePhases[idx] = {
			...livePhases[idx]!,
			status,
			objective_value:
				typeof record.objective_value === "number"
					? record.objective_value
					: livePhases[idx]!.objective_value,
		};
	}

	async function streamProgress(sseUrl: string): Promise<void> {
		const token = await getToken();
		const absolute = sseUrl.startsWith("http")
			? sseUrl
			: new URL(sseUrl.replace(/^\//, ""), apiBase.replace(/\/$/, "") + "/").toString();
		const resp = await fetch(absolute, {
			headers: {
				Authorization: `Bearer ${token}`,
				Accept: "text/event-stream",
			},
		});
		if (!resp.ok || !resp.body) {
			throw new Error(`SSE stream failed (${resp.status})`);
		}

		const reader = resp.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";

		while (running) {
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			const lines = buffer.split(/\n\n/);
			buffer = lines.pop() ?? "";
			for (const chunk of lines) {
				let eventName = "message";
				const dataLines: string[] = [];
				for (const line of chunk.split("\n")) {
					if (line.startsWith("event:")) eventName = line.slice(6).trim();
					else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
				}
				const label = EVENT_LABELS[eventName];
				if (label) statusText = label;
				if (eventName === "optimizer_phase_complete") {
					applyPhaseEvent(dataLines.join("\n"));
				}
				if (
					eventName === "completed" ||
					eventName === "propose_ready" ||
					eventName === "propose_cvar_infeasible"
				) {
					try {
						reader.cancel();
					} catch {
						/* noop */
					}
					return;
				}
				if (eventName === "error" || eventName === "failed") {
					const payload = dataLines.join("\n");
					throw new Error(payload || "Propose failed");
				}
			}
		}
	}

	async function propose(): Promise<void> {
		running = true;
		errorMsg = null;
		statusText = "Starting…";
		livePhases = seedPhases();
		try {
			const resp = await apiPost<JobCreatedResponse>(
				`/portfolio/profiles/${profile}/propose-allocation`,
				{},
			);
			await streamProgress(resp.sse_url);
			statusText = "Proposal complete";
			await onCompleted();
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : "Propose failed";
		} finally {
			running = false;
		}
	}
</script>

<section class="rounded-lg border border-border bg-card p-5">
	<div class="flex items-start gap-3 mb-3">
		<span class="p-2 rounded-md bg-primary/10 text-primary">
			<Wand2 class="w-4 h-4" />
		</span>
		<div>
			<h2 class="text-base font-medium text-foreground">Generate New Proposal</h2>
			<p class="text-sm text-muted-foreground mt-1">
				The optimizer will propose a CVaR-optimal allocation given your current
				<strong>{formatPercent(cvarLimit)}</strong> risk limit and any active overrides.
			</p>
		</div>
	</div>

	<button
		type="button"
		class="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
		onclick={() => void propose()}
		disabled={running}
	>
		{#if running}
			<Loader2 class="w-4 h-4 animate-spin" />
			<span>Proposing…</span>
		{:else}
			<span>Propose Allocation</span>
		{/if}
	</button>

	{#if running || statusText}
		<p class="mt-3 text-xs text-muted-foreground">{statusText}</p>
	{/if}
	{#if livePhases.length > 0}
		<div class="mt-3">
			<CascadeTimeline phases={livePhases} mode="live" />
		</div>
	{/if}
	{#if errorMsg}
		<p class="mt-2 text-xs text-destructive">{errorMsg}</p>
	{/if}
</section>
