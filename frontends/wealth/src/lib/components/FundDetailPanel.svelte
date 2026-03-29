<!--
  FundDetailPanel — slide-in detail panel for a selected fund.
  Tabs: Resumo, DD Report, Docs, Screening.
  DD report progress subscribes via SSE when an active report ID is available.
-->
<script lang="ts">
	import { ContextPanel, EmptyState, SectionCard, MetricCard, formatAUM, formatNumber, formatPercent, formatDate } from "@investintell/ui";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

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
		const reportId = fund?.dd_report_id;
		const ddStatus = fund?.dd_report_status;
		// Only subscribe when report is actively generating
		if (!reportId || ddStatus !== "generating") return;

		ddSseStatus = "streaming";
		ddProgress = null;
		ddProgressMessage = null;

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
					ddSseStatus = "error";
					return;
				}

				const reader = response.body.getReader();
				const decoder = new TextDecoder();
				let buffer = "";

				while (true) {
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
								ddProgress = event.progress ?? null;
								ddProgressMessage = event.message ?? null;
							} else if (event.type === "complete") {
								ddProgress = 100;
								ddProgressMessage = "Relatório gerado com sucesso";
								ddSseStatus = "complete";
								break;
							} else if (event.type === "error") {
								ddProgressMessage = event.message ?? "Erro na geração";
								ddSseStatus = "error";
								break;
							}
						} catch {
							// malformed JSON — skip
						}
					}

					if (ddSseStatus === "complete" || ddSseStatus === "error") break;
				}
			} catch (err: unknown) {
				if (err instanceof DOMException && err.name === "AbortError") return;
				ddSseStatus = "error";
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

<ContextPanel {open} {onClose} title={fund?.name ?? ""} width="480px">
	{#if fund}
		<!-- Fund identity row -->
		<div class="mb-5 flex items-start gap-3">
			<div class="min-w-0 flex-1">
				<p class="text-xs text-(--ii-text-muted)">{fund.manager ?? "—"}</p>
				{#if fund.subcategory}
					<p class="mt-0.5 text-xs text-(--ii-text-muted)">{fund.subcategory}</p>
				{/if}
			</div>
			<div class="flex shrink-0 flex-col items-end gap-1">
				{#if fund.score !== null}
					<span class="text-lg font-bold text-(--ii-text-primary)">
						{formatNumber(fund.score, 1, "pt-BR")}
					</span>
					<span class="text-xs text-(--ii-text-muted)">Score</span>
				{/if}
			</div>
		</div>

		<!-- Tabs -->
		<div class="mb-4 flex gap-1 border-b border-(--ii-border)">
			{#each tabs as tab (tab.value)}
				<button
					class="relative px-3 py-2 text-sm font-medium transition-colors"
					class:text-(--ii-brand-primary)={activeTab === tab.value}
					class:text-(--ii-text-muted)={activeTab !== tab.value}
					onclick={() => (activeTab = tab.value)}
				>
					{tab.label}
					{#if activeTab === tab.value}
						<span class="absolute bottom-0 left-0 right-0 h-0.5 bg-(--ii-brand-primary)"></span>
					{/if}
				</button>
			{/each}
		</div>

		<!-- Tab: Resumo -->
		{#if activeTab === "resumo"}
			<div class="space-y-4">
				<!-- Key metrics -->
				<div class="grid grid-cols-2 gap-3">
					<MetricCard label="AUM" value={formatAum(fund.aum)} />
					<MetricCard
						label="Score Geral"
						value={formatNumber(fund.score, 1, "pt-BR")}
					/>
					{#if fund.annual_return !== undefined}
						<MetricCard
							label="Retorno Anual"
							value={formatPct(fund.annual_return ?? null)}
						/>
					{/if}
					{#if fund.sharpe_ratio !== undefined}
						<MetricCard
							label="Sharpe"
							value={formatNumber(fund.sharpe_ratio, 2, "pt-BR")}
						/>
					{/if}
					{#if fund.max_drawdown !== undefined}
						<MetricCard
							label="Max Drawdown"
							value={formatPct(fund.max_drawdown ?? null)}
						/>
					{/if}
					{#if fund.cvar_95 !== undefined}
						<MetricCard
							label="CVaR 95%"
							value={formatPct(fund.cvar_95 ?? null)}
						/>
					{/if}
				</div>

				<!-- Fund metadata -->
				<SectionCard title="Informações">
					{#snippet children()}
						<dl class="space-y-2 text-sm">
							{#if fund.isin}
								<div class="flex justify-between">
									<dt class="text-(--ii-text-muted)">ISIN</dt>
									<dd class="font-mono text-(--ii-text-primary)">{fund.isin}</dd>
								</div>
							{/if}
							{#if fund.cnpj}
								<div class="flex justify-between">
									<dt class="text-(--ii-text-muted)">CNPJ</dt>
									<dd class="font-mono text-(--ii-text-primary)">{fund.cnpj}</dd>
								</div>
							{/if}
							<div class="flex justify-between">
								<dt class="text-(--ii-text-muted)">Estratégia</dt>
								<dd class="text-(--ii-text-primary)">{fund.strategy ?? "—"}</dd>
							</div>
							<div class="flex justify-between">
								<dt class="text-(--ii-text-muted)">Gestor</dt>
								<dd class="text-(--ii-text-primary)">{fund.manager ?? "—"}</dd>
							</div>
							<div class="flex justify-between">
								<dt class="text-(--ii-text-muted)">Atualizado</dt>
								<dd class="text-(--ii-text-primary)">{formatDate(fund.updated_at, "short", "pt-BR")}</dd>
							</div>
							{#if fund.inception_date}
								<div class="flex justify-between">
									<dt class="text-(--ii-text-muted)">Início</dt>
									<dd class="text-(--ii-text-primary)">{formatDate(fund.inception_date, "short", "pt-BR")}</dd>
								</div>
							{/if}
						</dl>
					{/snippet}
				</SectionCard>
			</div>

		<!-- Tab: DD Report -->
		{:else if activeTab === "dd-report"}
			<div class="space-y-4">
				{#if fund.dd_report_status === "complete"}
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
							href="/dd-reports/{fund.id}"
							class="inline-flex items-center gap-1.5 rounded-md bg-(--ii-brand-primary) px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
						>
							Ver Relatório
							<svg width="14" height="14" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
								<path d="M7 13L13 7M13 7H7M13 7V13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
							</svg>
						</a>
					</div>

				{:else if fund.dd_report_status === "generating" || ddSseStatus === "streaming"}
					<div class="rounded-lg border border-(--ii-border) bg-(--ii-surface-elevated) p-4">
						<div class="mb-3 flex items-center justify-between">
							<span class="text-sm font-medium text-(--ii-text-primary)">Gerando relatório…</span>
							{#if ddProgress !== null}
								<span class="text-xs text-(--ii-text-muted)">{ddProgress}%</span>
							{/if}
						</div>
						<!-- Progress bar -->
						<div class="h-1.5 w-full overflow-hidden rounded-full bg-(--ii-surface-inset)">
							<div
								class="h-full rounded-full bg-(--ii-brand-primary) transition-all duration-300"
								style="width: {ddProgress ?? 0}%;"
							></div>
						</div>
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

		<!-- Tab: Docs -->
		{:else if activeTab === "docs"}
			<EmptyState
				title="Documentos"
				message="Os documentos deste fundo aparecerão aqui após o upload."
			/>

		<!-- Tab: Screening -->
		{:else if activeTab === "screening"}
			<EmptyState
				title="Screening"
				message="Os resultados de screening para este fundo aparecerão aqui após a execução do screener."
			/>
		{/if}
	{:else}
		<EmptyState title="Nenhum fundo selecionado" message="Selecione um fundo na tabela para ver os detalhes." />
	{/if}
</ContextPanel>
