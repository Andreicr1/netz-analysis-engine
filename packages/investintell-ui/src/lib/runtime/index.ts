/**
 * @investintell/ui runtime kit — Stability Guardrails frontend primitives.
 *
 * See `docs/reference/stability-guardrails.md` and
 * `docs/superpowers/specs/2026-04-07-stability-guardrails-design.md`
 * for the design and the six non-negotiable principles.
 *
 * Use:
 *   import {
 *     createTickBuffer,
 *     createMountedGuard,
 *   } from "@investintell/ui/runtime";
 *
 * All primitives here are:
 * - Plain TypeScript (no Svelte runes import) so they can be unit
 *   tested under vitest without mounting a component.
 * - Browser-aware but safe under SSR — the visibility listener is
 *   only attached when `document` exists.
 * - Documented with behavior guarantees, not just signatures.
 */

export {
	createTickBuffer,
	type TickBuffer,
	type TickBufferConfig,
} from "./tick-buffer.svelte";
export {
	createMountedGuard,
	type MountedGuard,
} from "./listener-safe.svelte";
export {
	errData,
	isLoaded,
	isStale,
	okData,
	type RouteData,
	type RouteError,
} from "./route-contract";

// Re-export the analytical panel-state components under their Panel*
// aliases from the design spec. The underlying components live in
// ../components/analytical/ so every design-system consumer can
// still import them from the generic path; this barrel adds the
// charter-named handle.
export { default as PanelErrorState } from "../components/analytical/PanelErrorState.svelte";
export { default as PanelEmptyState } from "../components/analytical/EmptyState.svelte";
