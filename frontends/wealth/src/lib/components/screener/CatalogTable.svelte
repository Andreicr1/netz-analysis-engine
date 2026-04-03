<!--
  CatalogTable — Level 1 Manager Catalog.
  Institutional grid with name cleansing, fund badges, AUM formatting.
  Click → Level 2 ManagerDetailPanel (Sheet).
-->
<script lang="ts">
  import * as Table from "@investintell/ui/components/ui/table";
  import { formatAUM } from "@investintell/ui";
  import ManagerDetailPanel from "./ManagerDetailPanel.svelte";

  interface Manager {
    crd: string;
    name: string;
    aum: number;
    funds: string[];
  }

  interface Props {
    managers?: Manager[];
    totalCount?: number;
  }

  let { managers = [], totalCount = 0 }: Props = $props();

  // ── Level 2 state ──
  let panelOpen = $state(false);
  let selectedManager = $state<Manager | null>(null);

  function openPanel(manager: Manager) {
    selectedManager = manager;
    panelOpen = true;
  }

  // ── Name cleansing: strip legal suffixes + Title Case ──
  const LEGAL_SUFFIXES =
    /[,.]?\s*\b(LLC|L\.L\.C\.|INC\.?|L\.P\.|LP|LLP|CORP\.?|CORPORATION|LTD\.?|S\.A\.?|N\.A\.?|COMPANY|CO\.?|GROUP)\b[.,]?\s*/gi;

  function formatName(raw: string): string {
    const stripped = raw.replace(LEGAL_SUFFIXES, " ").replace(/\s{2,}/g, " ").trim().replace(/,\s*$/, "");
    return stripped
      .split(" ")
      .map((w) => {
        if (w === "&" || w === "AND") return "&";
        if (w.length <= 2 && w === w.toUpperCase()) return w;
        return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
      })
      .join(" ");
  }

  // ── Badge config ──
  const BADGE_STYLES: Record<string, string> = {
    MF: "bg-blue-500/10 text-blue-600 border-blue-500/20",
    HF: "bg-purple-500/10 text-purple-600 border-purple-500/20",
    PE: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
    VC: "bg-orange-500/10 text-orange-600 border-orange-500/20",
  };

  const BADGE_LABELS: Record<string, string> = {
    MF: "Mutual Fund",
    HF: "Hedge Fund",
    PE: "Private Equity",
    VC: "Venture Capital",
  };

  function badgeClass(type: string): string {
    return BADGE_STYLES[type] ?? "bg-muted text-muted-foreground border-border";
  }
</script>

<div class="w-full bg-card rounded-2xl border border-border/50 overflow-hidden shadow-sm">
  <!-- ── Header ── -->
  <div class="px-6 py-5 border-b border-border/50 flex justify-between items-center">
    <div class="flex items-center gap-4">
      <h2 class="text-xl font-semibold text-foreground tracking-tight">Manager Catalog</h2>
      <div class="h-6 w-px bg-border"></div>
      <span class="text-sm font-medium text-muted-foreground tabular-nums">
        {totalCount.toLocaleString()} registered entities
      </span>
    </div>
    <button
      class="text-sm px-4 py-2 border border-border/50 rounded-lg hover:bg-accent transition-colors text-foreground font-medium"
    >
      Export CSV
    </button>
  </div>

  <!-- ── Table ── -->
  <Table.Root>
    <Table.Header>
      <Table.Row class="border-b border-border/50 hover:bg-transparent">
        <Table.Head class="w-[420px] text-muted-foreground font-medium text-xs uppercase tracking-wider h-11 pl-6">
          Manager
        </Table.Head>
        <Table.Head class="text-muted-foreground font-medium text-xs uppercase tracking-wider h-11 w-[100px]">
          CRD
        </Table.Head>
        <Table.Head class="text-muted-foreground font-medium text-xs uppercase tracking-wider h-11">
          Funds
        </Table.Head>
        <Table.Head class="text-right text-muted-foreground font-medium text-xs uppercase tracking-wider h-11 pr-6 w-[140px]">
          AUM
        </Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each managers as manager (manager.crd)}
        <Table.Row
          class="border-b border-border/30 hover:bg-accent/50 transition-colors cursor-pointer group"
          onclick={() => openPanel(manager)}
        >
          <Table.Cell class="font-medium text-foreground py-4 pl-6">
            {formatName(manager.name)}
          </Table.Cell>
          <Table.Cell class="text-muted-foreground font-mono text-sm py-4">
            {manager.crd}
          </Table.Cell>
          <Table.Cell class="py-4">
            <div class="flex gap-1.5 flex-wrap">
              {#each manager.funds as fund}
                <span
                  class="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold border {badgeClass(fund)}"
                  title={BADGE_LABELS[fund] ?? fund}
                >
                  {fund}
                </span>
              {/each}
            </div>
          </Table.Cell>
          <Table.Cell class="text-right text-foreground font-mono font-medium py-4 pr-6 tabular-nums">
            {formatAUM(manager.aum)}
          </Table.Cell>
        </Table.Row>
      {/each}

      {#if managers.length === 0}
        <Table.Row>
          <Table.Cell colspan={4} class="text-center py-16 text-muted-foreground">
            No managers found.
          </Table.Cell>
        </Table.Row>
      {/if}
    </Table.Body>
  </Table.Root>
</div>

<!-- ── Level 2: Manager Detail Panel ── -->
<ManagerDetailPanel bind:open={panelOpen} manager={selectedManager} />
