1 # Admin UX Compliance Audit
2 +
3 +## 1. Core Philosophy
4 +
5 +### Finding 1
6 +- Domain: Admin
7 +- Principle: "System state is the first thing visible on every load"
8 +- Status: PARTIALLY COMPLIANT
9 +- Code Evidence:
10 + - `frontends/admin/src/routes/(admin)/+page.server.ts:4-5` redirects `/` to `/health`, so the default route l
ands on health.
11 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:32-45` renders the service grid first on the health
page.
12 + - `frontends/admin/src/routes/(admin)/health/+page.server.ts:22-38` silently falls back to empty arrays on AP
I failures, so degraded state can disappear instead of surfacing.
13 +- UI / Behavior Evidence:
14 + - Operators do land on health by default, but if health APIs fail they see empty states like "No service heal
th data available" instead of an explicit degraded system state.
15 +- Gap Description:
16 + - The entry flow is correct, but failure handling hides operational degradation instead of making it immediat
ely legible.
17 +- Severity: HIGH
18 +- Root Cause: missing enforcement of shared patterns
19 +- Recommended Fix:
20 + - In `frontends/admin/src/routes/(admin)/health/+page.server.ts`, preserve loader errors in returned page dat
a instead of swallowing them.
21 + - In `frontends/admin/src/routes/(admin)/health/+page.svelte`, replace empty fallback copy with a high-visibi
lity degraded state banner and per-section error panels.
22 +
23 +### Finding 2
24 +- Domain: Admin
25 +- Principle: "Configuration changes are consequential — treat them as such"
26 +- Status: NON-COMPLIANT
27 +- Code Evidence:
28 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:57-65` validates JSON, but only for plain JSON pars
e success and without a debounced, richer editor experience.
29 + - `frontends/admin/src/lib/components/ConfigDiffViewer.svelte:31-34` loads diff data with a hard-coded placeh
older `org_id`, so the diff is not tied to the real tenant context.
30 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:197-203` confirms global default updates, but the d
ialog message omits the exact tenant count and exact impact scope required by the spec.
31 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:155-160` uses inline messages instead of durable au
dit/history UI.
32 +- UI / Behavior Evidence:
33 + - Config editing has basic validation and confirmation, but the impact scope is incomplete, the diff is unrel
iable, and there is no visible audit-history surface proving the change was logged.
34 +- Gap Description:
35 + - The current config flow implements some safeguards, but not the full consequence-aware workflow the admin s
pec requires.
36 +- Severity: HIGH
37 +- Root Cause: architectural inconsistency
38 +- Recommended Fix:
39 + - Pass the active `orgId` from `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte` i
nto both `ConfigEditor.svelte` and `ConfigDiffViewer.svelte`.
40 + - Replace the plain `<textarea>` editor in `frontends/admin/src/lib/components/ConfigEditor.svelte` with a sy
ntax-highlighting JSON editor component in `@netz/ui`.
41 + - Add an audit/history panel to `ConfigEditor.svelte` that renders timestamp, actor, before/after diff, and c
onflict metadata.
42 +
43 +### Finding 3
44 +- Domain: Admin
45 +- Principle: "Every destructive action is explicit and logged"
46 +- Status: PARTIALLY COMPLIANT
47 +- Code Evidence:
48 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte:148-154`, `frontends/admin/src/route
         s/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:154-161`, `frontends/admin/src/lib/components/ConfigEdito
         r.svelte:188-203`, and `frontends/admin/src/lib/components/PromptEditor.svelte:304-320` do use `ConfirmDialog`.
49 + - `packages/ui/src/lib/components/ConfirmDialog.svelte:45-63` provides the shared confirmation primitive.
50 + - None of the affected Admin pages render an entity history/audit section after the destructive action comple
tes.
51 + - Most mutation results are surfaced as inline text (`ConfigEditor.svelte:155-160`, `PromptEditor.svelte:204-
         206`) rather than the specified toast pattern.
52 +- UI / Behavior Evidence:
53 + - Confirmation exists for several destructive actions, but the scope text is often generic and there is no vi
sible "action executed → toast → entity history updated" loop.
54 +- Gap Description:
55 + - Explicit confirmation is partly implemented; explicit scope, toast feedback, and visible audit logging are
not.
56 +- Severity: HIGH
57 +- Root Cause: missing enforcement of shared patterns
58 +- Recommended Fix:
59 + - Standardize Admin mutations on a shared `@netz/ui` mutation pattern that combines `ActionButton`, `ConfirmD
         ialog`, `Toast`, and post-mutation history refresh.
60 + - Update `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte`, `.../branding/+page.svelte`
, `frontends/admin/src/lib/components/ConfigEditor.svelte`, and `PromptEditor.svelte` to include entity-specifi
c scope in dialog copy and render mutation history.
61 +
62 +### Finding 4
63 +- Domain: Admin
64 +- Principle: "Operators are technical — do not simplify away useful information"
65 +- Status: NON-COMPLIANT
66 +- Code Evidence:
67 + - `frontends/admin/src/routes/(admin)/health/+page.server.ts:22-38` suppresses fetch errors completely.
68 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:24-26` suppresses refresh failures completely.
69 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:50-52` collapses load failures to "Failed to load c
onfig".
70 + - `frontends/admin/src/lib/components/PromptEditor.svelte:75-88` collapses preview/validation failures to gen
eric messages.
71 +- UI / Behavior Evidence:
72 + - Operators receive empty states or generic error strings instead of raw backend details, HTTP failure contex
t, or concrete technical traces.
73 +- Gap Description:
74 + - The frontend still favors friendly/generalized fallbacks in several critical operator surfaces.
75 +- Severity: MEDIUM
76 +- Root Cause: other (silent fallback handling in loaders and components)
77 +- Recommended Fix:
78 + - In the listed files, surface backend `detail`, status code, and request target in the UI instead of generic
fallback text.
79 + - Add expandable raw-error panels for health, config, and prompt operations.
80 +
81 +### Finding 5
82 +- Domain: Admin
83 +- Principle: "Tenant context is always explicit"
84 +- Status: NON-COMPLIANT
85 +- Code Evidence:
86 + - `frontends/admin/src/lib/components/TenantCard.svelte:25-35` shows name, vertical, slug, config count, and
asset count, but omits `organization_id`.
87 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte:60-67` only shows the tenant name in
the page header.
88 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:199-200` confirms global default updates as "all te
nants without overrides" instead of the required explicit "Affects: ALL TENANTS" language.
89 +- UI / Behavior Evidence:
90 + - On tenant list and tenant detail pages, operators cannot continuously anchor themselves on both slug and or
g_id from the primary header area.
91 +- Gap Description:
92 + - Tenant identity and impact scope are not consistently front-loaded in tenant-scoped or global-impact action
s.
93 +- Severity: HIGH
94 +- Root Cause: missing enforcement of shared patterns
95 +- Recommended Fix:
96 + - Update `frontends/admin/src/lib/components/TenantCard.svelte` to display `organization_id` in monospace wit
h copy affordance.
97 + - Update `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte` and `.../branding/+page.svel
         te` headers to always show name, slug, org_id, plan, and status together.
98 + - Update `frontends/admin/src/lib/components/ConfigEditor.svelte` confirm copy to include `Affects: ALL TENAN
         TS`.
99 +
100 +## 2. Global UI Rules
101 +
102 +### Finding 6
103 +- Domain: Admin
104 +- Principle: "Color system (strict semantic meaning)"
105 +- Status: NON-COMPLIANT
106 +- Code Evidence:
107 + - `packages/ui/src/lib/styles/tokens.css:30-35` defines only generic semantic tokens (`--netz-success`, `--ne
         tz-warning`, `--netz-danger`, `--netz-info`), not the Admin-specific health/config/scope variables from the spe
c.
108 + - `packages/ui/src/lib/components/StatusBadge.svelte:14-48` hard-codes generic color maps instead of using Ad
min semantic CSS variables.
109 + - `frontends/admin/src/lib/components/ServiceHealthCard.svelte:27-39` uses a neutral border for every service
card.
110 +- UI / Behavior Evidence:
111 + - Service health, config state, and scope severity do not have a dedicated Admin semantic color contract.
112 +- Gap Description:
113 + - Admin semantics are implemented ad hoc on top of shared generic colors rather than through the required exp
licit token system.
114 +- Severity: MEDIUM
115 +- Root Cause: missing enforcement of shared patterns
116 +- Recommended Fix:
117 + - Add Admin semantic tokens to `packages/ui/src/lib/styles/tokens.css`.
118 + - Refactor `StatusBadge.svelte` and `frontends/admin/src/lib/components/ServiceHealthCard.svelte` to consume
those tokens instead of hard-coded mappings.
119 +
120 +### Finding 7
121 +- Domain: Admin
122 +- Principle: "Typography rules"
123 +- Status: NON-COMPLIANT
124 +- Code Evidence:
125 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:147-153` and `PromptEditor.svelte:250-259` use plai
n `<textarea>` controls, not syntax-highlighting editors.
126 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte:114-120` renders `organization_id` i
n monospace, but slug is not monospace.
127 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:126-139` uses monospace for logs, but the componen
t does not format timestamps or structure lines itself.
128 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:155-160` renders error text as plain `<p>` content,
not monospace technical output.
129 +- UI / Behavior Evidence:
130 + - Some technical surfaces use monospace, but the most important code-like editors are still plain textareas a
nd tenant identifiers are not consistently typographically differentiated.
131 +- Gap Description:
132 + - The typography contract is only partially followed and breaks on the most operator-critical editing surface
s.
133 +- Severity: HIGH
134 +- Root Cause: placeholder / incomplete implementation
135 +- Recommended Fix:
136 + - Replace Admin JSON/Jinja textareas with a shared code editor component in `@netz/ui`.
137 + - Update tenant identity displays in `frontends/admin/src/lib/components/TenantCard.svelte` and `.../[orgId=o
         rgId]/+page.svelte` so both slug and org_id are always monospace.
138 + - Add a styled monospace error panel component for operator-facing errors.
139 +
140 +### Finding 8
141 +- Domain: Admin
142 +- Principle: "Interaction rules"
143 +- Status: NON-COMPLIANT
144 +- Code Evidence:
145 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:57-65` validates on every input, but not with the r
equired 500ms debounce.
146 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:18-29` does auto-refresh every 30 seconds.
147 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:103-119` requires a manual "Connect" click before
logs stream.
148 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:63-99` uses a raw unsortable table for workers.
149 + - `frontends/admin/src/lib/components/TenantCard.svelte:21-36` uses cards instead of a sortable/filterable ta
ble for tenants.
150 +- UI / Behavior Evidence:
151 + - One rule is met (health auto-refresh), but log streaming, table affordances, and config validation timing d
iverge from the standard.
152 +- Gap Description:
153 + - Shared interaction patterns exist in `@netz/ui`, but Admin pages are not consistently using them.
154 +- Severity: HIGH
155 +- Root Cause: missing enforcement of shared patterns
156 +- Recommended Fix:
157 + - Debounce config validation in `frontends/admin/src/lib/components/ConfigEditor.svelte`.
158 + - Auto-connect `WorkerLogFeed.svelte` on mount.
159 + - Replace Admin bespoke tables/cards with `packages/ui/src/lib/components/DataTable.svelte` where the spec re
quires sortable/filterable tables.
160 +
161 +### Finding 9
162 +- Domain: Admin
163 +- Principle: "Theme"
164 +- Status: PARTIALLY COMPLIANT
165 +- Code Evidence:
166 + - `frontends/admin/src/app.html:2-14` defaults the document to `data-theme="light"` and only switches if pers
isted preference is `dark`.
167 + - `frontends/admin/src/hooks.server.ts:32` uses `createThemeHook({ defaultTheme: "light" })`.
168 + - No Admin route or shared Admin layout exposes a theme preference control.
169 +- UI / Behavior Evidence:
170 + - Light is the effective default, which matches the spec, but there is no visible Admin user-preference contr
ol for switching themes.
171 +- Gap Description:
172 + - The default is correct, but the "dark theme as a user preference" part is incomplete at the UX layer.
173 +- Severity: LOW
174 +- Root Cause: placeholder / incomplete implementation
175 +- Recommended Fix:
176 + - Add a theme toggle to `packages/ui/src/lib/layouts/TopNav.svelte` or an Admin trailing control passed from
`frontends/admin/src/routes/+layout.svelte`.
177 +
178 +## 3. View Specifications
179 +
180 +### Finding 10
181 +- Domain: Admin
182 +- Principle: "This is the default landing page for the admin panel."
183 +- Status: COMPLIANT
184 +- Code Evidence:
185 + - `frontends/admin/src/routes/(admin)/+page.server.ts:4-5` redirects to `/health`.
186 + - `frontends/admin/src/routes/+layout.svelte:16-21` makes Health the first primary nav item.
187 +- UI / Behavior Evidence:
188 + - An operator entering the Admin app is taken to the health monitor first.
189 +- Gap Description:
190 + - No material gap on default landing behavior.
191 +- Severity: LOW
192 +- Root Cause: other (none)
193 +- Recommended Fix:
194 + - Keep the server redirect in `frontends/admin/src/routes/(admin)/+page.server.ts` as the source of truth and
remove redundant client redirect logic from `frontends/admin/src/routes/(admin)/+page.svelte`.
195 +
196 +### Finding 11
197 +- Domain: Admin
198 +- Principle: "Services Grid"
199 +- Status: NON-COMPLIANT
200 +- Code Evidence:
201 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:36-45` renders a responsive grid, but at `lg` it is
4 columns, not the specified 3-column grid.
202 + - `frontends/admin/src/lib/components/ServiceHealthCard.svelte:27-39` shows name, status, latency, and error
only; there is no last-checked time or drill-in link.
203 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:18-29` refreshes only services and pipeline data, n
ot worker data.
204 +- UI / Behavior Evidence:
205 + - The services area looks like a generic card grid rather than the specified monitoring grid with operational
timestamps and service drilldown.
206 +- Gap Description:
207 + - The section exists, but not with the specified density, timestamps, or navigation behavior.
208 +- Severity: HIGH
209 +- Root Cause: placeholder / incomplete implementation
210 +- Recommended Fix:
211 + - Update `frontends/admin/src/routes/(admin)/health/+page.svelte` to use a 3-column desktop grid and include
last-checked metadata from the backend.
212 + - Update `frontends/admin/src/lib/components/ServiceHealthCard.svelte` to render clickable cards with history
drilldown affordances.
213 +
214 +### Finding 12
215 +- Domain: Admin
216 +- Principle: "Workers Status"
217 +- Status: NON-COMPLIANT
218 +- Code Evidence:
219 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:63-99` renders columns for Worker, Status, Last Run
, Duration, Errors, which does not match the spec's heartbeat/queue depth/processed view.
220 + - There is no stale-heartbeat calculation in `frontends/admin/src/routes/(admin)/health/+page.svelte` or `+pa
         ge.server.ts`.
