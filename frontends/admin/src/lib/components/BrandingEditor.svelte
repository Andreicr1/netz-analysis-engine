<!--
  Branding Editor — color pickers, font selector, logo upload, live preview.
-->
<script lang="ts">
	import { SectionCard } from "@netz/ui";

	let { branding, orgId }: { branding: Record<string, string>; orgId: string } = $props();

	const HEX_RE = /^#[0-9a-fA-F]{6}$/;

	const colorFields = [
		{ key: "primary_color", label: "Primary" },
		{ key: "secondary_color", label: "Secondary" },
		{ key: "accent_color", label: "Accent" },
		{ key: "highlight_color", label: "Highlight" },
		{ key: "surface_color", label: "Surface" },
		{ key: "border_color", label: "Border" },
		{ key: "text_primary", label: "Text Primary" },
		{ key: "text_secondary", label: "Text Secondary" },
	];

	let values = $state<Record<string, string>>({ ...branding });
	let errors = $state<Record<string, string>>({});

	function validateHex(key: string, value: string) {
		if (!HEX_RE.test(value)) {
			errors[key] = "Must be 6-char hex (e.g. #1B365D)";
		} else {
			delete errors[key];
		}
		values[key] = value;
	}

	const hasErrors = $derived(Object.keys(errors).length > 0);
</script>

<div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
	<!-- Color Pickers -->
	<SectionCard title="Brand Colors">
		<div class="space-y-3">
			{#each colorFields as field}
				<div class="flex items-center gap-3">
					<input
						type="color"
						value={values[field.key] ?? "#000000"}
						oninput={(e) => validateHex(field.key, e.currentTarget.value)}
						class="h-8 w-8 cursor-pointer rounded border border-[var(--netz-border)]"
					/>
					<div class="flex-1">
						<label for="color-{field.key}" class="text-xs text-[var(--netz-text-muted)]">
							{field.label}
						</label>
						<input
							id="color-{field.key}"
							type="text"
							value={values[field.key] ?? ""}
							oninput={(e) => validateHex(field.key, e.currentTarget.value)}
							class="w-full rounded border border-[var(--netz-border)] bg-[var(--netz-surface)] px-2 py-1 font-mono text-xs text-[var(--netz-text-primary)]"
							placeholder="#000000"
						/>
					</div>
					{#if errors[field.key]}
						<span class="text-xs text-red-500">{errors[field.key]}</span>
					{/if}
				</div>
			{/each}
		</div>
	</SectionCard>

	<!-- Live Preview -->
	<SectionCard title="Preview">
		<div
			class="rounded-lg border p-4"
			style="background: {values.surface_color ?? '#fff'}; border-color: {values.border_color ??
				'#e2e8f0'};"
		>
			<div
				class="mb-3 h-8 rounded"
				style="background: {values.primary_color ?? '#1B365D'};"
			></div>
			<p
				style="color: {values.text_primary ?? '#0F172A'};"
				class="mb-1 text-sm font-medium"
			>
				Sample heading text
			</p>
			<p style="color: {values.text_secondary ?? '#475569'};" class="mb-2 text-xs">
				Secondary description text for preview
			</p>
			<div class="flex gap-2">
				<span
					class="rounded px-2 py-1 text-xs text-white"
					style="background: {values.primary_color ?? '#1B365D'};"
				>
					Primary
				</span>
				<span
					class="rounded px-2 py-1 text-xs text-white"
					style="background: {values.accent_color ?? '#8B9DAF'};"
				>
					Accent
				</span>
				<span
					class="rounded px-2 py-1 text-xs text-white"
					style="background: {values.highlight_color ?? '#FF975A'};"
				>
					Highlight
				</span>
			</div>
		</div>
	</SectionCard>
</div>

<!-- Save Button -->
<div class="mt-6 flex justify-end">
	<button
		disabled={hasErrors}
		class="rounded-md bg-[var(--netz-brand-primary)] px-6 py-2 text-sm text-white hover:opacity-90 disabled:opacity-50"
	>
		Save Branding
	</button>
</div>
