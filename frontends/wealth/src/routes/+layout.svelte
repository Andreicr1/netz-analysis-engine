<!--
  Root layout — auth context, branding injection, session expiry.
  Navigation is handled by (app)/+layout.svelte via AppShell + Sidebar.
-->
<script lang="ts">
	import "../app.css";
	import { page } from "$app/stores";
	import { goto, invalidateAll } from "$app/navigation";
	import { browser } from "$app/environment";
	import { setContext, onMount } from "svelte";
	import { ErrorBoundary, Toast } from "@netz/ui";
	import { injectBranding, startSessionExpiryMonitor, setConflictHandler, setAuthRedirectHandler } from "@netz/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	let showExpiryWarning = $state(false);
	let conflictMessage = $state<string | null>(null);

	// Auth context — provides getToken to child components.
	// If server has token (from __session cookie), use it.
	// Otherwise, Clerk JS will provide it after sync.
	let clerkToken = $state<string | undefined>(data.token);
	setContext("netz:getToken", () => Promise.resolve(clerkToken));

	// ── Clerk JS session sync ────────────────────────────────────
	// Clerk hosted sign-in sets cookies on the Clerk domain, not ours.
	// We need Clerk JS running to sync __session cookie to our domain.
	function clerkDomain(pk: string): string {
		const encoded = pk.replace(/^pk_(test|live)_/, "");
		return atob(encoded).replace(/\$$/, "");
	}

	onMount(async () => {
		if (!browser || import.meta.env.DEV) return;

		const pk = data.clerkPublishableKey ?? "";
		if (!pk) return;

		// Already have a valid token from cookie — no need to load Clerk JS
		if (data.token && data.token !== "dev-token") return;

		// Load Clerk JS to sync session
		const domain = clerkDomain(pk);
		try {
			await new Promise<void>((resolve, reject) => {
				if (document.querySelector("script[data-clerk-script]")) { resolve(); return; }
				const script = document.createElement("script");
				script.setAttribute("data-clerk-script", "");
				script.setAttribute("data-clerk-publishable-key", pk);
				script.async = true;
				script.src = `https://${domain}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`;
				script.onload = () => resolve();
				script.onerror = () => reject(new Error("Clerk JS load failed"));
				document.head.appendChild(script);
			});

			const ClerkClass = (window as any).Clerk;
			if (!ClerkClass) return;

			let clerk: any;
			if (typeof ClerkClass === "function" && !ClerkClass.load) {
				clerk = new ClerkClass(pk);
			} else {
				clerk = ClerkClass;
			}
			await clerk.load({ publishableKey: pk, routerPush: () => {}, routerReplace: () => {} });

			// Sync session token to cookie and reload for server-side access
			if (clerk.session) {
				const token = await clerk.session.getToken();
				if (token) {
					document.cookie = `__session=${token}; path=/; secure; samesite=lax`;
					clerkToken = token;
					// Reload so server-side has the cookie for API calls
					window.location.reload();
					return;
				}
			}

			// Listen for future session changes (token refresh)
			clerk.addListener(({ session }: any) => {
				if (session) {
					session.getToken().then((t: string) => {
						if (t) {
							document.cookie = `__session=${t}; path=/; secure; samesite=lax`;
							clerkToken = t;
						}
					});
				}
			});
		} catch {
			// Clerk JS failed to load — redirect to sign-in
		}
	});

	// Branding CSS injection
	$effect(() => {
		if (typeof document !== "undefined" && data.branding) {
			injectBranding(document.documentElement, data.branding);
		}
	});

	// Session expiry monitor
	$effect(() => {
		if (data.token && data.token !== "dev-token") {
			const cleanup = startSessionExpiryMonitor(data.token, () => {
				showExpiryWarning = true;
			});
			return cleanup;
		}
	});

	// 401 redirect + conflict handler
	$effect(() => {
		setAuthRedirectHandler(() => {
			window.location.href = "https://accounts.investintell.com/sign-in?redirect_url=" + encodeURIComponent(window.location.href);
		});
		setConflictHandler((msg: string) => {
			conflictMessage = msg;
			invalidateAll();
			setTimeout(() => { conflictMessage = null; }, 4000);
		});
	});
</script>

<ErrorBoundary>
	{@render children()}
</ErrorBoundary>

{#if showExpiryWarning}
	<div class="fixed inset-0 z-50 flex items-center justify-center" style="background: var(--netz-surface-overlay, rgba(0,0,0,0.5))">
		<div class="mx-4 w-full max-w-md rounded-lg bg-(--netz-surface-elevated) p-6 shadow-xl">
			<h2 class="mb-2 text-lg font-semibold text-(--netz-text-primary)">Session Expiring</h2>
			<p class="mb-4 text-sm text-(--netz-text-secondary)">
				Your session expires in 5 minutes. Please save your work and renew your access.
			</p>
			<div class="flex justify-end gap-3">
				<button
					class="rounded-md px-4 py-2 text-sm font-medium text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)"
					onclick={() => showExpiryWarning = false}
				>
					Dismiss
				</button>
				<button
					class="rounded-md bg-(--netz-brand-primary) px-4 py-2 text-sm font-medium text-white hover:opacity-90"
					onclick={() => { showExpiryWarning = false; window.location.reload(); }}
				>
					Renew Session
				</button>
			</div>
		</div>
	</div>
{/if}

{#if conflictMessage}
	<Toast message={conflictMessage} type="warning" duration={4000} onDismiss={() => conflictMessage = null} />
{/if}