221 + - Rows are static `<tr>` elements with no click/filter behavior.
222 +- UI / Behavior Evidence:
223 + - Operators cannot see heartbeat freshness, queue depth, processed counts, or click into a worker-scoped log
view.
224 +- Gap Description:
225 + - The workers area is a generic job-results table, not an operational worker monitor.
226 +- Severity: HIGH
227 +- Root Cause: placeholder / incomplete implementation
228 +- Recommended Fix:
229 + - Extend the worker payload in `frontends/admin/src/routes/(admin)/health/+page.server.ts`.
230 + - Replace the current table in `frontends/admin/src/routes/(admin)/health/+page.svelte` with a sortable `Data
         Table` that includes heartbeat freshness, queue depth, processed count, and row click → log filter behavior.
231 +
232 +### Finding 13
233 +- Domain: Admin
234 +- Principle: "Worker Log Feed (real-time SSE)"
235 +- Status: PARTIALLY COMPLIANT
236 +- Code Evidence:
237 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:37-68` uses authenticated fetch-stream SSE reading
.
238 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:103-119` requires a manual "Connect" action.
239 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:131-139` renders full lines without truncation.
240 + - There are no worker/level/time-range filters and no line-level severity styling.
241 +- UI / Behavior Evidence:
242 + - The feed is live after connect and shows full lines, but it is not live by default and lacks the filtering/
styling expected of an operator console.
243 +- Gap Description:
244 + - The transport is correct; the UX around connection state, filtering, and severity encoding is incomplete.
245 +- Severity: HIGH
246 +- Root Cause: architectural inconsistency
247 +- Recommended Fix:
248 + - Auto-connect on mount in `frontends/admin/src/lib/components/WorkerLogFeed.svelte`.
249 + - Add worker, level, and time-range filters plus line styling for WARN/ERROR.
250 + - Migrate the component onto `createSSEStream` in `packages/ui/src/lib/utils/sse-client.svelte.ts` so Admin l
og streaming follows the shared SSE pattern.
251 +
252 +### Finding 14
253 +- Domain: Admin
254 +- Principle: "Tenant List"
255 +- Status: NON-COMPLIANT
256 +- Code Evidence:
257 + - `frontends/admin/src/routes/(admin)/tenants/+page.svelte:64-69` renders a grid of cards, not a table.
258 + - `frontends/admin/src/lib/components/TenantCard.svelte:25-35` omits `org_id`, plan badge, status, last-activ
e, and copy-to-clipboard behavior.
259 + - `frontends/admin/src/lib/components/TenantCard.svelte:27-30` uses vertical badges, not plan-tier badges.
260 +- UI / Behavior Evidence:
261 + - The tenant list does not provide the operator-dense table required for cross-tenant work.
262 +- Gap Description:
263 + - Critical tenant-identification and operational comparison fields are missing from the primary list.
264 +- Severity: HIGH
265 +- Root Cause: placeholder / incomplete implementation
266 +- Recommended Fix:
267 + - Replace the card grid in `frontends/admin/src/routes/(admin)/tenants/+page.svelte` with `DataTable`.
268 + - Expand the data model rendered by `frontends/admin/src/lib/components/TenantCard.svelte` or remove the card
component in favor of a table row implementation.
269 +
270 +### Finding 15
271 +- Domain: Admin
272 +- Principle: "Create Tenant Dialog"
273 +- Status: PARTIALLY COMPLIANT
274 +- Code Evidence:
275 + - `frontends/admin/src/routes/(admin)/tenants/+page.svelte:76-131` uses a dialog for tenant creation.
276 + - `frontends/admin/src/routes/(admin)/tenants/+page.svelte:18-23` validates slug format only; it does not aut
o-generate from name or check uniqueness.
277 + - `frontends/admin/src/routes/(admin)/tenants/+page.svelte:48-49` navigates to the new tenant detail page on
success.
278 +- UI / Behavior Evidence:
279 + - The dialog pattern and success navigation are correct, but the form stops short of the required real-time s
lug generation and uniqueness checks.
280 +- Gap Description:
281 + - The happy path exists, but the operator assistance and validation depth are incomplete.
282 +- Severity: MEDIUM
283 +- Root Cause: placeholder / incomplete implementation
284 +- Recommended Fix:
285 + - Add slug auto-generation from `name` and a uniqueness check in `frontends/admin/src/routes/(admin)/tenants/
         +page.svelte`.
286 + - Surface uniqueness failures inline before submit.
287 +
288 +### Finding 16
289 +- Domain: Admin
290 +- Principle: "Tenant Detail (`routes/tenants/[orgId]/+page.svelte`)"
291 +- Status: NON-COMPLIANT
292 +- Code Evidence:
293 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte:60-67` shows only tenant name in the
header.
294 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte:110-131` pushes slug, org_id, plan,
and status into a lower details card instead of the header.
295 + - There is no read-only `clerk_org_id` or `created_at` display in the current component.
296 +- UI / Behavior Evidence:
297 + - The page does not give the operator an always-visible tenant identity block at the top.
298 +- Gap Description:
299 + - Tenant identity and immutable metadata are not surfaced in the page frame the way the spec requires.
300 +- Severity: HIGH
301 +- Root Cause: placeholder / incomplete implementation
302 +- Recommended Fix:
303 + - Rework the header in `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte` to always show
name, slug, org_id, plan, status, clerk org id, and created_at.
304 +
305 +### Finding 17
306 +- Domain: Admin
307 +- Principle: "Tabs: [Overview] [Configuration] [Branding] [Seed & Setup]"
308 +- Status: NON-COMPLIANT
309 +- Code Evidence:
310 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+layout.svelte:18-28` defines sidebar items `Over
         view`, `Branding`, `Config`, and `Prompts`.
