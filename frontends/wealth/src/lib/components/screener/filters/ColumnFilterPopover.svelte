<!--
  ColumnFilterPopover — institutional column-level filter editor.

  Renders a small floating panel anchored to a table header's filter icon.
  The operator dropdown is dynamic based on `column.type`:
    - text    → contains / equals
    - numeric → greater than / less than / between
    - enum    → in (rendered as a multi-select checklist)

  State model:
    - The component owns a *draft* copy of the filter value while the user
      is editing, so rapid-fire checkbox toggles or input keystrokes do not
      spam the parent's $state.
    - On "Apply", the draft is committed via `onApply(draft)`.
    - "Clear" commits `null`, which the parent removes from the
      ColumnFiltersState array.
    - Closing without applying discards the draft.
-->
<script lang="ts">
	import { untrack } from "svelte";
	import { formatAUM } from "@investintell/ui";
	import {
		NUMERIC_OPERATORS,
		TEXT_OPERATORS,
		defaultValueFor,
		isEnumFilter,
		isNumericFilter,
		isTextFilter,
		type ColumnFilterMeta,
		type ColumnFilterValue,
		type EnumFilterValue,
		type NumericFilterValue,
		type TextFilterValue,
	} from "./filter-types.js";

	interface Props {
		column: ColumnFilterMeta;
		value: ColumnFilterValue | null;
		onApply: (next: ColumnFilterValue | null) => void;
		onClose: () => void;
	}

	let { column, value, onApply, onClose }: Props = $props();

	// ── Draft state: seeded once from the incoming value, edited locally. ──
	// The parent mounts/unmounts this component via `{#if openFilterColumn === ...}`
	// so each open is a fresh instance. `untrack` silences
	// state_referenced_locally which doesn't know that semantic.
	let draft = $state<ColumnFilterValue>(
		untrack(() =>
			value && matchesColumnType(value, column.type)
				? structuredClone(value)
				: defaultValueFor(column.type),
		),
	);

	function matchesColumnType(
		v: ColumnFilterValue,
		type: ColumnFilterMeta["type"],
	): boolean {
		if (type === "text") return isTextFilter(v);
		if (type === "numeric") return isNumericFilter(v);
		return isEnumFilter(v);
	}

	// Typed narrowings for template use — Svelte 5 templates do not narrow
	// $state runes on their own, so we re-assert per branch.
	const textDraft = $derived(isTextFilter(draft) ? draft : null);
	const numericDraft = $derived(isNumericFilter(draft) ? draft : null);
	const enumDraft = $derived(isEnumFilter(draft) ? draft : null);

	function commit(): void {
		onApply(draft);
		onClose();
	}

	function clear(): void {
		onApply(null);
		onClose();
	}

	function toggleEnum(value: string): void {
		if (!enumDraft) return;
		const current = enumDraft.values;
		const next = current.includes(value)
			? current.filter((v) => v !== value)
			: [...current, value];
		draft = { op: "in", values: next } satisfies EnumFilterValue;
	}

	function setTextOp(op: TextFilterValue["op"]): void {
		if (!textDraft) return;
		draft = { op, value: textDraft.value };
	}

	function setNumericOp(op: NumericFilterValue["op"]): void {
		if (!numericDraft) return;
		draft = {
			op,
			value: numericDraft.value,
			valueMax:
				op === "between" ? (numericDraft.valueMax ?? null) : undefined,
		};
	}

	function numberOrNull(raw: string): number | null {
		if (raw === "" || raw == null) return null;
		const n = Number(raw);
		return Number.isFinite(n) ? n : null;
	}

	function handleKey(e: KeyboardEvent): void {
		if (e.key === "Escape") {
			e.preventDefault();
			onClose();
		}
		if (e.key === "Enter" && !(e.target instanceof HTMLTextAreaElement)) {
			e.preventDefault();
			commit();
		}
	}

	// ── Click-outside close ──
	let rootEl = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!rootEl) return;
		function onMouseDown(e: MouseEvent): void {
			if (rootEl && !rootEl.contains(e.target as Node)) {
				onClose();
			}
		}
		// Delay the listener one tick so the click that opened the popover
		// does not immediately close it.
		const id = setTimeout(() => {
			document.addEventListener("mousedown", onMouseDown);
		}, 0);
		return () => {
			clearTimeout(id);
			document.removeEventListener("mousedown", onMouseDown);
		};
	});

	function formatNumericChipPreview(v: number | null): string {
		if (v == null) return "";
		if (column.unit === "currency") return formatAUM(v);
		return String(v);
	}
