<!--
  Auth callback — loads Clerk JS ONCE to sync __session cookie.
  Isolated from the main app to prevent loops.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { browser } from "$app/environment";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let status = $state("Authenticating...");

	function clerkDomain(pk: string): string {
		const encoded = pk.replace(/^pk_(test|live)_/, "");
		return atob(encoded).replace(/\$$/, "");
	}

	onMount(async () => {
		if (!browser) return;

		const pk = data.clerkPublishableKey ?? "";
		if (!pk) {
			status = "Configuration error: missing publishable key.";
			return;
		}

		try {
			const domain = clerkDomain(pk);

			// Load Clerk JS
			await new Promise<void>((resolve, reject) => {
				const script = document.createElement("script");
				script.setAttribute("data-clerk-publishable-key", pk);
				script.async = true;
				script.src = `https://${domain}/npm/@clerk/clerk-js@5/dist/clerk.browser.js`;
				script.onload = () => resolve();
				script.onerror = () => reject(new Error("Failed to load Clerk"));
				document.head.appendChild(script);
			});

			const ClerkClass = (window as any).Clerk;
			if (!ClerkClass) {
				status = "Failed to initialize authentication.";
				return;
			}

			// Initialize Clerk
			let clerk: any;
			if (typeof ClerkClass === "function" && !ClerkClass.load) {
				clerk = new ClerkClass(pk);
			} else {
				clerk = ClerkClass;
			}
			await clerk.load({ publishableKey: pk, routerPush: () => {}, routerReplace: () => {} });

			// Get session token and set cookie
			if (clerk.session) {
				// Try custom template first (3600s lifetime), fall back to default session token
				let token = await clerk.session.getToken({ template: "investintell-wealth" }).catch(() => null);
				if (!token) {
					console.warn("investintell-wealth template unavailable, using default session token");
					token = await clerk.session.getToken();
				}
				if (token) {
					document.cookie = `__session=${token}; path=/; secure; samesite=lax; max-age=3600`;
					// Success — redirect to app
					window.location.href = "/";
					return;
				}
			}

			// No session — user not signed in, redirect to Clerk
			// Guard against redirect loops: if we've been here recently, show error instead
			const loopKey = "auth_callback_ts";
			const lastAttempt = parseInt(sessionStorage.getItem(loopKey) ?? "0", 10);
			const now = Date.now();
			if (now - lastAttempt < 10_000) {
				status = "Authentication loop detected. Please clear cookies and try again.";
				sessionStorage.removeItem(loopKey);
				return;
			}
			sessionStorage.setItem(loopKey, String(now));

			status = "No active session. Redirecting to sign-in...";
			setTimeout(() => {
				if (import.meta.env.DEV) {
					window.location.href = "/";
					return;
				}
				window.location.href = `https://accounts.investintell.com/sign-in?redirect_url=${encodeURIComponent(window.location.href)}`;
			}, 1000);
		} catch {
			status = "Authentication failed. Redirecting...";
			setTimeout(() => {
				if (import.meta.env.DEV) {
					window.location.href = "/";
					return;
				}
				window.location.href = "https://accounts.investintell.com/sign-in?redirect_url=" + encodeURIComponent(window.location.href);
			}, 2000);
		}
	});
</script>

<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0a0a0f;color:#94a3b8;font-family:system-ui;">
	<p>{status}</p>
</div>
