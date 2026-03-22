<!--
  Macro — Dashboards consuming FRED/OFR/BIS/IMF indirectly via hypertables.
  No direct external API calls — all data from macro_data, treasury_data, ofr_hedge_fund_data,
  bis_statistics, imf_weo_forecasts hypertables.
-->
<script lang="ts">
	import { PageHeader } from "@netz/ui";
</script>

<PageHeader title="Macro Intelligence" />

<div class="p-6">
	<div class="rounded-lg border border-(--netz-border-subtle) bg-(--netz-surface-elevated) p-8 text-center">
		<p class="text-sm text-(--netz-text-muted)">Macro dashboards — FRED, Treasury, OFR, BIS, IMF (all from hypertables)</p>
	</div>
</div>
