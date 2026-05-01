<!--
  NewPortfolioDialog — wealth deprecation shim.

  As of PR-UX-4 (`docs/plans/2026-04-30-builder-workspace-redesign-final.md`
  §6.2.4 / §6.4 Option A), the canonical NewPortfolioDialog lives in
  `packages/ii-terminal-core/src/lib/components/portfolio/NewPortfolioDialog.svelte`.
  This wealth file is a thin re-export shim so existing wealth imports
  (`$lib/components/portfolio/NewPortfolioDialog.svelte`) keep working
  while wealth migrates onto the canonical surface.

  The wealth surface owns its own caller wiring — it injects a
  workspace-bound `create` callback and an `onCreated` handler that
  performs the wealth-flavoured navigation (`goto("/portfolio?portfolio=…")`).
  Behaviour pre-PR-UX-4 (no-op `onCreated` + workspace-bound create)
  is preserved here.

  @deprecated — import from
    `@investintell/ii-terminal-core/components/portfolio/NewPortfolioDialog.svelte`
  directly. This shim is scheduled for removal once the wealth Builder
  is folded into the terminal workspace (post-GA convergence).
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import NewPortfolioDialogCanonical from "@investintell/ii-terminal-core/components/portfolio/NewPortfolioDialog.svelte";
	import type { ModelPortfolio } from "$wealth/types/model-portfolio";
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";

	interface Props {
		open: boolean;
		onOpenChange: (open: boolean) => void;
		/** Optional pre-loaded portfolio list for the "Copy from" select. */
		portfolios?: readonly ModelPortfolio[];
		/**
		 * Active mandate / profile context. Defaults to `moderate` to
		 * match the legacy wealth dialog's default mandate selection
		 * when the caller omits it (the wealth `+page.svelte` callsite
		 * does not currently pass a profile prop).
		 */
		profile?: string;
	}

	let {
		open,
		onOpenChange,
		portfolios = [],
		profile = "moderate",
	}: Props = $props();

	async function handleCreate(
		payload: Record<string, unknown>,
	): Promise<ModelPortfolio | null> {
		return workspace.createPortfolio(payload);
	}

	async function handleCreated(created: ModelPortfolio): Promise<void> {
		await goto(`/portfolio?portfolio=${created.id}`);
	}
</script>

<NewPortfolioDialogCanonical
	{open}
	{onOpenChange}
	{profile}
	{portfolios}
	create={handleCreate}
	onCreated={handleCreated}
/>
