/**
 * Test-only stub barrel for `@investintell/ui`. Used by
 * `NewPortfolioDialog.test.ts` via `vi.mock("@investintell/ui", ...)`
 * to bypass the DataTable + @tanstack/svelte-table transitive load
 * which the vitest ESM resolver cannot transform.
 *
 * The stubs mirror only the contract NewPortfolioDialog uses:
 *   - Dialog: open / onOpenChange / title / children
 *   - Button: type / disabled / onclick / children
 *   - FormField: label / required / children
 *   - Input: bind:value / maxlength / disabled / required
 *   - Select: bind:value / options / disabled
 *
 * Do not import this module from production code — it lives under
 * `__tests__/` for a reason.
 */
export { default as Dialog } from "./Dialog.svelte";
export { default as Button } from "./Button.svelte";
export { default as FormField } from "./FormField.svelte";
export { default as Input } from "./Input.svelte";
export { default as Select } from "./Select.svelte";
