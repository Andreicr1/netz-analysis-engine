<!--
  CodeEditor — CodeMirror 6 JSON editor with schema linting.
  Section 3.Admin.1.

  Jinja2 mode note: `@codemirror/lang-jinja` is NOT a real package and does not exist on npm.
  Jinja2 template editing uses JinjaEditor.svelte, which implements a custom StreamLanguage
  tokenizer covering {%, {{, and {# delimiters — no third-party Jinja grammar required.

  {@html} audit: frontends/admin has one {@html} usage in PromptEditor.svelte (line ~330).
  It is sanitized via DOMPurify.sanitize() before rendering. All future {@html} additions
  in this frontend MUST be wrapped with DOMPurify.sanitize() to prevent stored XSS.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import type { EditorView } from "@codemirror/view";

	interface Props {
		value?: string;
		schema: Record<string, unknown>;
		ariaLabel: string;
		class?: string;
	}

	let {
		value = $bindable(""),
		schema,
		ariaLabel,
		class: className,
	}: Props = $props();

	let editorHost: HTMLDivElement | undefined;
	let view: EditorView | undefined;
	let applySchema:
		| ((target: EditorView, nextSchema?: Record<string, unknown>) => void)
		| undefined;
	let isInternalUpdate = false;
	let editorReady = $state(false);

	const instructionsId = "code-editor-instructions";

	function syncExternalValue(nextValue: string) {
		if (!view) {
			return;
		}

		const currentValue = view.state.doc.toString();
		if (nextValue === currentValue) {
			return;
		}

		isInternalUpdate = true;
		try {
			view.dispatch({
				changes: {
					from: 0,
					to: currentValue.length,
					insert: nextValue,
				},
			});
		} finally {
			isInternalUpdate = false;
		}
	}

	$effect(() => {
		syncExternalValue(value ?? "");
	});

	$effect(() => {
		if (view && applySchema) {
			applySchema(view, schema);
		}
	});

	onMount(() => {
		let disposed = false;
		let cleanup = () => {};
		void (async () => {
			const [
				{ EditorState },
				{ EditorView, keymap },
				{ json, jsonParseLinter },
				{ linter },
				{ indentWithTab },
				{ jsonSchemaLinter, handleRefresh, stateExtensions, updateSchema: setSchema },
			] = await Promise.all([
				import("@codemirror/state"),
				import("@codemirror/view"),
				import("@codemirror/lang-json"),
				import("@codemirror/lint"),
				import("@codemirror/commands"),
				import("codemirror-json-schema"),
			]);

			if (disposed || !editorHost) {
				return;
			}

			const extensions = [
				EditorView.lineWrapping,
				EditorView.theme({
					"&": {
						backgroundColor: "var(--netz-surface)",
						color: "var(--netz-text-primary)",
					},
					"&.cm-focused": {
						outline: "2px solid var(--netz-brand-secondary)",
						outlineOffset: "2px",
					},
					".cm-content": {
						caretColor: "var(--netz-brand-primary)",
						fontFamily:
							"ui-monospace, SFMono-Regular, SF Mono, Consolas, Liberation Mono, monospace",
					},
					".cm-gutters": {
						backgroundColor: "var(--netz-surface-alt)",
						color: "var(--netz-text-secondary)",
						borderRight: "1px solid var(--netz-border)",
					},
				}),
				EditorView.contentAttributes.of({
					role: "textbox",
					"aria-multiline": "true",
					"aria-label": ariaLabel,
					"aria-describedby": instructionsId,
					spellcheck: "false",
					autocapitalize: "off",
					autocorrect: "off",
				}),
				json(),
				linter(jsonParseLinter(), { delay: 300 }),
				linter(jsonSchemaLinter(), { delay: 750, needsRefresh: handleRefresh }),
				keymap.of([indentWithTab]),
				stateExtensions(schema as never),
				EditorView.updateListener.of((update) => {
					if (!update.docChanged || isInternalUpdate) {
						return;
					}

					value = update.state.doc.toString();
				}),
			];

			view = new EditorView({
				state: EditorState.create({
					doc: value ?? "",
					extensions,
				}),
				parent: editorHost,
			});
			applySchema = setSchema;
			editorReady = true;
			applySchema(view, schema);

			cleanup = () => {
				view?.destroy();
				view = undefined;
				applySchema = undefined;
			};

			if (disposed) {
				cleanup();
			}
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
		class="min-h-72 overflow-hidden rounded-xl border border-[var(--netz-border)] bg-[var(--netz-surface)]"
		aria-busy={editorReady ? "false" : "true"}
	></div>
	<p
		id={instructionsId}
		class="mt-3 text-sm leading-6 text-[var(--netz-text-secondary)]"
	>
		Press Escape to leave the editor, Tab to indent.
	</p>
</div>
