/** Navigation item for Sidebar component. */
export interface NavItem {
	label: string;
	href: string;
	icon?: string;
	badge?: string | number;
	children?: NavItem[];
}

/** Tenant branding configuration from GET /api/v1/branding. */
export interface BrandingConfig {
	primary_color: string;
	secondary_color: string;
	accent_color: string;
	light_color: string;
	highlight_color: string;
	surface_color: string;
	surface_alt_color: string;
	border_color: string;
	text_primary: string;
	text_secondary: string;
	text_muted: string;
	font_sans: string;
	font_mono: string;
	logo_light_url: string | null;
	logo_dark_url: string | null;
	favicon_url: string | null;
	org_name: string;
	org_slug: string;
}
