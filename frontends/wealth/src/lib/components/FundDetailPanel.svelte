<!--
  FundDetailPanel — slide-in detail panel for a selected fund.
  Tabs: Resumo, DD Report, Docs, Screening.
  DD report progress subscribes via SSE when an active report ID is available.
-->
<script lang="ts">
	import { ContextPanel, EmptyState, SectionCard, MetricCard, formatAUM, formatNumber, formatPercent, formatDate } from "@investintell/ui";
	import { createMountedGuard } from "@investintell/ui/runtime";
	import { humanizeMetric } from "$wealth/i18n/quant-labels";
	import { Progress } from "@investintell/ui/components/ui/progress";
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import { getContext, onDestroy, onMount } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// Mounted guard — gates every state mutation that might fire
	// after the panel has been closed/destroyed. The DD-report SSE
	// loop is async and can complete a `reader.read()` cycle in the
	// window between component teardown and the AbortController
	// landing on the underlying fetch; without this guard a late
	// `ddProgress = ...` write would crash Svelte's reactive graph
	// (the §7.2 black-screen failure mode in the design spec).
	const mounted = createMountedGuard();
	onMount(() => mounted.start());
	onDestroy(() => mounted.stop());

	// ── Types ──────────────────────────────────────────────────────────────

	type FundRow = {
		id: string;
		name: string;
		subcategory: string | null;
		manager: string | null;
		aum: number | null;
		strategy: string | null;
		status: string | null;
		dd_report_status: string | null;
		dd_report_id: string | null;
		score: number | null;
		updated_at: string | null;
		// Extended detail fields (may not be present in list response)
		isin?: string | null;
		cnpj?: string | null;
		inception_date?: string | null;
		annual_return?: number | null;
		sharpe_ratio?: number | null;
		max_drawdown?: number | null;
		cvar_95?: number | null;
	};

	type DDReportEvent = {
		type: "progress" | "complete" | "error";
		progress?: number;
		message?: string;
		report_id?: string;
	};

	type DocEntry = {
		id: string;
		name: string;
		uploaded_at: string;
	};

	// ── Props ──────────────────────────────────────────────────────────────

	interface Props {
		fund: FundRow | null;
		open: boolean;
		onClose: () => void;
	}

	let { fund, open, onClose }: Props = $props();

	// ── Defensive derived accessors ────────────────────────────────────────
	// Optional chaining everywhere — the props can flip to `null`
	// between renders when the parent unselects a row, and the
	// template body must never assume a particular field is
	// present. These accessors return safe fallbacks so the
	// surrounding `{#if fund}` guard remains the *only* required
	// truthiness check.
	const fundName = $derived(fund?.name ?? "—");
	const fundManager = $derived(fund?.manager ?? null);
	const fundSubcategory = $derived(fund?.subcategory ?? null);
	const fundScore = $derived(fund?.score ?? null);
	const fundAum = $derived(fund?.aum ?? null);
	const fundStrategy = $derived(fund?.strategy ?? null);
	const fundIsin = $derived(fund?.isin ?? null);
	const fundCnpj = $derived(fund?.cnpj ?? null);
	const fundUpdatedAt = $derived(fund?.updated_at ?? null);
	const fundInceptionDate = $derived(fund?.inception_date ?? null);
	const fundAnnualReturn = $derived(fund?.annual_return ?? null);
	const fundSharpeRatio = $derived(fund?.sharpe_ratio ?? null);
	const fundMaxDrawdown = $derived(fund?.max_drawdown ?? null);
	const fundCvar95 = $derived(fund?.cvar_95 ?? null);
	const fundDdReportId = $derived(fund?.dd_report_id ?? null);
	const fundDdReportStatus = $derived(fund?.dd_report_status ?? null);
	const fundFundId = $derived(fund?.id ?? null);

	// ── Tab state ──────────────────────────────────────────────────────────

	type Tab = "resumo" | "dd-report" | "docs" | "screening";
	let activeTab = $state<Tab>("resumo");

	const tabs: { value: Tab; label: string }[] = [
		{ value: "resumo", label: "Resumo" },
		{ value: "dd-report", label: "DD Report" },
		{ value: "docs", label: "Docs" },
		{ value: "screening", label: "Screening" },
	];

	// ── DD Report SSE ──────────────────────────────────────────────────────

	let ddProgress = $state<number | null>(null);
	let ddProgressMessage = $state<string | null>(null);
	let ddSseStatus = $state<"idle" | "streaming" | "complete" | "error">("idle");

	$effect(() => {
		const reportId = fundDdReportId;
		const ddStatus = fundDdReportStatus;
		// Only subscribe when report is actively generating
		if (!reportId || ddStatus !== "generating") return;

		// Reset visible progress through the mounted guard so the
		// reset itself is also a no-op once the panel has been
		// destroyed (paranoid but cheap).
		mounted.guard(() => {
			ddSseStatus = "streaming";
			ddProgress = null;
			ddProgressMessage = null;
		});

		const controller = new AbortController();

		(async () => {
			try {
				const token = getToken ? await getToken() : "";
				const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
				const response = await fetch(`${apiBase}/dd-reports/${reportId}/stream`, {
					headers: {
						Authorization: `Bearer ${token}`,
						Accept: "text/event-stream",
					},
					signal: controller.signal,
				});

				if (!response.ok || !response.body) {
					mounted.guard(() => {
						ddSseStatus = "error";
					});
					return;
				}

				const reader = response.body.getReader();
				const decoder = new TextDecoder();
				let buffer = "";

				// Local mirror of ddSseStatus so the inner loop can
				// observe terminal states without re-reading the
				// reactive `$state` from inside an async tick.
				let localStatus: "idle" | "streaming" | "complete" | "error" = "streaming";

				while (mounted.mounted) {
					const { done, value } = await reader.read();
					if (done) break;

					buffer += decoder.decode(value, { stream: true });
					const lines = buffer.split("\n");
					buffer = lines.pop() ?? "";

					for (const line of lines) {
						if (!line.startsWith("data: ")) continue;
						try {
							const event = JSON.parse(line.slice(6)) as DDReportEvent;
							if (event.type === "progress") {
								mounted.guard(() => {
									ddProgress = event.progress ?? null;
									ddProgressMessage = event.message ?? null;
								});
							} else if (event.type === "complete") {
								localStatus = "complete";
								mounted.guard(() => {
									ddProgress = 100;
									ddProgressMessage = "Relatório gerado com sucesso";
									ddSseStatus = "complete";
								});
								break;
							} else if (event.type === "error") {
								localStatus = "error";
								mounted.guard(() => {
									ddProgressMessage = event.message ?? "Erro na geração";
									ddSseStatus = "error";
								});
								break;
							}
						} catch {
							// malformed JSON — skip
						}
					}

					if (localStatus === "complete" || localStatus === "error") break;
				}
			} catch (err: unknown) {
				if (err instanceof DOMException && err.name === "AbortError") return;
				mounted.guard(() => {
					ddSseStatus = "error";
				});
			}
		})();

		return () => controller.abort();
	});

	// Reset tab when a new fund is selected
	$effect(() => {
		if (fund) {
			activeTab = "resumo";
		}
	});

	// ── Format helpers ─────────────────────────────────────────────────────

	function formatAum(value: number | null): string {
		return formatAUM(value, "BRL", "pt-BR");
	}

	function formatPct(value: number | null): string {
		return formatPercent(value, 2, "pt-BR", true);
	}
