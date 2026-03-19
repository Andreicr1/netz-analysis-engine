<!--
  JinjaEditor — CodeMirror 6 editor for Jinja2 templates.
  Lazy-loaded on mount. No external Jinja language package required —
  uses StreamLanguage with a minimal Jinja2 tokenizer for bracket/variable/comment
  highlighting plus CodeMirror's core editing UX (indent, undo, line wrap).
-->
<script lang="ts">
	import { onMount } from "svelte";
	import type { EditorView } from "@codemirror/view";

	interface Props {
		value?: string;
		readonly?: boolean;
		ariaLabel?: string;
		class?: string;
		onChange?: (value: string) => void;
	}

	let {
		value = $bindable(""),
		readonly = false,
		ariaLabel = "Jinja2 template editor",
		class: className,
		onChange,
	}: Props = $props();

	let editorHost: HTMLDivElement | undefined;
	let view: EditorView | undefined;
	let isInternalUpdate = false;
	let editorReady = $state(false);

	function syncExternalValue(nextValue: string) {
		if (!view) return;
		const currentValue = view.state.doc.toString();
		if (nextValue === currentValue) return;
		isInternalUpdate = true;
		try {
			view.dispatch({
				changes: { from: 0, to: currentValue.length, insert: nextValue },
			});
		} finally {
			isInternalUpdate = false;
		}
	}

	$effect(() => {
		syncExternalValue(value ?? "");
	});

	onMount(() => {
		let disposed = false;
		let cleanup = () => {};

		void (async () => {
			const [
				{ EditorState },
				{ EditorView, keymap },
				{ indentWithTab },
				{ StreamLanguage },
			] = await Promise.all([
				import("@codemirror/state"),
				import("@codemirror/view"),
				import("@codemirror/commands"),
				import("@codemirror/language"),
			]);

			if (disposed || !editorHost) return;

			// Minimal Jinja2 StreamLanguage tokenizer — covers {%, {{, {#, #}, %}, }}
			const jinjaLanguage = StreamLanguage.define({
				token(stream) {
					// Block tags: {% ... %}
					if (stream.match("{%")) {
						while (!stream.eol()) {
							if (stream.match("%}")) break;
							stream.next();
						}
						return "keyword";
					}
					// Variables: {{ ... }}
					if (stream.match("{{")) {
						while (!stream.eol()) {
							if (stream.match("}}")) break;
							stream.next();
						}
						return "variableName";
					}
					// Comments: {# ... #}
					if (stream.match("{#")) {
						while (!stream.eol()) {
							if (stream.match("#}")) break;
							stream.next();
						}
						return "comment";
					}
					// Consume one character as plain text
					stream.next();
					return null;
				},
			});

			const extensions = [
				EditorView.lineWrapping,
				EditorView.editable.of(!readonly),
				EditorView.theme({
					"&": {
						backgroundColor: "var(--netz-surface)",
						color: "var(--netz-text-primary)",
						fontSize: "12px",
						fontFamily:
							"ui-monospace, SFMono-Regular, SF Mono, Consolas, Liberation Mono, monospace",
					},
					"&.cm-focused": {
						outline: "2px solid var(--netz-brand-secondary)",
						outlineOffset: "2px",
					},
					".cm-content": {
						caretColor: "var(--netz-brand-primary)",
					},
					".cm-gutters": {
						backgroundColor: "var(--netz-surface-alt)",
						color: "var(--netz-text-secondary)",
						borderRight: "1px solid var(--netz-border)",
					},
					".tok-keyword": {
						color: "var(--netz-brand-primary)",
						fontWeight: "600",
					},
					".tok-variableName": {
						color: "var(--netz-brand-secondary)",
					},
					".tok-comment": {
						color: "var(--netz-text-muted)",
						fontStyle: "italic",
					},
				}),
				EditorView.contentAttributes.of({
					role: "textbox",
					"aria-multiline": "true",
					"aria-label": ariaLabel,
					spellcheck: "false",
					autocapitalize: "off",
					autocorrect: "off",
				}),
				jinjaLanguage,
				keymap.of([indentWithTab]),
				EditorView.updateListener.of((update) => {
					if (!update.docChanged || isInternalUpdate) return;
					value = update.state.doc.toString();
					onChange?.(value);
				}),
			];

			view = new EditorView({
				state: EditorState.create({ doc: value ?? "", extensions }),
				parent: editorHost,
			});
			editorReady = true;

			cleanup = () => {
				view?.destroy();
				view = undefined;
			};

			if (disposed) cleanup();
		})();

		return () => {
			disposed = true;
			cleanup();
		};
	});
</script>

<div class={className}>
	<div
		bind:this={editorHost}
		class="min-h-96 overflow-hidden rounded-md border border-(--netz-border) bg-(--netz-surface) {readonly ? 'opacity-60' : ''}"
		aria-busy={editorReady ? "false" : "true"}
	></div>
	{#if !editorReady}
		<p class="mt-1 text-xs text-(--netz-text-muted)">Loading editor…</p>
	{:else}
		<p class="mt-1 text-xs text-(--netz-text-muted)">Press Escape to leave the editor. Tab to indent.</p>
	{/if}
</div>
