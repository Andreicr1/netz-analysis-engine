<!--
  ManagerDetailPanel — Level 2 Sheet panel.
  Slides in from the right with manager profile, AI summary placeholder, and fund list.
-->
<script lang="ts">
  import * as Sheet from "@investintell/ui/components/ui/sheet";
  import { Badge } from "@investintell/ui/components/ui/badge";
  import { Button } from "@investintell/ui/components/ui/button";
  import { ScrollArea } from "@investintell/ui/components/ui/scroll-area";
  import { ExternalLink, FileText, Landmark } from "lucide-svelte";
  import { formatAUM } from "@investintell/ui";

  interface Manager {
    crd: string;
    name: string;
    aum: number;
    funds: string[];
  }

  interface Props {
    open?: boolean;
    manager?: Manager | null;
  }

  let { open = $bindable(false), manager = null }: Props = $props();

  // ── Name cleansing (shared logic with CatalogTable) ──
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

  // ── Badge styles ──
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

  // ── Mock fund list (will be replaced by real API fetch) ──
  const MOCK_FUNDS: Record<string, { name: string; ticker?: string; type: string }[]> = {
    "105958": [
      { name: "Total Stock Market Index Fund", ticker: "VTSAX", type: "MF" },
      { name: "500 Index Fund", ticker: "VFIAX", type: "MF" },
      { name: "Total Bond Market Index Fund", ticker: "VBTLX", type: "MF" },
    ],
    "108281": [
      { name: "Contrafund", ticker: "FCNTX", type: "MF" },
      { name: "Growth Company Fund", ticker: "FDGRX", type: "MF" },
    ],
    "104559": [
      { name: "Income Fund", ticker: "PIMIX", type: "MF" },
      { name: "Total Return Fund", ticker: "PTTRX", type: "MF" },
      { name: "Strategic Alpha L.P.", type: "HF" },
    ],
    "105247": [
      { name: "iShares Core S&P 500 ETF", ticker: "IVV", type: "MF" },
      { name: "iShares MSCI Emerging Markets ETF", ticker: "EEM", type: "MF" },
    ],
    "105496": [
      { name: "Blue Chip Growth Fund", ticker: "TRBCX", type: "MF" },
      { name: "Capital Appreciation Fund", ticker: "PRWCX", type: "MF" },
      { name: "Private Credit Opportunities L.P.", type: "PE" },
    ],
  };

  let funds = $derived(manager ? (MOCK_FUNDS[manager.crd] ?? []) : []);
</script>

<Sheet.Root bind:open>
  <Sheet.Content
    side="right"
    class="w-[600px] sm:max-w-[600px] bg-card border-l border-border/50 p-0 flex flex-col"
  >
    {#if manager}
      <!-- ── Header ── -->
      <div class="px-8 py-6 border-b border-border/50 shrink-0">
        <div class="flex items-start justify-between mb-3">
          <div>
            <Sheet.Title class="text-2xl font-bold tracking-tight text-foreground">
              {formatName(manager.name)}
            </Sheet.Title>
            <Sheet.Description class="flex items-center gap-3 mt-1.5 text-muted-foreground font-mono text-sm">
              <span>CRD: {manager.crd}</span>
              <span class="w-1 h-1 rounded-full bg-border"></span>
              <span>AUM: {formatAUM(manager.aum)}</span>
            </Sheet.Description>
          </div>
        </div>
        <div class="flex gap-2">
          {#each manager.funds ?? [] as fund}
            <Badge variant="outline" class={badgeClass(fund)} title={BADGE_LABELS[fund] ?? fund}>
              {fund}
            </Badge>
          {/each}
        </div>
      </div>

      <!-- ── Scrollable body ── -->
      <ScrollArea class="flex-1">
        <div class="p-8 space-y-8">
          <!-- AI ADV Profile Summary -->
          <div class="space-y-3">
            <h3 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
              <FileText size={16} />
              AI ADV Profile Summary
            </h3>
            <div class="p-4 rounded-xl border border-border/50 bg-muted/30 text-sm leading-relaxed text-muted-foreground">
              <span class="animate-pulse">Retrieving vector embeddings for CRD {manager.crd}...</span>
            </div>
          </div>

          <!-- Managed Funds -->
          <div class="space-y-3">
            <h3 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
              <Landmark size={16} />
              Managed Funds
              <span class="text-xs font-normal">({funds.length})</span>
            </h3>
            <div class="border border-border/50 rounded-xl overflow-hidden divide-y divide-border/30">
              {#each funds as fund}
                <div class="p-4 hover:bg-accent/50 cursor-pointer flex justify-between items-center group transition-colors">
                  <div>
                    <div class="font-medium text-sm text-foreground group-hover:text-primary transition-colors">
                      {fund.name}
                    </div>
                    <div class="text-xs text-muted-foreground font-mono mt-1">
                      {#if fund.ticker}
                        Ticker: {fund.ticker}
                      {:else}
                        Private Fund
                      {/if}
                    </div>
                  </div>
                  <div class="flex items-center gap-2">
                    <Badge variant="outline" class="{badgeClass(fund.type)} text-[10px]">
                      {fund.type}
                    </Badge>
                    <Button variant="ghost" size="icon" class="opacity-0 group-hover:opacity-100 transition-opacity h-8 w-8">
                      <ExternalLink size={14} />
                    </Button>
                  </div>
                </div>
              {:else}
                <div class="p-6 text-center text-sm text-muted-foreground">
                  No fund data available for this manager.
                </div>
              {/each}
            </div>
          </div>
        </div>
      </ScrollArea>
    {/if}
  </Sheet.Content>
</Sheet.Root>