311 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/config/+page.svelte:5-8` is a placeholder.
312 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/prompts/+page.svelte:5-8` is a placeholder.
313 + - There is no dedicated "Seed & Setup" route or tab; the seed action is embedded in the overview page (`+page
         .svelte:139-154`).
314 +- UI / Behavior Evidence:
315 + - The tenant detail navigation is materially different from the spec and two of the routes are placeholders.
316 +- Gap Description:
317 + - Tenant-level task organization is incomplete and structurally inconsistent with the design guide.
318 +- Severity: HIGH
319 +- Root Cause: placeholder / incomplete implementation
320 +- Recommended Fix:
321 + - Replace the current context-nav items in `.../[orgId=orgId]/+layout.svelte` with the specified four-tab mod
el.
322 + - Implement real tenant-scoped config and setup pages in `.../config/+page.svelte` and a new `.../setup/+page
         .svelte`.
323 +
324 +### Finding 18
325 +- Domain: Admin
326 +- Principle: "Branding"
327 +- Status: PARTIALLY COMPLIANT
328 +- Code Evidence:
329 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:15-20` only allows PNG, JPE
G, and ICO MIME types.
330 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:34-59` validates magic byte
s client-side.
331 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:124-130` renders an immedia
te `<img>` preview.
332 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:154-161` uses a generic del
ete confirm dialog message.
333 + - `packages/ui/src/lib/utils/api-client.ts:238-247` uploads multipart data without the required `X-Netz-Reque
         st: 1` header.
