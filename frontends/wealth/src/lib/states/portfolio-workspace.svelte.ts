/**
 * Portfolio Workspace — Global state for the unified Portfolio Builder.
 * Manages sidebar/main tab selection, active portfolio, and async operation flags.
 */

export class PortfolioWorkspaceState {
	activeSidebarTab = $state<"universe" | "policy" | "models">("models");
	activeMainTab = $state<"overview" | "analytics" | "stress" | "holdings">("overview");
	portfolio = $state<any | null>(null);
	localBacktest = $state.raw<any | null>(null);
	localStress = $state.raw<any | null>(null);
	isConstructing = $state(false);
	isStressing = $state(false);

	portfolioId = $derived(this.portfolio?.id ?? null);
	funds = $derived(this.portfolio?.fund_selection_schema?.funds ?? []);

	selectPortfolio(p: any) {
		this.portfolio = p;
		this.localBacktest = null;
		this.localStress = null;
	}

	async constructPortfolio() {
		/* placeholder — will call POST /model-portfolios/{id}/construct */
	}

	async runStressTest() {
		/* placeholder — will call POST /stress-test */
	}
}

export const workspace = new PortfolioWorkspaceState();
