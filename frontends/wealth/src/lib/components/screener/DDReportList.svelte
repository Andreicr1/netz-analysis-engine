<!--
  DDReportList — Placeholder for the "DD Reviews" tab in the Screener Level 1.
  Will consume GET /screener/dd-reports once wired.
-->
<script lang="ts">
  import { goto } from "$app/navigation";
  import { FileText } from "lucide-svelte";
</script>

<div class="ddl-empty">
  <div class="ddl-icon">
    <FileText size={40} strokeWidth={1.2} />
  </div>
  <h3 class="ddl-title">Due Diligence Reports</h3>
  <p class="ddl-desc">
    Generated reports will appear here. Navigate to a fund and click
    <strong>"Run DD Report"</strong> to start an 8-chapter analysis.
  </p>
  <button class="ddl-cta" onclick={() => goto("/screener/dd-reports")}>
    View All Reports
  </button>
</div>

<style>
  .ddl-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 64px 24px;
    text-align: center;
    gap: 12px;
  }

  .ddl-icon {
    color: var(--ii-text-muted, #71717a);
    margin-bottom: 4px;
  }

  .ddl-title {
    font-size: 1.125rem;
    font-weight: 700;
    color: var(--ii-text-primary, #fafafa);
    font-family: var(--ii-font-sans, "Urbanist", sans-serif);
  }

  .ddl-desc {
    max-width: 380px;
    font-size: var(--ii-text-small, 0.8125rem);
    color: var(--ii-text-muted, #71717a);
    line-height: 1.5;
    font-family: var(--ii-font-sans, "Urbanist", sans-serif);
  }

  .ddl-desc strong {
    color: var(--ii-brand-primary, #0177fb);
    font-weight: 600;
  }

  .ddl-cta {
    margin-top: 8px;
    padding: 8px 20px;
    border: 1px solid var(--ii-border, #3a3b44);
    border-radius: var(--ii-radius-pill, 999px);
    background: transparent;
    color: var(--ii-text-secondary, #a1a1aa);
    font-size: var(--ii-text-small, 0.8125rem);
    font-weight: 600;
    font-family: var(--ii-font-sans, "Urbanist", sans-serif);
    cursor: pointer;
    transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
  }

  .ddl-cta:hover {
    background: color-mix(in srgb, var(--ii-brand-primary) 8%, transparent);
    border-color: var(--ii-brand-primary, #0177fb);
    color: var(--ii-brand-primary, #0177fb);
  }
</style>