334 +- UI / Behavior Evidence:
335 + - Upload restrictions and preview are present, but delete scope and CSRF header behavior do not match the spe
c.
336 +- Gap Description:
337 + - The branding flow is close, but the safety copy and request contract are incomplete.
338 +- Severity: MEDIUM
339 +- Root Cause: missing enforcement of shared patterns
340 +- Recommended Fix:
341 + - Update `packages/ui/src/lib/utils/api-client.ts` to support extra headers on `upload()`.
342 + - Pass `X-Netz-Request: 1` from `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svel
         te`.
343 + - Update the confirm copy to include asset type and tenant name.
344 +
345 +### Finding 19
346 +- Domain: Admin
347 +- Principle: "Seed & Setup"
348 +- Status: NON-COMPLIANT
349 +- Code Evidence:
350 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte:139-154` exposes the seed action as
a generic "Actions" card, not a dedicated setup surface.
351 + - The confirm copy at `:151-152` says existing overrides will not be affected, which directly conflicts with
the spec's warning that existing overrides will be replaced.
352 + - The confirm message omits explicit scope text with tenant name and org_id.
353 +- UI / Behavior Evidence:
354 + - The seeding flow does not give the operator the structured setup context, scope block, or warning language
required by the guide.
355 +- Gap Description:
356 + - This is a consequential setup action presented with insufficient context and incorrect warning copy.
357 +- Severity: HIGH
358 +- Root Cause: placeholder / incomplete implementation
359 +- Recommended Fix:
360 + - Move the seed workflow into a dedicated tenant setup page.
361 + - Update `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte` or the new setup page to sho
w scope, warning, and confirm text exactly as specified.
362 +
363 +### Finding 20
364 +- Domain: Admin
365 +- Principle: "Config List (per vertical)"
366 +- Status: PARTIALLY COMPLIANT
367 +- Code Evidence:
368 + - `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte:40-64` surfaces invalid configs
prominently.
369 + - `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte:67-97` renders a config list, b
ut only shows key, description, and override/default badge.
370 + - There is no last-modified metadata or per-key override count in the current list UI.
371 +- UI / Behavior Evidence:
372 + - Invalid configs are noticeable, but the operator cannot scan the list for ownership, freshness, or override
counts the way the spec expects.
373 +- Gap Description:
374 + - The section is directionally correct but incomplete as an operational list view.
375 +- Severity: MEDIUM
376 +- Root Cause: placeholder / incomplete implementation
377 +- Recommended Fix:
378 + - Extend the loader in `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.server.ts` to ret
urn last-modified data and override counts.
379 + - Update the list rendering in `+page.svelte` to display those fields.
380 +
381 +### Finding 21
382 +- Domain: Admin
383 +- Principle: "Config Editor (`ConfigEditor.svelte`)"
384 +- Status: NON-COMPLIANT
385 +- Code Evidence:
386 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:147-153` uses a plain textarea with no syntax highl
ighting.
387 + - `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte:104-123` renders the diff viewe
r behind a separate toggle instead of the required always-visible two-panel layout.
388 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:169-171` allows global-default updates, but the con
firmation copy at `197-203` does not include exact tenant count or the required "affects ALL tenants" wording.
389 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:155-160` surfaces result text inline instead of toa
st feedback.
390 +- UI / Behavior Evidence:
391 + - The editor works as a basic JSON form, but it is not the spec-grade operator editor described in the UX gui
de.
392 +- Gap Description:
393 + - Key spec requirements around editor ergonomics, diff visibility, scope clarity, and feedback are missing.
394 +- Severity: HIGH
395 +- Root Cause: placeholder / incomplete implementation
396 +- Recommended Fix:
397 + - Replace the editor with a syntax-highlighting shared code editor.
398 + - Make the diff permanently visible beside the editor in `frontends/admin/src/routes/(admin)/config/[vertical
         =vertical]/+page.svelte`.