</script>

<ContextPanel {open} {onClose} title={fundName} width="520px" class="rounded-none font-mono text-[11px] bg-[#222]">
	{#if fund}
		<!-- Fund identity row — High density grid -->
		<div class="grid grid-cols-[1fr_auto] gap-[1px] bg-[#222] border-b border-[#222]">
			<div class="bg-black p-2 flex flex-col justify-center">
				<p class="text-[10px] uppercase tracking-tighter text-(--ii-text-muted) leading-none mb-1">MANAGER</p>
				<p class="font-bold truncate">{fundManager ?? "—"}</p>
				{#if fundSubcategory}
					<p class="mt-1 text-[10px] text-(--ii-text-muted) border-t border-[#222] pt-1">{fundSubcategory.toUpperCase()}</p>
				{/if}
			</div>
			<div class="bg-black p-2 flex flex-col items-end justify-center min-w-[80px]">
				{#if fundScore !== null}
					<p class="text-[10px] uppercase tracking-tighter text-(--ii-text-muted) leading-none mb-1">SCORE</p>
					<span class="text-xl font-black leading-none text-(--ii-brand-primary)">
						{formatNumber(fundScore, 1, "pt-BR")}
					</span>
				{/if}
			</div>
		</div>

		<!-- Tabs — Brutalist variant -->
		<Tabs.Root bind:value={activeTab} class="mt-[1px]">
			<Tabs.List class="w-full justify-start rounded-none bg-[#222] p-0 h-auto gap-[1px]">
				{#each tabs as tab (tab.value)}
					<Tabs.Trigger 
						value={tab.value} 
						class="rounded-none bg-black px-4 py-2 text-[10px] font-bold uppercase tracking-widest data-[state=active]:bg-[#222] data-[state=active]:text-white border-none h-full"
					>
						{tab.label}
					</Tabs.Trigger>
				{/each}
			</Tabs.List>

			<!-- Tab: Resumo -->
			<Tabs.Content value="resumo" class="mt-0 outline-none">
				<div class="flex flex-col gap-[1px] bg-[#222]">
					<!-- Key metrics grid -->
					<div class="grid grid-cols-3 gap-[1px]">
						<div class="bg-black p-2">
							<p class="text-[9px] uppercase font-bold text-(--ii-text-muted) mb-1">AUM (BRL)</p>
							<p class="text-xs font-bold tabular-nums">{formatAum(fundAum)}</p>
						</div>
						<div class="bg-black p-2">
							<p class="text-[9px] uppercase font-bold text-(--ii-text-muted) mb-1">ANNUAL RET</p>
							<p class="text-xs font-bold tabular-nums {fundAnnualReturn && fundAnnualReturn >= 0 ? 'text-(--ii-success)' : 'text-(--ii-danger)'}">
								{fundAnnualReturn !== null ? formatPct(fundAnnualReturn) : "—"}
							</p>
						</div>
						<div class="bg-black p-2">
							<p class="text-[9px] uppercase font-bold text-(--ii-text-muted) mb-1">SHARPE</p>
							<p class="text-xs font-bold tabular-nums">{fundSharpeRatio !== null ? formatNumber(fundSharpeRatio, 2, "pt-BR") : "—"}</p>
						</div>
						<div class="bg-black p-2">
							<p class="text-[9px] uppercase font-bold text-(--ii-text-muted) mb-1">MAX DRAWDOWN</p>
							<p class="text-xs font-bold tabular-nums text-(--ii-danger)">{fundMaxDrawdown !== null ? formatPct(fundMaxDrawdown) : "—"}</p>
						</div>
						<div class="bg-black p-2">
							<p class="text-[9px] uppercase font-bold text-(--ii-text-muted) mb-1">CVAR (95%)</p>
							<p class="text-xs font-bold tabular-nums">{fundCvar95 !== null ? formatPct(fundCvar95) : "—"}</p>
						</div>
						<div class="bg-black p-2">
							<p class="text-[9px] uppercase font-bold text-(--ii-text-muted) mb-1">UPDATED</p>
							<p class="text-[10px] font-bold uppercase">{fundUpdatedAt ? formatDate(fundUpdatedAt, "short", "pt-BR") : "—"}</p>
						</div>
					</div>

					<!-- Technical Attributes -->
					<div class="bg-black p-2">
						<p class="text-[10px] font-black uppercase tracking-widest text-white mb-2 border-b border-[#222] pb-1">TECHNICAL ATTRIBUTES</p>
						<div class="grid grid-cols-1 gap-[1px] bg-[#222]">
							{#if fundIsin}
								<div class="flex justify-between bg-black py-1 px-1">
									<dt class="text-(--ii-text-muted) uppercase text-[9px] font-bold">ISIN</dt>
									<dd class="font-mono text-white text-[10px]">{fundIsin}</dd>
								</div>
							{/if}
							{#if fundCnpj}
								<div class="flex justify-between bg-black py-1 px-1">
									<dt class="text-(--ii-text-muted) uppercase text-[9px] font-bold">CNPJ</dt>
									<dd class="font-mono text-white text-[10px]">{fundCnpj}</dd>
								</div>
							{/if}
							<div class="flex justify-between bg-black py-1 px-1">
								<dt class="text-(--ii-text-muted) uppercase text-[9px] font-bold">STRATEGY</dt>
								<dd class="text-white text-[10px] font-bold uppercase">{fundStrategy ?? "—"}</dd>
							</div>
							{#if fundInceptionDate}
								<div class="flex justify-between bg-black py-1 px-1">
									<dt class="text-(--ii-text-muted) uppercase text-[9px] font-bold">INCEPTION</dt>
									<dd class="text-white text-[10px] uppercase">{formatDate(fundInceptionDate, "short", "pt-BR")}</dd>
								</div>
							{/if}
						</div>
					</div>
				</div>
			</Tabs.Content>

			<!-- Tab: DD Report -->
			<Tabs.Content value="dd-report" class="mt-0 outline-none">
				<div class="flex flex-col gap-[1px] bg-[#222]">
					{#if fundDdReportStatus === "complete"}
						<div class="bg-black p-4 text-center">
							<p class="text-[10px] font-bold uppercase tracking-widest text-(--ii-success) mb-4">SYSTEM READY: DD REPORT AVAILABLE</p>
							<a
								href="/library?q={encodeURIComponent(fundFundId ?? '')}"
								class="inline-block w-full rounded-none bg-(--ii-brand-primary) px-4 py-3 text-[11px] font-black uppercase tracking-widest text-white hover:bg-white hover:text-black transition-colors"
							>
								ACCESS FULL ANALYSIS →
							</a>
						</div>

					{:else if fundDdReportStatus === "generating" || ddSseStatus === "streaming"}
						<div class="bg-black p-4">
							<div class="mb-2 flex items-center justify-between">
								<span class="text-[10px] font-black uppercase tracking-widest text-white">PIPELINE EXECUTION: GENERATING...</span>
								{#if ddProgress !== null}
									<span class="text-xs font-mono font-bold text-(--ii-brand-primary)">{ddProgress}%</span>
								{/if}
							</div>
							<!-- High-contrast progress bar -->
							<div class="h-1 w-full bg-[#222]">
								<div class="h-full bg-(--ii-brand-primary)" style="width: {ddProgress ?? 0}%"></div>
							</div>
							{#if ddProgressMessage}
								<p class="mt-3 text-[10px] font-mono text-(--ii-text-muted) uppercase italic">{ddProgressMessage}</p>
							{/if}
						</div>

					{:else if ddSseStatus === "error"}
						<div class="bg-black p-4 text-center">
							<p class="text-[10px] font-bold uppercase tracking-widest text-(--ii-danger)">FATAL: REPORT GENERATION FAILED</p>
						</div>
					{:else}
						<div class="bg-black p-4 text-center">
							<p class="text-[10px] font-bold uppercase tracking-widest text-(--ii-text-muted) mb-4">SYSTEM STATUS: NO REPORT GENERATED</p>
							<button
								class="w-full rounded-none border border-[#222] bg-black px-4 py-3 text-[11px] font-black uppercase tracking-widest text-white hover:bg-white hover:text-black transition-colors"
								onclick={() => {}}
							>
								INITIALIZE GENERATION
							</button>
						</div>
					{/if}
				</div>
			</Tabs.Content>

			<!-- Tab: Docs -->
			<Tabs.Content value="docs" class="mt-0 outline-none">
				<div class="bg-black p-4 text-center border-t border-[#222]">
					<p class="text-[10px] font-bold uppercase tracking-widest text-(--ii-text-muted)">DATAROOM: ZERO FILES FOUND</p>
				</div>
			</Tabs.Content>

			<!-- Tab: Screening -->
			<Tabs.Content value="screening" class="mt-0 outline-none">
				<div class="bg-black p-4 text-center border-t border-[#222]">
					<p class="text-[10px] font-bold uppercase tracking-widest text-(--ii-text-muted)">VALIDATION: SCREENING PENDING</p>
				</div>
			</Tabs.Content>
		</Tabs.Root>
	{:else}
		<div class="bg-black p-8 text-center border border-[#222]">
			<p class="text-[10px] font-black uppercase tracking-widest text-(--ii-text-muted)">AWAITING ENTITY SELECTION</p>
		</div>
	{/if}
</ContextPanel>
