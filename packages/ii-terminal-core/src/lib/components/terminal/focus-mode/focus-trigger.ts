import type { FocusModeEntityKind } from "./FocusMode.svelte";

export type FocusTriggerInitialTab =
	| "performance"
	| "profile"
	| "peers"
	| "analysis"
	| "holdings"
	| "sectors"
	| "network";

export interface FocusTriggerOptions {
	entityKind: FocusModeEntityKind;
	entityId: string;
	entityLabel?: string;
	ticker?: string | null;
	instrumentId?: string | null;
	initialTab?: FocusTriggerInitialTab;
}

/**
 * Svelte use:action that makes any element a FocusMode trigger.
 *
 * Usage:
 *   <tr use:focusTrigger={{ entityKind: "fund", entityId: row.id, entityLabel: row.name }}>
 *
 * On click, dispatches a CustomEvent "focustrigger" on the element,
 * which the page-level listener picks up via onfocustrigger={handler}.
 * This decouples the grid row from knowing about FocusMode internals.
 */
export function focusTrigger(
	node: HTMLElement,
	options: FocusTriggerOptions,
): { update(opts: FocusTriggerOptions): void; destroy(): void } {
	let currentOptions = options;

	function handleClick(event: MouseEvent) {
		// Don't trigger if the click was on an interactive element inside the row
		// (button, link, input) — those have their own handlers
		const target = event.target as HTMLElement;
		if (target.closest("button, a, input, select, textarea")) return;

		node.dispatchEvent(
			new CustomEvent("focustrigger", {
				bubbles: true,
				detail: { ...currentOptions },
			}),
		);
	}

	node.addEventListener("click", handleClick);
	node.style.cursor = "pointer";

	return {
		update(opts: FocusTriggerOptions) {
			currentOptions = opts;
		},
		destroy() {
			node.removeEventListener("click", handleClick);
			node.style.cursor = "";
		},
	};
}
