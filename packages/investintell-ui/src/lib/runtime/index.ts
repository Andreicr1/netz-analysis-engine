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
