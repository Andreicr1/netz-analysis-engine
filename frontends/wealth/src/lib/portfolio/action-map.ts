/**
 * Builder action map — Phase 5 Task 5.2 of the portfolio-enterprise-workbench
 * plan. Maps each ``PortfolioAction`` string returned by the backend
 * ``allowed_actions`` array to a button label, variant, icon name, and
 * confirmation policy.
 *
 * The Builder action bar renders ``{#each portfolio.allowed_actions as
 * action}<ActionButton {...ACTION_MAP[action]} />{/each}`` — DL3 forbids
 * any ``if state === "validated"`` conditional anywhere in the wealth
 * frontend. The single source of truth for which buttons are visible
 * is the backend's ``compute_allowed_actions`` function.
 *
 * Adding a new entry here is a coordinated change with:
 *   - ``backend/vertical_engines/wealth/model_portfolio/state_machine.py``
 *     (compute_allowed_actions + the ACTION_* constants)
 *   - ``backend/app/domains/wealth/routes/model_portfolios.py``
 *     (the ``apply_portfolio_transition`` dispatcher)
 *   - ``frontends/wealth/src/lib/types/model-portfolio.ts``
 *     (the ``PortfolioAction`` union)
 */

import type { PortfolioAction } from "$wealth/types/model-portfolio";

/**
 * Visual variant for the action button — maps to the @investintell/ui
 * Button variant prop. ``primary`` is the canonical "next step" button,
 * ``success`` lights up the approval / activation gate, ``warning``
 * highlights pause / rebuild_draft, and ``danger`` covers reject /
 * archive moves that destroy or hide work.
 */
export type ActionVariant =
	| "primary"
	| "secondary"
	| "success"
	| "warning"
	| "danger";

/**
 * Lucide icon name for the action button. Phase 5 ships a small set of
 * deterministic icons; Phase 10 may swap them for the canonical iconset
 * once the jargon translation table lands.
 */
export type ActionIcon =
	| "play"
	| "shield-check"
	| "check-circle"
	| "rocket"
	| "pause"
	| "play-circle"
	| "archive"
	| "x-circle"
	| "rotate-ccw";

export interface ActionDescriptor {
	/** Action string returned by the backend in ``allowed_actions``. */
	action: PortfolioAction;
	/** Button label as shown to the PM. */
	label: string;
	/** Visual variant for the @investintell/ui Button. */
	variant: ActionVariant;
	/** Icon name passed to the BuilderActionBar's icon switch. */
	icon: ActionIcon;
	/** Tooltip / aria description; surfaces in the action bar's hover. */
	description: string;
	/** When true, the action bar opens a ConfirmDialog before dispatching. */
	confirm: boolean;
	/** When true, the confirm dialog requires the user to type a reason. */
	reasonRequired: boolean;
}

/**
 * Canonical action map. Every ``PortfolioAction`` value MUST appear here
 * — TypeScript's ``Record<PortfolioAction, ActionDescriptor>`` enforces
 * coverage at compile time so adding a new action to the union without
 * updating this map fails the build.
 */
export const ACTION_MAP: Record<PortfolioAction, ActionDescriptor> = {
	construct: {
		action: "construct",
		label: "Run Construct",
		variant: "primary",
		icon: "play",
		description:
			"Run the optimizer cascade, stress suite, validation gate, and narrative templater.",
		confirm: false,
		reasonRequired: false,
	},
	validate: {
		action: "validate",
		label: "Validate",
		variant: "secondary",
		icon: "shield-check",
		description:
			"Re-run the 15-check validation gate against the latest construction run.",
		confirm: false,
		reasonRequired: false,
	},
	approve: {
		action: "approve",
		label: "Approve",
		variant: "success",
		icon: "check-circle",
		description:
			"Move the portfolio to approved. Activation is the next step.",
		confirm: true,
		reasonRequired: true,
	},
	activate: {
		action: "activate",
		label: "Go Live",
		variant: "primary",
		icon: "rocket",
		description:
			"Activate the portfolio. Live monitoring and drift checks begin immediately.",
		confirm: true,
		reasonRequired: false,
	},
	pause: {
		action: "pause",
		label: "Pause",
		variant: "warning",
		icon: "pause",
		description:
			"Pause live monitoring. Holdings stay frozen until you resume.",
		confirm: true,
		reasonRequired: true,
	},
	resume: {
		action: "resume",
		label: "Resume",
		variant: "primary",
		icon: "play-circle",
		description: "Resume live monitoring on the paused portfolio.",
		confirm: false,
		reasonRequired: false,
	},
	archive: {
		action: "archive",
		label: "Archive",
		variant: "danger",
		icon: "archive",
		description:
			"Archive the portfolio. Archived portfolios are read-only and excluded from screens.",
		confirm: true,
		reasonRequired: true,
	},
	reject: {
		action: "reject",
		label: "Reject",
		variant: "danger",
		icon: "x-circle",
		description:
			"Reject the construction. The portfolio returns to a rejected state for rebuild.",
		confirm: true,
		reasonRequired: true,
	},
	rebuild_draft: {
		action: "rebuild_draft",
		label: "Rebuild Draft",
		variant: "warning",
		icon: "rotate-ccw",
		description:
			"Send the portfolio back to draft so calibration and composition can be edited.",
		confirm: true,
		reasonRequired: false,
	},
};

/**
 * Stable display order for the action bar — the backend ``allowed_actions``
 * array order is canonical, but the frontend may want to render certain
 * actions on the right (destructive) and others on the left (forward
 * progression) for visual hierarchy. Phase 5 keeps it simple: render in
 * the order the backend returned, then apply this priority weight to
 * sort destructive actions to the right.
 */
const _ACTION_PRIORITY: Record<PortfolioAction, number> = {
	construct: 0,
	validate: 1,
	approve: 2,
	activate: 3,
	resume: 4,
	pause: 5,
	rebuild_draft: 6,
	reject: 7,
	archive: 8,
};

/**
 * Sort the backend ``allowed_actions`` array into the canonical action
 * bar order so destructive actions land on the right.
 */
export function sortActions(actions: readonly PortfolioAction[]): PortfolioAction[] {
	return [...actions].sort(
		(a, b) => (_ACTION_PRIORITY[a] ?? 99) - (_ACTION_PRIORITY[b] ?? 99),
	);
}
