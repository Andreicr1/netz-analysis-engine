<!--
  II Terminal — X1 scaffold placeholder.

  Routes (live, allocation, macro, screener, research, alerts) land in X2
  when they move out of frontends/wealth/src/routes/(terminal)/.
-->
<script lang="ts">
	const env = import.meta.env.VITE_ENV ?? "dev";
	const sha = import.meta.env.VITE_BUILD_SHA ?? "local-dev";
</script>

<svelte:head>
	<title>II Terminal — Scaffold</title>
</svelte:head>

<main class="min-h-screen bg-black text-white font-sans antialiased px-10 py-10">
	<header class="mb-12">
		<p class="text-xs uppercase tracking-[0.24em] text-white/40">InvestIntell</p>
		<h1 class="mt-2 text-3xl font-semibold">II Terminal</h1>
		<p class="mt-1 text-sm text-white/60">
			Institutional investment workstation.
		</p>
	</header>

	<section class="max-w-xl space-y-4 text-sm leading-relaxed text-white/80">
		<p>
			II Terminal scaffolded. Routes populated in X2.
		</p>
		<p class="text-white/50">
			This placeholder proves the SvelteKit app boots at
			<code class="font-mono text-white/70">terminal.investintell.com</code>
			with the shared Clerk session and the @investintell/ui design tokens.
		</p>
		<div class="pt-4">
			<a
				href="/live"
				class="inline-flex h-10 items-center rounded-full border border-white/20 bg-white/5 px-5 text-xs font-medium uppercase tracking-[0.16em] text-white/80 transition hover:border-white/40 hover:bg-white/10"
			>
				Placeholder nav → /live (404 until X2)
			</a>
		</div>
	</section>

	<footer class="mt-16 text-[11px] font-mono text-white/30">
		env={env} · build={sha}
	</footer>
</main>
