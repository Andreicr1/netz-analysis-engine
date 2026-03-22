<script lang="ts">
	import { ContextPanel, StatusBadge, Button, EmptyState, formatNumber } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";

	/* ── Types ── */

	interface EsmaFundItem {
		isin: string;
		fund_name: string;
		domicile: string | null;
		fund_type: string | null;
		yahoo_ticker: string | null;
		esma_manager_id: string | null;
	}

	interface EsmaManagerDetail {
		esma_id: string;
		company_name: string;
		country: string | null;
		authorization_status: string | null;
		sec_crd_number: string | null;
		funds: EsmaFundItem[];
	}

	/* ── Props ── */

	let {
		esmaId,
		onClose,
		getToken,
	}: {
		esmaId: string | null;
		onClose: () => void;
		getToken: () => Promise<string>;
	} = $props();

	/* ── State ── */

	let manager = $state<EsmaManagerDetail | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	/* ── Load manager detail on esmaId change ── */

	$effect(() => {
		if (esmaId) {
			loading = true;
			error = null;
			manager = null;

			const api = createClientApiClient(getToken);
			api
				.get(`/esma/managers/${esmaId}`)
				.then((m: EsmaManagerDetail) => {
					manager = m;
				})
				.catch((err: Error) => {
					console.error("Failed to load ESMA manager detail", err);
					error = "Failed to load manager details.";
				})
				.finally(() => {
					loading = false;
				});
		} else {
			manager = null;
			error = null;
		}
	});

	/* ── Add to Universe dialog ── */

	let showAddDialog = $state(false);
	let addIsin = $state("");
	let addAssetClass = $state("equity");
	let addGeography = $state("EU");
	let addCurrency = $state("EUR");
	let addLoading = $state(false);
	let addSuccess = $state<string | null>(null);

	function openAddDialog(isin: string) {
		addIsin = isin;
		addAssetClass = "equity";
		addGeography = "EU";
		addCurrency = "EUR";
		addSuccess = null;
		showAddDialog = true;
	}

	function closeAddDialog() {
		showAddDialog = false;
		addIsin = "";
		addSuccess = null;
	}

	async function addToUniverse() {
		if (!addIsin) return;
		addLoading = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/instruments", {
				name: manager?.funds.find((f) => f.isin === addIsin)?.fund_name ?? addIsin,
				ticker: manager?.funds.find((f) => f.isin === addIsin)?.yahoo_ticker ?? "",
				instrument_type: "fund",
				asset_class: addAssetClass,
				geography: addGeography,
				currency: addCurrency,
				attributes: {
					source: "esma_fund",
					isin: addIsin,
					esma_manager_id: esmaId,
				},
			});
			addSuccess = addIsin;
		} catch (err) {
			console.error("Failed to add to universe", err);
		} finally {
			addLoading = false;
		}
	}
</script>

