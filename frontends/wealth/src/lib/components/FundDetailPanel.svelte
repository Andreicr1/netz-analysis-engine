<!--
  FundDetailPanel — slide-in detail panel for a selected fund.
  Tabs: Resumo, DD Report, Docs, Screening.
  DD report progress subscribes via SSE when an active report ID is available.
-->
<script lang="ts">
	import { ContextPanel, EmptyState, SectionCard, MetricCard, formatAUM, formatNumber, formatPercent, formatDate } from "@investintell/ui";
	import { createMountedGuard } from "@investintell/ui/runtime";
	import { humanizeMetric } from "$lib/i18n/quant-labels";
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

<ContextPanel {open} {onClose} title={fundName} width="480px">
	{#if fund}
		<!-- Fund identity row -->
		<div class="mb-5 flex items-start gap-3">
			<div class="min-w-0 flex-1">
				<p class="text-xs text-(--ii-text-muted)">{fundManager ?? "—"}</p>
				{#if fundSubcategory}
					<p class="mt-0.5 text-xs text-(--ii-text-muted)">{fundSubcategory}</p>
				{/if}
			</div>
			<div class="flex shrink-0 flex-col items-end gap-1">
				{#if fundScore !== null}
					<span class="text-lg font-bold text-(--ii-text-primary)">
						{formatNumber(fundScore, 1, "pt-BR")}
					</span>
					<span class="text-xs text-(--ii-text-muted)">Score</span>
				{/if}
			</div>
		</div>

		<!-- Tabs -->
		<Tabs.Root bind:value={activeTab}>
			<Tabs.List>
				{#each tabs as tab (tab.value)}
					<Tabs.Trigger value={tab.value}>{tab.label}</Tabs.Trigger>
				{/each}
			</Tabs.List>

			<!-- Tab: Resumo -->
			<Tabs.Content value="resumo">
				<div class="space-y-4">
					<!-- Key metrics -->
					<div class="grid grid-cols-2 gap-3">
						<MetricCard label="AUM" value={formatAum(fundAum)} />
						<MetricCard
							label="Score Geral"
							value={formatNumber(fundScore, 1, "pt-BR")}
						/>
						{#if fundAnnualReturn !== null}
							<MetricCard
								label="Retorno Anual"
								value={formatPct(fundAnnualReturn)}
							/>
						{/if}
						{#if fundSharpeRatio !== null}
							<MetricCard
								label="Sharpe"
								value={formatNumber(fundSharpeRatio, 2, "pt-BR")}
							/>
						{/if}
						{#if fundMaxDrawdown !== null}
							<MetricCard
								label={humanizeMetric("max_drawdown")}
								value={formatPct(fundMaxDrawdown)}
							/>
						{/if}
						{#if fundCvar95 !== null}
							<MetricCard
								label={humanizeMetric("cvar_95")}
								value={formatPct(fundCvar95)}
							/>
						{/if}
					</div>

					<!-- Fund metadata -->
					<SectionCard title="Informações">
						{#snippet children()}
							<dl class="space-y-2 text-sm">
								{#if fundIsin}
									<div class="flex justify-between">
										<dt class="text-(--ii-text-muted)">ISIN</dt>
										<dd class="font-mono text-(--ii-text-primary)">{fundIsin}</dd>
									</div>
								{/if}
								{#if fundCnpj}
									<div class="flex justify-between">
										<dt class="text-(--ii-text-muted)">CNPJ</dt>
										<dd class="font-mono text-(--ii-text-primary)">{fundCnpj}</dd>
									</div>
								{/if}
								<div class="flex justify-between">
									<dt class="text-(--ii-text-muted)">Estratégia</dt>
									<dd class="text-(--ii-text-primary)">{fundStrategy ?? "—"}</dd>
								</div>
								<div class="flex justify-between">
									<dt class="text-(--ii-text-muted)">Gestor</dt>
									<dd class="text-(--ii-text-primary)">{fundManager ?? "—"}</dd>
								</div>
								<div class="flex justify-between">
									<dt class="text-(--ii-text-muted)">Atualizado</dt>
									<dd class="text-(--ii-text-primary)">{formatDate(fundUpdatedAt, "short", "pt-BR")}</dd>
								</div>
								{#if fundInceptionDate}
									<div class="flex justify-between">
										<dt class="text-(--ii-text-muted)">Início</dt>
										<dd class="text-(--ii-text-primary)">{formatDate(fundInceptionDate, "short", "pt-BR")}</dd>
									</div>
								{/if}
							</dl>
						{/snippet}
					</SectionCard>
				</div>
			</Tabs.Content>

			<!-- Tab: DD Report -->
			<Tabs.Content value="dd-report">
				<div class="space-y-4">
					{#if fundDdReportStatus === "complete"}
						<div class="rounded-lg border border-(--ii-border) bg-(--ii-surface-elevated) p-4">
							<div class="mb-3 flex items-center justify-between">
								<span class="text-sm font-medium text-(--ii-text-primary)">DD Report Completo</span>
								<span
									class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
									style="background-color: color-mix(in srgb, var(--ii-success) 15%, transparent); color: var(--ii-success);"
								>
									Completo
								</span>
							</div>
							<a
								href="/library?q={encodeURIComponent(fundFundId ?? '')}"
								class="inline-flex items-center gap-1.5 rounded-md bg-(--ii-brand-primary) px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
							>
								Ver Relatório
								<svg width="14" height="14" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
									<path d="M7 13L13 7M13 7H7M13 7V13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
								</svg>
							</a>
						</div>

					{:else if fundDdReportStatus === "generating" || ddSseStatus === "streaming"}
						<div class="rounded-lg border border-(--ii-border) bg-(--ii-surface-elevated) p-4">
							<div class="mb-3 flex items-center justify-between">
								<span class="text-sm font-medium text-(--ii-text-primary)">Gerando relatório…</span>
								{#if ddProgress !== null}
									<span class="text-xs text-(--ii-text-muted)">{ddProgress}%</span>
								{/if}
							</div>
							<!-- Progress bar -->
							<Progress value={ddProgress ?? 0} max={100} class="h-1.5" />
							{#if ddProgressMessage}
								<p class="mt-2 text-xs text-(--ii-text-muted)">{ddProgressMessage}</p>
							{/if}
						</div>

					{:else if ddSseStatus === "error"}
						<EmptyState
							title="Erro na geração"
							message="Ocorreu um erro ao gerar o DD Report. Tente novamente."
						/>
					{:else}
						<EmptyState
							title="DD Report Pendente"
							message="Nenhum relatório de due diligence foi gerado para este fundo."
							actionLabel="Gerar Relatório"
							onAction={() => {}}
						/>
					{/if}
				</div>
			</Tabs.Content>

			<!-- Tab: Docs -->
			<Tabs.Content value="docs">
				<EmptyState
					title="Documentos"
					message="Os documentos deste fundo aparecerão aqui após o upload."
				/>
			</Tabs.Content>

			<!-- Tab: Screening -->
			<Tabs.Content value="screening">
				<EmptyState
					title="Screening"
					message="Os resultados de screening para este fundo aparecerão aqui após a execução do screener."
				/>
			</Tabs.Content>
		</Tabs.Root>
	{:else}
		<EmptyState title="Nenhum fundo selecionado" message="Selecione um fundo na tabela para ver os detalhes." />
	{/if}
</ContextPanel>