399 + - Use shared toast feedback after save/delete/default update.
400 +
401 +### Finding 22
402 +- Domain: Admin
403 +- Principle: "Prompt List"
404 +- Status: PARTIALLY COMPLIANT
405 +- Code Evidence:
406 + - `frontends/admin/src/routes/(admin)/prompts/[vertical=vertical]/+page.svelte:42-71` allows row-click select
ion and shows version/source level.
407 + - The list does not render last-modified actor/date or last preview date.
408 +- UI / Behavior Evidence:
409 + - Operators can open prompt editors from the list, but the list is weaker than the specified version/audit in
dex.
410 +- Gap Description:
411 + - Prompt inventory lacks operational metadata that should support quick triage.
412 +- Severity: LOW
413 +- Root Cause: placeholder / incomplete implementation
414 +- Recommended Fix:
415 + - Extend `frontends/admin/src/routes/(admin)/prompts/[vertical=vertical]/+page.server.ts` to return modifier
and preview metadata, then render it in the list.
416 +
417 +### Finding 23
418 +- Domain: Admin
419 +- Principle: "Prompt Editor (`PromptEditor.svelte`)"
420 +- Status: PARTIALLY COMPLIANT
421 +- Code Evidence:
422 + - `frontends/admin/src/lib/components/PromptEditor.svelte:92-99` debounces preview/validation by 500ms.
423 + - `frontends/admin/src/lib/components/PromptEditor.svelte:250-259` uses a plain textarea instead of a code ed
itor.
424 + - `frontends/admin/src/lib/components/PromptEditor.svelte:290-299` provides save and revert/remove actions, b
ut there are no explicit Validate or Run Preview buttons despite the spec calling for them.
425 + - `frontends/admin/src/lib/components/PromptEditor.svelte:101-120` creates new versions on save via backend r
esponse versioning.
426 +- UI / Behavior Evidence:
427 + - The prompt editor is in the main content area and supports preview/save/versioning, but not in the exact co
ntrol pattern described by the spec.
428 +- Gap Description:
429 + - The editor approximates the intended workflow but still lacks the specified explicit validation/preview con
trols and code-editor ergonomics.
430 +- Severity: MEDIUM
431 +- Root Cause: placeholder / incomplete implementation
432 +- Recommended Fix:
433 + - Add explicit Validate and Run Preview buttons to `frontends/admin/src/lib/components/PromptEditor.svelte`.
434 + - Replace the textarea with a shared syntax-highlighting template editor in `@netz/ui`.
435 +
436 +### Finding 24
437 +- Domain: Admin
438 +- Principle: "Version History Panel (lazy-loaded on \"History\" click)"
439 +- Status: PARTIALLY COMPLIANT
440 +- Code Evidence:
441 + - `frontends/admin/src/lib/components/PromptEditor.svelte:148-153` lazy-loads history on first open.
442 + - `frontends/admin/src/lib/components/PromptEditor.svelte:223-237` renders versions and per-version revert co
ntrols.
443 + - The panel does not show modifier identity or change summary, only version number and `created_at`.
444 +- UI / Behavior Evidence:
445 + - Lazy loading exists, but the history panel is too thin for the auditability standard in the spec.
446 +- Gap Description:
447 + - Operators can see versions, but not who changed them or why.
448 +- Severity: LOW
449 +- Root Cause: placeholder / incomplete implementation
450 +- Recommended Fix:
451 + - Extend the versions API contract and update `PromptEditor.svelte` to show modifier and change summary per r
ow.
452 +
453 +## 4. Component Anti-Patterns
454 +
455 +### Finding 25
456 +- Domain: Admin
457 +- Principle: "Never hide system errors behind friendly messages."
458 +- Status: NON-COMPLIANT
459 +- Code Evidence:
460 + - `frontends/admin/src/routes/(admin)/health/+page.server.ts:24-37` suppresses errors.
461 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:50-52` and `PromptEditor.svelte:75-88` reduce failu
res to generic text.
462 +- UI / Behavior Evidence:
463 + - Operator-facing failures are frequently hidden behind empty or generic messages.
464 +- Gap Description:
465 + - This anti-pattern is present in multiple Admin workflows.
466 +- Severity: MEDIUM
467 +- Root Cause: other (silent/generic error handling)
468 +- Recommended Fix:
469 + - Replace generic fallback strings with raw backend detail, request target, and status code in the cited comp
onents.
470 +
471 +### Finding 26
472 +- Domain: Admin
473 +- Principle: "Never save config without validation."
474 +- Status: COMPLIANT
475 +- Code Evidence:
476 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:130` derives `jsonValid`.
477 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:178-180` disables save while invalid.
478 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:67-68` hard-stops save if `jsonError` exists.
479 +- UI / Behavior Evidence:
480 + - Invalid JSON cannot be saved through the config override flow.
481 +- Gap Description:
482 + - The validation mechanism is weaker than specified, but the anti-pattern itself is currently blocked.
483 +- Severity: LOW
484 +- Root Cause: other (none)
485 +- Recommended Fix:
486 + - Keep the save guard and strengthen it with a debounced syntax-highlighting editor.
487 +
488 +### Finding 27
489 +- Domain: Admin
490 +- Principle: "Never show a config action without specifying scope."
491 +- Status: NON-COMPLIANT
492 +- Code Evidence:
493 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:165-171` labels actions generically as "Revert to D
efault" and "Update Default".
494 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:188-203` confirm messages omit tenant identity and
the required `Affects: ALL TENANTS` wording.
495 +- UI / Behavior Evidence:
496 + - Operators see config actions without precise scope language.
497 +- Gap Description:
498 + - Scope is implicit in a workflow where scope must be explicit.
499 +- Severity: HIGH
500 +- Root Cause: missing enforcement of shared patterns
501 +- Recommended Fix:
502 + - Include `{configType}`, tenant name, slug, org_id, and `Affects: ALL TENANTS` directly in button labels and
dialog copy inside `ConfigEditor.svelte`.
503 +
504 +### Finding 28
505 +- Domain: Admin
506 +- Principle: "Never auto-refresh tenant data in a form the operator is editing."
507 +- Status: COMPLIANT
508 +- Code Evidence:
509 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte` contains no timer-based refresh whi
le editing.
510 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte` also contains no automatic
refresh loop.
511 +- UI / Behavior Evidence:
512 + - Tenant edit flows are not being silently refreshed out from under the operator.
513 +- Gap Description:
514 + - No direct violation found in the current Admin tenant forms.
515 +- Severity: LOW
516 +- Root Cause: other (none)
517 +- Recommended Fix:
518 + - Preserve this behavior if future live refresh is added by gating it behind an unsaved-changes banner.
519 +
520 +### Finding 29
521 +- Domain: Admin
522 +- Principle: "Never show worker logs truncated."
523 +- Status: COMPLIANT
524 +- Code Evidence:
525 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:129-132` renders each full line in a wrapping `div
         ` inside a scroll container, with no truncation classes.
526 +- UI / Behavior Evidence:
527 + - Log lines are displayed in full-width wrapped text rather than ellipsized snippets.
528 +- Gap Description:
529 + - No truncation violation found.
530 +- Severity: LOW
531 +- Root Cause: other (none)
532 +- Recommended Fix:
533 + - Keep the current wrapping behavior when filters and severity styling are added.
534 +
535 +### Finding 30
536 +- Domain: Admin
537 +- Principle: "Never omit org_id from any tenant-scoped view."
538 +- Status: NON-COMPLIANT
539 +- Code Evidence:
540 + - `frontends/admin/src/lib/components/TenantCard.svelte:25-35` omits `organization_id`.
541 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:100-105` shows only a gener
ic "Branding" page title with no tenant identity block.
542 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte:60-67` header omits org_id.
543 +- UI / Behavior Evidence:
544 + - Multiple tenant-scoped pages force the operator to infer or remember tenant identity.
545 +- Gap Description:
546 + - This anti-pattern is still present on primary tenant surfaces.
547 +- Severity: HIGH
548 +- Root Cause: placeholder / incomplete implementation
549 +- Recommended Fix:
550 + - Add a shared tenant context header component in `@netz/ui` and render it on all tenant-scoped Admin pages.
551 +
552 +### Finding 31
553 +- Domain: Admin
554 +- Principle: "Never allow SVG uploads for branding assets."
555 +- Status: COMPLIANT
556 +- Code Evidence:
557 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:15-20` restricts uploads to
PNG, JPEG, and ICO.
558 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte:50-58` rejects mismatched f
ile contents.
559 +- UI / Behavior Evidence:
560 + - SVG cannot be selected through the accept list or uploaded through the MIME/magic-byte validation path.
561 +- Gap Description:
562 + - No direct SVG-acceptance violation found.
563 +- Severity: LOW
564 +- Root Cause: other (none)
565 +- Recommended Fix:
566 + - Keep both MIME and magic-byte validation when the upload flow is expanded.
567 +
568 +### Finding 32
569 +- Domain: Admin
570 +- Principle: "Never show health status without a last-checked timestamp."
571 +- Status: NON-COMPLIANT
572 +- Code Evidence:
573 + - `frontends/admin/src/lib/components/ServiceHealthCard.svelte:27-39` shows status, latency, and error only.
574 + - `frontends/admin/src/routes/(admin)/health/+page.svelte:33-45` has no page-level "last checked" timestamp.
575 +- UI / Behavior Evidence:
576 + - Operators see health snapshots without freshness metadata.
577 +- Gap Description:
578 + - Health data cannot be judged for staleness from the UI alone.
579 +- Severity: HIGH
580 +- Root Cause: placeholder / incomplete implementation
581 +- Recommended Fix:
582 + - Return `checked_at` values from `frontends/admin/src/routes/(admin)/health/+page.server.ts` and render them
both globally and per service card.
583 +
584 +### Finding 33
585 +- Domain: Admin
586 +- Principle: "Never make the prompt editor a modal or side panel."
587 +- Status: COMPLIANT
588 +- Code Evidence:
589 + - `frontends/admin/src/routes/(admin)/prompts/[vertical=vertical]/+page.svelte:81-88` renders `PromptEditor`
directly in the page flow.
590 + - `frontends/admin/src/lib/components/PromptEditor.svelte:243-288` occupies the main content area with a full
split-pane layout.
591 +- UI / Behavior Evidence:
592 + - Prompt editing is a full-page activity, not a cramped overlay.
593 +- Gap Description:
594 + - No modal/side-panel violation found.
595 +- Severity: LOW
596 +- Root Cause: other (none)
597 +- Recommended Fix:
598 + - Keep prompt editing as a full-page surface.
599 +
600 +### Finding 34
601 +- Domain: Admin
602 +- Principle: "Never default the config editor to read-only."
603 +- Status: PARTIALLY COMPLIANT
604 +- Code Evidence:
605 + - `frontends/admin/src/lib/components/ConfigEditor.svelte:147-180` opens directly into an editable form, not
a display-only view.
606 + - `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte:106` does not pass `orgId`, so
the editor defaults to global/default editing and the tenant override path is unavailable here.
607 + - `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/config/+page.svelte:5-8` is a placeholder instead
of a tenant-scoped editable config surface.
608 +- UI / Behavior Evidence:
609 + - Operators do get an immediate editor, but not the tenant-scoped editing path the Admin IA implies.
610 +- Gap Description:
611 + - The non-read-only rule is met for global config, but tenant-scoped config editing is still missing.
612 +- Severity: MEDIUM
613 +- Root Cause: placeholder / incomplete implementation
614 +- Recommended Fix:
615 + - Implement tenant-scoped config editing in `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/config/
         +page.svelte` using `ConfigEditor` with a real `orgId`.
616 +
617 +## 5. Alerting, Accessibility, and Localization
618 +
619 +### Finding 35
620 +- Domain: Admin
621 +- Principle: "Alert fatigue discipline — amber that is always amber becomes gray"
622 +- Status: NON-COMPLIANT
623 +- Code Evidence:
624 + - `frontends/admin/src/lib/components/ServiceHealthCard.svelte:18-24` maps only simple status-to-badge colors
.
625 + - `frontends/admin/src/routes/(admin)/health/+page.svelte` contains no acknowledgement UI, escalation banner,
grouping rule, or stale-duration escalation logic.
626 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte` contains no alert-acknowledgement state at all.
627 +- UI / Behavior Evidence:
628 + - There is no suppression, acknowledgement, grouping, or time-bounded escalation model in the health UI.
629 +- Gap Description:
630 + - The health monitor currently lacks the policy layer required to keep operator trust in amber/red signals.
631 +- Severity: HIGH
632 +- Root Cause: placeholder / incomplete implementation
633 +- Recommended Fix:
634 + - Add acknowledgement state, grouped degraded-alert banners, and stale-duration escalation logic to `frontend
         s/admin/src/routes/(admin)/health/+page.svelte` and `ServiceHealthCard.svelte`.