<ContextPanel open={!!esmaId} {onClose} title={manager?.company_name ?? "Manager Detail"} width="560px">
	{#if loading}
		<div class="flex items-center justify-center py-12">
			<span class="text-sm text-(--netz-text-muted)">Loading...</span>
		</div>
	{:else if error}
		<div class="py-8">
			<EmptyState title="Error" description={error} />
		</div>
	{:else if manager}
		<!-- Manager Info -->
		<div class="space-y-4">
			<div class="grid grid-cols-2 gap-3">
				<div>
					<span class="block text-xs text-(--netz-text-muted)">ESMA ID</span>
					<span class="text-sm font-mono text-(--netz-text-primary)">{manager.esma_id}</span>
				</div>
				<div>
					<span class="block text-xs text-(--netz-text-muted)">Country</span>
					<span class="text-sm text-(--netz-text-primary)">{manager.country ?? "—"}</span>
				</div>
				<div>
					<span class="block text-xs text-(--netz-text-muted)">Authorization</span>
					<span class="text-sm text-(--netz-text-primary)">{manager.authorization_status ?? "—"}</span>
				</div>
				<div>
					<span class="block text-xs text-(--netz-text-muted)">SEC Cross-Reference</span>
					{#if manager.sec_crd_number}
						<StatusBadge status="ok" label="SEC Matched (CRD {manager.sec_crd_number})" />
					{:else}
						<StatusBadge status="neutral" label="No SEC Match" />
					{/if}
				</div>
			</div>

			<!-- Funds Table -->
			<div class="mt-6">
				<h3 class="text-sm font-semibold text-(--netz-text-primary) mb-2">
					Funds ({formatNumber(manager.funds.length, 0)})
				</h3>

				{#if manager.funds.length === 0}
					<EmptyState title="No funds" description="This manager has no registered funds." />
				{:else}
					<div class="overflow-x-auto rounded-lg border border-(--netz-border-subtle)">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-(--netz-border-subtle) bg-(--netz-surface-alt)">
									<th class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary)">Fund Name</th>
									<th class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary)">ISIN</th>
									<th class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary)">Ticker</th>
									<th class="px-3 py-2 text-right text-xs font-medium text-(--netz-text-secondary)"></th>
								</tr>
							</thead>
							<tbody>
								{#each manager.funds as fund (fund.isin)}
									<tr class="border-b border-(--netz-border-subtle) last:border-b-0">
										<td class="px-3 py-2 text-(--netz-text-primary) max-w-[180px] truncate" title={fund.fund_name}>
											{fund.fund_name}
										</td>
										<td class="px-3 py-2 font-mono text-xs text-(--netz-text-secondary)">
											{fund.isin}
										</td>
										<td class="px-3 py-2 font-mono text-xs text-(--netz-text-secondary)">
											{fund.yahoo_ticker ?? "—"}
										</td>
										<td class="px-3 py-2 text-right">
											{#if addSuccess === fund.isin}
												<StatusBadge status="ok" label="Added" />
											{:else}
												<Button
													variant="outline"
													size="sm"
													onclick={() => openAddDialog(fund.isin)}
												>
													Add to Universe
												</Button>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</ContextPanel>

<!-- Add to Universe Dialog -->
{#if showAddDialog}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onkeydown={(e) => e.key === "Escape" && closeAddDialog()}>
		<div
			class="w-full max-w-md rounded-xl p-6 shadow-xl"
			style="background: var(--netz-surface, #fff);"
			role="dialog"
			aria-modal="true"
			aria-label="Add fund to universe"
		>
			<h3 class="text-base font-semibold text-(--netz-text-primary) mb-4">Add to Universe</h3>
			<p class="text-sm text-(--netz-text-secondary) mb-4">
				ISIN: <span class="font-mono">{addIsin}</span>
			</p>

			<div class="space-y-3">
				<div>
					<label for="esma-asset-class" class="block text-xs font-medium text-(--netz-text-secondary) mb-1">Asset Class</label>
					<select
						id="esma-asset-class"
						bind:value={addAssetClass}
						class="w-full rounded-md border border-(--netz-border-subtle) bg-(--netz-surface) px-3 py-1.5 text-sm text-(--netz-text-primary)"
					>
						<option value="equity">Equity</option>
						<option value="fixed_income">Fixed Income</option>
						<option value="multi_asset">Multi Asset</option>
						<option value="alternatives">Alternatives</option>
						<option value="money_market">Money Market</option>
					</select>
				</div>
				<div>
					<label for="esma-geography" class="block text-xs font-medium text-(--netz-text-secondary) mb-1">Geography</label>
					<select
						id="esma-geography"
						bind:value={addGeography}
						class="w-full rounded-md border border-(--netz-border-subtle) bg-(--netz-surface) px-3 py-1.5 text-sm text-(--netz-text-primary)"
					>
						<option value="EU">Europe</option>
						<option value="US">United States</option>
						<option value="UK">United Kingdom</option>
						<option value="APAC">Asia Pacific</option>
						<option value="LATAM">Latin America</option>
						<option value="GLOBAL">Global</option>
					</select>
				</div>
				<div>
					<label for="esma-currency" class="block text-xs font-medium text-(--netz-text-secondary) mb-1">Currency</label>
					<select
						id="esma-currency"
						bind:value={addCurrency}
						class="w-full rounded-md border border-(--netz-border-subtle) bg-(--netz-surface) px-3 py-1.5 text-sm text-(--netz-text-primary)"
					>
						<option value="EUR">EUR</option>
						<option value="USD">USD</option>
						<option value="GBP">GBP</option>
						<option value="CHF">CHF</option>
						<option value="BRL">BRL</option>
					</select>
				</div>
			</div>

			<div class="flex justify-end gap-2 mt-6">
				<Button variant="outline" size="sm" onclick={closeAddDialog}>Cancel</Button>
				<Button size="sm" onclick={addToUniverse} disabled={addLoading}>
					{addLoading ? "Adding..." : "Add Fund"}
				</Button>
			</div>
		</div>
	</div>
{/if}
