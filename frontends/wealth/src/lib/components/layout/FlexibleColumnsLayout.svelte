<!--
  FlexibleColumnsLayout — Institutional 3-column adaptive workspace primitive.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-centerColumn-flexible-columns.md §2.1

  Three states, CSS Grid based, zero unmount:
    two-col:   Universe (2fr) | Builder (3fr) | Analytics (0fr, hidden)
    three-col: Universe (1.6fr) | Builder (2.2fr) | Analytics (1.4fr)
    landing:   Universe (0fr, hidden) | Builder (1fr) | Analytics (0fr, hidden)

  Why this approach (vs {#if} or snippet branching):

    - `{#if layoutState === 'three-col'}` desmonta a subárvore da 3ª
      coluna quando falsa. Remontar destrói scroll position da tabela
      virtual, cancela drag state em andamento, e (pior) re-inicializa
      charts do LayerChart a cada abertura — memória vaza, frame drops.

    - A solução idiomática CSS Grid é manter os 3 slots SEMPRE no DOM,
      mas controlar a LARGURA via `grid-template-columns` com `0fr`
      nas colunas inativas. Transição CSS pura do `grid-template-columns`
      é estável em Chrome/Edge/Safari 16+ desde 2023.

    - `overflow: hidden` + `visibility: hidden` + `pointer-events: none`
      nas colunas colapsadas isolam o conteúdo oculto de qualquer
      interação, preservando acessibilidade e layout flow.

    - Container queries (`@container`) são usadas no shell do wrapper
      em vez de media queries porque o cage do shell global
      (`calc(100vh - 72px)`) já define a geometria — o viewport não é
      a referência correta.

  Regras de responsive (spec §1.5):
    ≥ 1440px  → 3-col normal (empurra layout)
    1200-1440 → 3ª coluna vira drawer overlay (não empurra)
    1024-1200 → Estado B força 50/50
    768-1024  → Fallback single column (gerenciado pelo caller)
    < 768     → Caller redireciona para aviso desktop-required

  Este componente não toma essas decisões — ele expõe o contrato
  `layoutState` e respeita a proporção declarada. Viewport downgrade
  é responsabilidade do `+page.svelte` orchestrator.

  Acessibilidade:
    - Cada coluna tem `role="region"` e `aria-label` fornecido pelo
      caller via snippet context (caller é responsável).
    - Colunas colapsadas recebem `aria-hidden="true"` para serem
      ignoradas por screen readers.
    - Transição é instantânea quando `prefers-reduced-motion: reduce`.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	export type LayoutState = "landing" | "two-col" | "three-col";

	interface Props {
		/**
		 * Derived from business state in the caller, never stored:
		 *   $derived(
		 *     selectedAnalyticsFund ? "three-col" :
		 *     portfolioId ? "two-col" : "landing"
		 *   )
		 */
		layoutState: LayoutState;
		leftColumn: Snippet;
		centerColumn: Snippet;
		rightColumn: Snippet;
	}

	let { layoutState, leftColumn, centerColumn, rightColumn }: Props = $props();

	// Grid template per state — expressed as a single CSS custom prop so
	// the transition CSS only needs to watch one variable.
	const gridTemplate = $derived.by(() => {
		switch (layoutState) {
			case "landing":
				return "0fr minmax(0, 1fr) 0fr";
			case "two-col":
				return "minmax(0, 2fr) minmax(0, 3fr) 0fr";
			case "three-col":
				return "minmax(0, 1.6fr) minmax(0, 2.2fr) minmax(0, 1.4fr)";
		}
	});

	const leftColumnHidden = $derived(layoutState === "landing");
	const rightColumnHidden = $derived(layoutState !== "three-col");
</script>

<div
	class="fcl-root"
	style:grid-template-columns={gridTemplate}
	data-layout-state={layoutState}
>
	<!-- A <section> with an accessible name (aria-label) already has
	     implicit ARIA role="region". Explicit `role="region"` would
	     be redundant and triggers svelte-check a11y_no_redundant_roles. -->
	<section
		class="fcl-col fcl-col-left"
		class:fcl-col--collapsed={leftColumnHidden}
		aria-hidden={leftColumnHidden}
		aria-label="Approved Universe"
	>
		{@render leftColumn()}
	</section>

	<section
		class="fcl-col fcl-col-center"
		aria-label="Portfolio Builder"
	>
		{@render centerColumn()}
	</section>

	<section
		class="fcl-col fcl-col-right"
		class:fcl-col--collapsed={rightColumnHidden}
		aria-hidden={rightColumnHidden}
		aria-label="Analytics"
	>
		{@render rightColumn()}
	</section>
</div>

<style>
	.fcl-root {
		/* Container for the 3 columns. Height is 100% of the slot the
		 * caller gives us — do not assume viewport here. The shell
		 * layout cage (`calc(100vh - 72px)` in (app)/+layout.svelte)
		 * owns the viewport math. */
		display: grid;
		width: 100%;
		height: 100%;
		min-height: 0;
		gap: 0;
		background: #0e0f13;
		border: 1px solid rgba(64, 66, 73, 0.4);
		/* The star of the show. Transition on grid-template-columns is
		 * supported in Chrome 107+, Edge 107+, Safari 16+. All
		 * institutional clients run these. Duration 240ms is the
		 * institutional sweet spot — noticeable enough to read as
		 * "opening", fast enough to not feel sluggish. */
		transition: grid-template-columns 240ms cubic-bezier(0.4, 0, 0.2, 1);
		/* Container query reference for the columns. */
		container-type: inline-size;
		container-name: fcl;
	}

	.fcl-col {
		/* Each column owns its own scroll. A PM scrolling the Universe
		 * table must not drag Builder content with it. */
		min-width: 0;
		min-height: 0;
		overflow: auto;
		background: #141519;
		/* The column uses its own border-box; collapse to 0px width
		 * when the grid template says 0fr, with overflow hidden so
		 * content clips cleanly during transition. */
		position: relative;
	}

	.fcl-col-left,
	.fcl-col-right {
		/* These two can collapse; the Builder is always present. */
		border-left: 1px solid rgba(64, 66, 73, 0.4);
	}

	.fcl-col-left {
		border-left: none;
		border-right: 1px solid rgba(64, 66, 73, 0.4);
	}

	.fcl-col--collapsed {
		/* Belt-and-suspenders: grid gives us 0fr, but visibility and
		 * pointer-events make absolutely sure the hidden column
		 * cannot receive focus, mouse events, or be read by screen
		 * readers mid-transition. */
		visibility: hidden;
		pointer-events: none;
		border: none;
	}

	/* Honour user preference for reduced motion — instant state
	 * transitions, no animation. The drag-drop lifecycle is unchanged;
	 * only the visual tween is suppressed. */
	@media (prefers-reduced-motion: reduce) {
		.fcl-root {
			transition: none;
		}
	}

	/* ── Responsive degradation (container queries) ─────────────────
	 *
	 * The caller is responsible for passing the right `layoutState`
	 * for each viewport bucket (§1.5 of the spec), but we add a
	 * safety net here for when the workspace slot itself is narrow
	 * — e.g. when the global sidebar is open taking 240px — so the
	 * columns never collapse below institutional density. */
	@container fcl (max-width: 1100px) {
		.fcl-root[data-layout-state="three-col"] {
			/* Under 1100px of workspace width, the Analytics column
			 * becomes an absolute overlay on top of Builder instead
			 * of squeezing the grid. Caller can opt out of this by
			 * setting data-layout-state to two-col explicitly. */
			grid-template-columns: minmax(0, 2fr) minmax(0, 3fr) 0fr;
		}
		.fcl-root[data-layout-state="three-col"] .fcl-col-right {
			position: absolute;
			top: 0;
			right: 0;
			bottom: 0;
			width: min(520px, 80%);
			visibility: visible;
			pointer-events: auto;
			border-left: 1px solid var(--ii-border-subtle, transparent);
			box-shadow: -12px 0 32px -16px rgb(0 0 0 / 0.4);
			z-index: 10;
		}
	}
</style>