635 +
636 +### Finding 36
637 +- Domain: Admin
638 +- Principle: "Accessibility & Audit Requirements"
639 +- Status: PARTIALLY COMPLIANT
640 +- Code Evidence:
641 + - `packages/ui/src/lib/components/Dialog.svelte:26-58` uses Bits UI dialog primitives and exposes close contr
ols, which supports focus management and Escape behavior.
642 + - `packages/ui/src/lib/components/Toast.svelte:55-63` exposes `role="alert"`.
643 + - `frontends/admin/src/routes/(admin)/health/+page.svelte` does not add `aria-live="polite"` to health status
indicators.
644 + - `frontends/admin/src/lib/components/ConfigEditor.svelte` and `PromptEditor.svelte` do not announce syntax e
rrors to screen readers or provide dedicated accessible code-editor semantics.
645 + - No Admin page renders visible audit-log history for config saves or destructive actions.
646 +- UI / Behavior Evidence:
647 + - Modal foundations are decent, but health accessibility and operator-audit visibility are incomplete.
648 +- Gap Description:
649 + - Accessibility primitives exist in shared UI, but the Admin implementation does not fully apply the document
ed requirements.
650 +- Severity: HIGH
651 +- Root Cause: missing enforcement of shared patterns
652 +- Recommended Fix:
653 + - Add `aria-live="polite"` to health status regions in `frontends/admin/src/routes/(admin)/health/+page.svelt
         e`.
