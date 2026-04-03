/** Screener Level 1 — Manager Catalog SSR load.
 *
 * Mock data based on Timescale inventory (sec_managers × sec_manager_funds).
 * Will be replaced by real API call to /manager-screener/ once wired.
 */
import type { PageServerLoad } from "./$types";

export interface CatalogManager {
	crd: string;
	name: string;
	aum: number;
	funds: string[];
}

export const load: PageServerLoad = async () => {
	const mockManagers: CatalogManager[] = [
		{ crd: "105958", name: "VANGUARD GROUP INC", aum: 10_200_000_000_000, funds: ["MF", "HF"] },
		{ crd: "108281", name: "FIDELITY MANAGEMENT & RESEARCH COMPANY LLC", aum: 4_700_000_000_000, funds: ["MF", "PE"] },
		{ crd: "104559", name: "PACIFIC INVESTMENT MANAGEMENT COMPANY LLC", aum: 3_000_000_000_000, funds: ["HF", "PE"] },
		{ crd: "105247", name: "BLACKROCK FUND ADVISORS", aum: 3_500_000_000_000, funds: ["MF"] },
		{ crd: "105496", name: "T. ROWE PRICE ASSOCIATES, INC.", aum: 1_900_000_000_000, funds: ["MF", "HF", "PE"] },
		{ crd: "106838", name: "CAPITAL RESEARCH AND MANAGEMENT COMPANY", aum: 2_800_000_000_000, funds: ["MF"] },
		{ crd: "105497", name: "WELLINGTON MANAGEMENT COMPANY LLP", aum: 1_200_000_000_000, funds: ["MF", "HF", "PE"] },
		{ crd: "106055", name: "JP MORGAN INVESTMENT MANAGEMENT INC", aum: 2_100_000_000_000, funds: ["MF", "HF", "PE", "VC"] },
		{ crd: "105567", name: "GOLDMAN SACHS ASSET MANAGEMENT L.P.", aum: 1_800_000_000_000, funds: ["MF", "HF", "PE"] },
		{ crd: "106405", name: "MORGAN STANLEY INVESTMENT MANAGEMENT INC", aum: 1_500_000_000_000, funds: ["MF", "HF"] },
		{ crd: "105352", name: "STATE STREET GLOBAL ADVISORS INC", aum: 4_100_000_000_000, funds: ["MF"] },
		{ crd: "106698", name: "INVESCO ADVISERS INC", aum: 1_600_000_000_000, funds: ["MF", "PE"] },
	];

	return {
		managers: mockManagers,
		totalCount: 5_692,
	};
};
