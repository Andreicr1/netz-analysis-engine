<!--
  PolicyPanel — DEPRECATED in Phase 4 of the portfolio-enterprise-workbench
  plan. Scheduled for deletion in Phase 5 Task 5.4. The new
  ``CalibrationPanel.svelte`` is the canonical calibration surface (DL5).
  This file is kept alive only so the ``policy`` sub-pill in
  /portfolio/+page.svelte continues to render until the Phase 5 swap
  lands — but every interaction is a local-only no-op.
-->
<script lang="ts">
    import { workspace } from "$lib/state/portfolio-workspace.svelte";
    import { EmptyState, formatPercent } from "@investintell/ui";

    // Local-only sliders kept purely for the legacy visual. The real
    // state lives in ``CalibrationPanel`` (Phase 4 Task 4.1/4.2) and
    // persists via PUT /model-portfolios/{id}/calibration.
    let cvarLimit = $state(-0.08);
    let maxConcentration = $state(0.15);

    function handleCvarChange(e: Event) {
        cvarLimit = parseFloat((e.target as HTMLInputElement).value);
    }

    function handleConcentrationChange(e: Event) {
        maxConcentration = parseFloat((e.target as HTMLInputElement).value);
    }
</script>

{#if !workspace.portfolio}
    <div class="p-6">
        <EmptyState
            title="No portfolio selected"
            message="Select a model portfolio to adjust its investment policies."
        />
    </div>
{:else}
    <div class="flex flex-col gap-8 p-6">
        <div class="space-y-6">
            <h3 class="text-[11px] font-bold text-[#85a0bd] uppercase tracking-[0.08em] pb-3" style="border-bottom: 1px solid #404249;">
                Risk Constraints
            </h3>

            <!-- CVaR Limit Slider -->
            <div class="flex flex-col gap-3">
                <div class="flex justify-between items-center">
                    <label for="cvar-slider" class="text-[14px] font-semibold text-white">Max CVaR Limit (95%)</label>
                    <span class="text-[14px] font-bold text-[#fc1a1a]">{formatPercent(cvarLimit)}</span>
                </div>
                <input
                    id="cvar-slider"
                    type="range"
                    min="-0.25"
                    max="-0.02"
                    step="0.01"
                    value={cvarLimit}
                    oninput={handleCvarChange}
                />
                <div class="flex justify-between text-[11px] font-medium text-[#85a0bd]">
                    <span>-25% (Looser)</span>
                    <span>-2% (Tighter)</span>
                </div>
            </div>

            <!-- Max Concentration Slider -->
            <div class="flex flex-col gap-3 pt-2">
                <div class="flex justify-between items-center">
                    <label for="conc-slider" class="text-[14px] font-semibold text-white">Max Single Fund Weight</label>
                    <span class="text-[14px] font-bold text-[#0177fb]">{formatPercent(maxConcentration)}</span>
                </div>
                <input
                    id="conc-slider"
                    type="range"
                    min="0.05"
                    max="0.40"
                    step="0.01"
                    value={maxConcentration}
                    oninput={handleConcentrationChange}
                />
                <div class="flex justify-between text-[11px] font-medium text-[#85a0bd]">
                    <span>5%</span>
                    <span>40%</span>
                </div>
            </div>
        </div>

        <div class="bg-white/[0.03] p-4 rounded-[16px] border border-[#404249]/30">
            <p class="text-[12px] text-[#85a0bd] leading-relaxed">
                <strong class="text-[#cbccd1]">Note:</strong> These constraints govern the
                <span class="font-mono text-[10px] bg-white/5 text-[#cbccd1] px-1.5 py-0.5 rounded border border-white/10">CLARABEL</span>
                optimizer. Tighter CVaR limits may activate the Phase 2 variance-ceiling
                fallback to preserve numerical admissibility.
            </p>
        </div>
    </div>
{/if}

<style>
    /* Modern cross-browser Slider Styling — Figma One X dark theme */
    input[type="range"] {
        -webkit-appearance: none;
        appearance: none;
        width: 100%;
        background: transparent;
    }

    input[type="range"]::-webkit-slider-runnable-track {
        width: 100%;
        height: 6px;
        cursor: pointer;
        background: rgba(64, 66, 73, 0.6);
        border-radius: 999px;
    }

    input[type="range"]::-webkit-slider-thumb {
        height: 20px;
        width: 20px;
        border-radius: 50%;
        background: #1a1b20;
        border: 3px solid #0177fb;
        cursor: pointer;
        -webkit-appearance: none;
        margin-top: -7px;
        box-shadow: 0 2px 8px rgba(1, 119, 251, 0.25);
        transition: transform 100ms ease, box-shadow 100ms ease;
    }

    input[type="range"]::-webkit-slider-thumb:hover {
        transform: scale(1.15);
    }

    input[type="range"]:focus {
        outline: none;
    }

    input[type="range"]:focus::-webkit-slider-thumb {
        box-shadow: 0 0 0 4px rgba(1, 119, 251, 0.2);
    }

    /* Firefox support */
    input[type="range"]::-moz-range-track {
        width: 100%;
        height: 6px;
        cursor: pointer;
        background: rgba(64, 66, 73, 0.6);
        border-radius: 999px;
    }

    input[type="range"]::-moz-range-thumb {
        height: 20px;
        width: 20px;
        border-radius: 50%;
        background: #1a1b20;
        border: 3px solid #0177fb;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(1, 119, 251, 0.25);
        transition: transform 100ms ease;
    }
</style>