654 + - Replace plain textareas with accessible code editors and add screen-reader error announcements.
655 + - Add visible audit panels for config and destructive actions.
656 +
657 +### Finding 37
658 +- Domain: Admin
659 +- Principle: "Localization Notes"
660 +- Status: PARTIALLY COMPLIANT
661 +- Code Evidence:
662 + - `frontends/admin/src/app.html:2` sets `lang="en"`.
663 + - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:131-132` renders log lines verbatim.
664 + - `frontends/admin/src/routes/(admin)/health/+page.svelte`, `.../tenants/+page.svelte`, `.../config/[vertical
         =vertical]/+page.svelte`, and `.../prompts/[vertical=vertical]/+page.svelte` all hard-code user-facing English
strings.
665 + - A targeted search found no `paraglide`/i18n usage in `frontends/admin/src` or `packages/ui/src/lib`.
666 +- UI / Behavior Evidence:
667 + - Technical text is English and identifiers are shown raw, but there is no i18n keying for user-facing labels
.
668 +- Gap Description:
669 + - The Admin UI partially matches the localization note on English errors/raw identifiers, but misses the requ
ired paraglide-js key usage and does not enforce the date-format rules.
670 +- Severity: MEDIUM
671 +- Root Cause: placeholder / incomplete implementation
672 +- Recommended Fix:
673 + - Introduce paraglide-js keys for Admin labels in the page and component files above.
674 + - Centralize date formatting for Admin surfaces so UI timestamps use the specified format while logs remain v
erbatim.
