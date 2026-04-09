// FOUC prevention — set data-theme before first paint.
// Wealth is dark-only (see hooks.server.ts + feedback_shell_architecture).
// We honor an explicit localStorage 'ii-theme=light' if the user really
// forces it, but the default is ALWAYS dark — never prefers-color-scheme.
// An OS in light mode was flipping institutional dashboards white.
(function() {
	var theme = localStorage.getItem('ii-theme');
	if (theme !== 'light') theme = 'dark';
	document.documentElement.setAttribute('data-theme', theme);
})();