</script>

<div
	bind:this={rootEl}
	class="cfp-root"
	role="dialog"
	aria-label="Filter {column.label}"
	onkeydown={handleKey}
	tabindex="-1"
>
	<header class="cfp-header">
		<span class="cfp-title">Filter {column.label}</span>
	</header>

	{#if textDraft}
		<div class="cfp-body">
			<label class="cfp-field">
				<span class="cfp-field-label">Operator</span>
				<select
					class="cfp-select"
					value={textDraft.op}
					onchange={(e) =>
						setTextOp(
							(e.currentTarget as HTMLSelectElement)
								.value as TextFilterValue["op"],
						)}
				>
					{#each TEXT_OPERATORS as opt (opt.value)}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>
			</label>
			<label class="cfp-field">
				<span class="cfp-field-label">Value</span>
				<input
					class="cfp-input"
					type="text"
					placeholder="Type to filter…"
					value={textDraft.value}
					oninput={(e) => {
						draft = {
							op: textDraft.op,
							value: (e.currentTarget as HTMLInputElement).value,
						};
					}}
				/>
			</label>
		</div>
	{:else if numericDraft}
		<div class="cfp-body">
			<label class="cfp-field">
				<span class="cfp-field-label">Operator</span>
				<select
					class="cfp-select"
					value={numericDraft.op}
					onchange={(e) =>
						setNumericOp(
							(e.currentTarget as HTMLSelectElement)
								.value as NumericFilterValue["op"],
						)}
				>
					{#each NUMERIC_OPERATORS as opt (opt.value)}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>
			</label>
			{#if numericDraft.op === "between"}
				<div class="cfp-field-row">
					<label class="cfp-field cfp-field--half">
						<span class="cfp-field-label">From</span>
						<input
							class="cfp-input"
							type="number"
							inputmode="decimal"
							placeholder="min"
							value={numericDraft.value ?? ""}
							oninput={(e) => {
								draft = {
									op: "between",
									value: numberOrNull(
										(e.currentTarget as HTMLInputElement)
											.value,
									),
									valueMax: numericDraft.valueMax ?? null,
								};
							}}
						/>
					</label>
					<label class="cfp-field cfp-field--half">
						<span class="cfp-field-label">To</span>
						<input
							class="cfp-input"
							type="number"
							inputmode="decimal"
							placeholder="max"
							value={numericDraft.valueMax ?? ""}
							oninput={(e) => {
								draft = {
									op: "between",
									value: numericDraft.value ?? null,
									valueMax: numberOrNull(
										(e.currentTarget as HTMLInputElement)
											.value,
									),
								};
							}}
						/>
					</label>
				</div>
				{#if numericDraft.value != null || numericDraft.valueMax != null}
					<p class="cfp-preview">
						Range: {formatNumericChipPreview(numericDraft.value)} —
						{formatNumericChipPreview(numericDraft.valueMax ?? null)}
					</p>
				{/if}
			{:else}
				<label class="cfp-field">
					<span class="cfp-field-label">Value</span>
					<input
						class="cfp-input"
						type="number"
						inputmode="decimal"
						placeholder={column.unit === "currency" ? "e.g. 1000000000" : "e.g. 10"}
						value={numericDraft.value ?? ""}
						oninput={(e) => {
							draft = {
								op: numericDraft.op,
								value: numberOrNull(
									(e.currentTarget as HTMLInputElement).value,
								),
							};
						}}
					/>
				</label>
				{#if numericDraft.value != null}
					<p class="cfp-preview">
						{numericDraft.op === "gt" ? ">" : "<"}
						{formatNumericChipPreview(numericDraft.value)}
					</p>
				{/if}
			{/if}
		</div>
	{:else if enumDraft && column.options}
		<div class="cfp-body">
			<ul class="cfp-option-list">
				{#each column.options as opt (opt.value)}
					{@const checked = enumDraft.values.includes(opt.value)}
					<li>
						<label class="cfp-option">
							<input
								type="checkbox"
								checked={checked}
								onchange={() => toggleEnum(opt.value)}
							/>
							<span class="cfp-option-label">{opt.label}</span>
						</label>
					</li>
				{/each}
			</ul>
			{#if enumDraft.values.length > 0}
				<p class="cfp-preview">{enumDraft.values.length} selected</p>
			{/if}
		</div>
	{/if}

	<footer class="cfp-footer">
		<button type="button" class="cfp-btn cfp-btn--ghost" onclick={clear}>
			Clear
		</button>
		<div class="cfp-footer-right">
			<button type="button" class="cfp-btn cfp-btn--ghost" onclick={onClose}>
				Cancel
			</button>
			<button type="button" class="cfp-btn cfp-btn--primary" onclick={commit}>
				Apply
			</button>
		</div>
	</footer>
</div>

<style>
	.cfp-root {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 120;
		min-width: 260px;
		max-width: 320px;
		padding: 12px;
		background: #111114;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 10px;
		box-shadow: 0 16px 48px rgba(0, 0, 0, 0.55);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
		color: #e5e7eb;
		text-transform: none;
		letter-spacing: normal;
		text-align: left;
	}
	.cfp-header {
		padding-bottom: 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		margin-bottom: 10px;
	}
	.cfp-title {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #9ca3af;
	}
	.cfp-body {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.cfp-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.cfp-field-row {
		display: flex;
		gap: 8px;
	}
	.cfp-field--half {
		flex: 1;
	}
	.cfp-field-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #6b7280;
	}
	.cfp-select,
	.cfp-input {
		width: 100%;
		padding: 7px 9px;
		background: #0b0b0e;
		border: 1px solid rgba(255, 255, 255, 0.14);
		border-radius: 6px;
		color: #f3f4f6;
		font-family: inherit;
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.cfp-select:focus,
	.cfp-input:focus {
		outline: none;
		border-color: #3b82f6;
		box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.24);
	}
	.cfp-option-list {
		list-style: none;
		padding: 0;
		margin: 0;
		max-height: 220px;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 4px;
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: 6px;
		padding: 6px;
	}
	.cfp-option {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 6px;
		border-radius: 4px;
		cursor: pointer;
	}
	.cfp-option:hover {
		background: rgba(255, 255, 255, 0.05);
	}
	.cfp-option input[type="checkbox"] {
		accent-color: #3b82f6;
	}
	.cfp-option-label {
		font-size: 12px;
		color: #e5e7eb;
	}
	.cfp-preview {
		margin: 0;
		padding: 6px 8px;
		background: rgba(59, 130, 246, 0.1);
		border: 1px solid rgba(59, 130, 246, 0.3);
		border-radius: 4px;
		color: #93c5fd;
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}
	.cfp-footer {
		margin-top: 12px;
		padding-top: 10px;
		border-top: 1px solid rgba(255, 255, 255, 0.08);
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.cfp-footer-right {
		display: flex;
		gap: 6px;
	}
	.cfp-btn {
		padding: 6px 12px;
		border-radius: 6px;
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
		border: 1px solid transparent;
		transition: background 120ms, border-color 120ms, color 120ms;
	}
	.cfp-btn--ghost {
		background: transparent;
		color: #9ca3af;
		border-color: rgba(255, 255, 255, 0.12);
	}
	.cfp-btn--ghost:hover {
		color: #f3f4f6;
		border-color: rgba(255, 255, 255, 0.24);
	}
	.cfp-btn--primary {
		background: #2563eb;
		color: #ffffff;
		border-color: #2563eb;
	}
	.cfp-btn--primary:hover {
		background: #1d4ed8;
		border-color: #1d4ed8;
	}
</style>
