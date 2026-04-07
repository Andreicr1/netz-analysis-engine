<!--
  Reverse Lookup Panel — displays institutional holders of a specific CUSIP/ISIN.
-->
<script lang="ts">
    import { onMount, getContext } from 'svelte';
    import { formatCompact, formatPercent, formatDate, StatusBadge } from "@investintell/ui";
    import { createClientApiClient } from "$lib/api/client";

    let { cusip = null, isin = null, assetName = "Asset" } = $props();
    
    const getToken = getContext<() => Promise<string>>("netz:getToken");
    
    let holders = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    async function loadHolders() {
        loading = true;
        error = null;
        try {
            const api = createClientApiClient(getToken);
            const params = new URLSearchParams();
            if (cusip) params.set("cusip", cusip);
            if (isin) params.set("isin", isin);
            
            const res = await api.get<any>(`/search/holdings/reverse?${params.toString()}`);
            holders = res.holders;
        } catch (e) {
            error = "Failed to load holders data.";
            console.error(e);
        } finally {
            loading = false;
        }
    }

    onMount(() => {
        loadHolders();
    });
</script>

<div class="rl-panel">
    <div class="rl-header">
        <h3 class="rl-title">Institutional Holders</h3>
        <p class="rl-subtitle">{assetName} {cusip ? `(CUSIP: ${cusip})` : isin ? `(ISIN: ${isin})` : ""}</p>
    </div>

    {#if loading}
        <div class="rl-loading">Searching institutional portfolios...</div>
    {:else if error}
        <div class="rl-error">{error}</div>
    {:else if holders.length === 0}
        <div class="rl-empty">No institutional holders found in recent filings.</div>
    {:else}
        <div class="rl-table-wrap">
            <table class="rl-table">
                <thead>
                    <tr>
                        <th>Holder</th>
                        <th>Type</th>
                        <th class="r">Weight</th>
                        <th class="r">Value</th>
                        <th class="r">Reported</th>
                    </tr>
                </thead>
                <tbody>
                    {#each holders as h}
                        <tr>
                            <td>
                                <div class="rl-holder-name">{h.holder_name}</div>
                                <div class="rl-holder-id">CIK: {h.holder_id}</div>
                            </td>
                            <td>
                                <span class="rl-type-badge" class:fund={h.holder_type === 'fund'}>
                                    {h.holder_type.toUpperCase()}
                                </span>
                            </td>
                            <td class="r rl-weight">{h.weight_pct ? formatPercent(h.weight_pct) : "—"}</td>
                            <td class="r rl-value">{h.market_value ? formatCompact(h.market_value) : "—"}</td>
                            <td class="r rl-date">{h.report_date ? formatDate(h.report_date) : "—"}</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}
</div>

<style>
    .rl-panel {
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    .rl-header {
        padding-bottom: 12px;
        border-bottom: 1px solid var(--ii-border-subtle);
    }

    .rl-title {
        margin: 0;
        font-size: 18px;
        font-weight: 700;
        color: var(--ii-text-primary);
    }

    .rl-subtitle {
        margin: 4px 0 0;
        font-size: 13px;
        color: var(--ii-text-muted);
    }

    .rl-loading, .rl-empty, .rl-error {
        padding: 40px;
        text-align: center;
        color: var(--ii-text-muted);
        font-size: 14px;
        background: var(--ii-surface-alt);
        border-radius: 8px;
    }

    .rl-error { color: var(--ii-danger); }

    .rl-table-wrap {
        overflow-x: auto;
    }

    .rl-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
    }

    .rl-table th {
        text-align: left;
        padding: 8px 12px;
        color: var(--ii-text-muted);
        font-size: 11px;
        text-transform: uppercase;
        border-bottom: 1px solid var(--ii-border-subtle);
    }

    .rl-table td {
        padding: 12px;
        border-bottom: 1px solid var(--ii-border-subtle);
    }

    .rl-table th.r, .rl-table td.r { text-align: right; }

    .rl-holder-name {
        font-weight: 600;
        color: var(--ii-text-primary);
    }

    .rl-holder-id {
        font-size: 11px;
        color: var(--ii-text-muted);
    }

    .rl-type-badge {
        font-size: 10px;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        background: #f1f5f9;
        color: #64748b;
    }

    .rl-type-badge.fund {
        background: #eff6ff;
        color: #3b82f6;
    }

    .rl-weight {
        font-weight: 700;
        color: var(--ii-text-primary);
    }

    .rl-value {
        font-variant-numeric: tabular-nums;
    }

    .rl-date {
        color: var(--ii-text-muted);
        font-size: 12px;
    }
</style>
