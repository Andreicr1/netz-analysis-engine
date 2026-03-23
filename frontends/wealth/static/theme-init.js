// FOUC prevention — set data-theme before first paint.
// Loaded as external script to avoid CSP nonce/unsafe-inline conflicts.
(function() {
	var theme = localStorage.getItem('netz-theme');
	if (theme !== 'dark' && theme !== 'light') {
		theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
	}
	document.documentElement.setAttribute('data-theme', theme);
})();
