Premium Institutional System Design Doctrine — Definitive Version

1. Purpose

This design doctrine defines the visual, structural, and interaction principles for the Netz Analysis Engine as a full institutional operating system, not as a standalone frontend application.

The product spans multiple domains, including credit underwriting, portfolio monitoring, macro intelligence, wealth analysis, document ingestion, quantitative analytics, content generation, investor distribution, administrative oversight, and approval workflows. Its interface must therefore support not only presentation, but also decision-making, traceability, process confidence, and prolonged use under analytical pressure.

The goal of the design system is to create an environment that feels calm, rigorous, trustworthy, and operationally mature. It must support dense data, layered workflows, long-lived sessions, and role-sensitive actions without feeling visually noisy, generic, or improvised.

This is not a marketing surface. It is not a dashboard skin. It is a system interface for institutional work.

2. System Context

The Netz platform is architecturally composed of multiple SvelteKit frontends over a FastAPI backend, connected to AI pipelines, quant engines, vertical engines for Credit and Wealth, Redis-backed SSE and job orchestration, and a multi-layer data architecture spanning PostgreSQL, pgvector, TimescaleDB, Redis, local or cloud object storage, and several external data providers. Both the Credit and Wealth verticals expose broad tool surfaces with materially different workflows, including IC memo generation, document review, pipeline management, screening, macro committee processes, allocation workbenches, DD reports, reporting, investor views, and audit-linked approvals.

Because of this, design quality must be judged against the entire operating context:

The interface must help users understand where they are in a process, what is deterministic versus model-generated, what is draft versus approved, what belongs to monitoring versus action, what is evidence-backed versus synthetic, and which parts of the screen are operationally important versus merely informative.

A design system that only optimizes color, spacing, and typography at component level will not be sufficient. The visual language must encode system structure.

3. Core Principle

The primary design challenge is not “beautifying screens.” The real challenge is expressing institutional system hierarchy in a way that is pleasant, premium, and cognitively stable.

That means the design system must do five things simultaneously:

It must express product seriousness without becoming cold.
It must support data density without becoming claustrophobic.
It must support workflows without becoming mechanical.
It must support AI-generated outputs without making the interface feel unstable.
It must support two different verticals without fragmenting into two unrelated products.

This doctrine therefore treats design as system orchestration, not ornament.

4. What Was Weak Before

The prior styling foundation was technically competent but strategically incomplete.

It was too frontend-local in spirit. The visual language behaved like a generic enterprise UI baseline, appropriate for component consistency but not for a platform with deep backend orchestration, evidence pipelines, approval states, policy checks, and multi-step institutional workflows.

The main weaknesses were these:

The palette was too close to generic enterprise blue-gray systems, which made the product feel safe but undifferentiated.

Surface layers were too close together, reducing the visual separation needed for cards, grouped sections, review states, overlays, and operational zones.

Border hierarchy was underdeveloped, which flattened distinctions between inputs, panels, tables, review states, and navigation regions.

Typography was correct but generic, with insufficient emphasis on structured hierarchy for dense, document-heavy, analytical contexts.

Spacing was mathematically consistent but semantically weak, so layout rhythm did not reflect product meaning.

Depth relied too much on standard shadow logic and too little on layered structural hierarchy.

Motion existed as utility, not as process communication.

Most importantly, the system did not visibly express that the product is more than a frontend. It did not encode pipeline stages, evidence confidence, approval maturity, operational gravity, or cross-domain differences strongly enough.

5. Design Objective

The design system must now evolve from a component baseline into an institutional operating language.

The target state is a platform that feels:

Premium, but not luxurious.
Restrained, but not dull.
Dense, but not crowded.
Modern, but not trendy.
Authoritative, but not hostile.
Calm, but not lifeless.

The user should feel that the system is controlled, coherent, and serious. Visual quality should reinforce confidence in the product’s judgment, especially in domains where outputs affect investment decisions, risk interpretation, compliance review, and investor-facing deliverables.

6. Design Strategy

The visual strategy of the platform is surface-driven and workflow-aware.

Surfaces are the primary carriers of hierarchy.
Typography is the primary carrier of authority and reading rhythm.
Color is a supporting signal for interaction and meaning.
Motion is reserved for state communication and transition clarity.
Spacing is used to express structure, not simply separation.
Borders are used to define containment, active state, and procedural emphasis.

This hierarchy matters because the platform contains many different content types: tables, forms, dashboards, narratives, memo chapters, evidence panels, charts, upload flows, approvals, alerts, review queues, generated content, and live monitoring streams. A single visual strategy must organize them all without collapsing them into one aesthetic treatment.

7. System-Level Design Model

The product should be treated as composed of five visual layers.

The first layer is Structural Frame. This includes application shell, side navigation, top-level headers, page chrome, and sectional framing. It establishes where the user is in the operating system.

The second layer is Operational Workspace. This includes pages where users actively work: pipeline boards, allocation editors, review screens, report builders, macro workbenches, portfolio tools, and detail pages.

The third layer is Analytical Surface. This includes cards, tables, metrics, charts, detail panes, chapter views, evidence panels, and context drawers. This is where most reading and comparison happens.

The fourth layer is Process Layer. This includes statuses, approvals, generation states, SSE-fed progress, consequence dialogs, publish states, stage transitions, review assignments, and workflow bars. This is where design must make process maturity legible.

The fifth layer is Elevated Decision Layer. This includes modals, floating inspectors, drawers, dropdowns, command surfaces, and critical action confirmations. These must feel clearly above the rest of the system.

The old design system mainly addressed the third layer. The new one must address all five.

8. Visual Identity Direction

The visual identity should be read as executive analytical software.

Not consumer fintech.
Not startup SaaS.
Not legacy enterprise portal.
Not heavy Bloomberg nostalgia.
Not glassmorphism.
Not high-contrast hype UI.

The correct direction is a premium institutional interface with controlled density, low-noise layering, serious typography, disciplined accent use, and enough polish to feel expensive without ever becoming decorative.

The visual impression should be that the system was designed for intelligent scrutiny.

9. Color Doctrine

Color must be treated as a governance instrument, not a stylistic playground.

The base palette should remain in the family of deep navy, steel-blue neutrals, mineral grays, and softened warm highlights. This provides seriousness and continuity with the product’s domain, while avoiding the sterility of pure grayscale or the generic feel of default slate-based design systems.

The accent system must become more intentional. Accent should not merely mean “button color.” It should be used to indicate actionability, focus, subtle emphasis, hover, selected state, and guided attention. Accent-soft layers are especially important because the platform contains many high-density tables and interactive lists where hover and selected states must be felt without becoming loud.

Semantic colors must remain tightly controlled. Success, warning, danger, and info should be role-driven, not decorative. A warning badge and a workflow warning state should feel related but not over-saturated. Risk must feel serious without turning the interface into a field of red.

Across both Credit and Wealth, color should help distinguish meaning, not create brand spectacle.

10. Surface Doctrine

Surface hierarchy is the core of the new system.

Because the platform contains nested analytical contexts, the user must immediately perceive whether something is page background, grouped section, primary analytical panel, inset process block, or elevated decision surface.

The surface system should therefore be formalized as:

surface-base for page background and app canvas.
surface-1 for primary cards and standard containers.
surface-2 for grouped sections, headers, embedded zones, and context partitions.
surface-3 for elevated surfaces such as dropdowns, modals, floating trays, and overlays.
surface-inverse for structural shell elements and visually anchoring zones.

This layering is not cosmetic. It is what makes an IC memo page, a document review queue, a macro dashboard, and an allocation editor feel structurally intelligible rather than like arbitrary stacks of boxes.

11. Border Doctrine

Borders must become semantically meaningful.

The prior design used borders mostly as generic separators. In a product like this, borders need to express structural containment, interaction readiness, and process emphasis.

The border hierarchy should therefore be explicit:

border-subtle for layout containment and low-noise separation.
border-default for components requiring direct affordance.
border-strong for emphasis, active containers, and stateful prominence.
border-focus for user interaction states only.

Borders must support the system’s containment logic. They are particularly important for tables, forms, review panels, process modules, and sidebar structures, where insufficient border differentiation quickly causes visual flattening.

12. Typography Doctrine

Typography in this system cannot be treated as generic UI text styling. It is part of the product’s institutional credibility.

The platform includes narrative outputs, legal and financial documentation, memo chapters, macro commentary, portfolio diagnostics, evidence excerpts, metadata panels, table-heavy dashboards, and approval interfaces. Typography must therefore support both scanning and sustained reading.

The system should remain sans-based and modern, but hierarchy needs to be sharper and more editorial.

Display styles should be rare and reserved for major entry points.
Heading styles should convey authority without theatricality.
Subheadings should support sectional navigation.
Body should remain highly readable under density.
Labels should feel precise and compact.
Captions should be optimized for metadata and secondary context.

Tracking, weight, and line-height tuning matter here more than novelty. The perceived quality of the product will depend heavily on how well the text holds composure under dense layouts.

13. Spacing Doctrine

Spacing must become semantic.

A purely numeric spacing scale is not enough for a multi-domain institutional platform. Different contexts require different rhythm logic: dashboards, report readers, upload workflows, review queues, tables, and settings surfaces cannot all derive their compositional quality from raw 4px multiplication alone.

The system should therefore expose semantic spacing roles such as:

section spacing for page-level flow.
block spacing for major content blocks.
card padding for containers.
form gap for control groupings.
inline spacing for compact metadata, filters, and row utilities.

This is especially important because the platform spans both Credit and Wealth, and because many pages contain mixed compositions of charting, forms, tables, and long-form content. Semantic spacing is what keeps these mixtures from feeling improvised.

14. Depth and Elevation Doctrine

Depth should come from the interaction of surface, border, and shadow, not from shadow alone.

The old depth language was too close to default shadow ladders. For an institutional system, this makes the product feel generic.

The new elevation system must be restrained and structural. A card should feel lifted because its surface is distinct, its border is disciplined, and its shadow is ambient. A modal should feel elevated because it is spatially separate, tonally clear, and contextually dominant. A dropdown should feel precise, not floaty.

Elevation levels should be defined for cards, floating containers, and overlays. These should be reused consistently across the product so that the user can infer importance from depth cues.

15. Motion Doctrine

Motion in this platform is not about delight. It is about confidence.

The system includes asynchronous generation, streaming content, uploads, classification pipelines, approval transitions, and live risk monitoring. Motion should therefore clarify state progression and responsiveness.

Hover, pressed, focus, and expansion states should be subtle and fast.
Panel entrances should feel controlled.
Loading and generation states should reinforce process legitimacy.
SSE-fed changes should never feel jumpy or unstable.

Motion must always reduce ambiguity. If an animation only adds personality but not clarity, it should not exist.

16. Workflow Visibility Doctrine

Because the product is deeply process-driven, the design system must explicitly support workflow maturity.

A user should be able to distinguish at a glance:

draft from approved,
generated from reviewed,
pending from blocked,
published from internal,
monitoring from action-required,
analysis from evidence,
temporary UI state from committed system state.

This is particularly important given the workflows described in the system map: DD report approvals, content status pipelines, IC memo generation, deal stage transitions, document reviews, report pack publication, macro committee reviews, and investor distribution states. These are not edge cases; they are central product behaviors.

The design system must therefore include a process-state language that is calm, clear, and consistent across domains.

17. AI and Determinism Visibility

The product mixes deterministic computation, database-backed state, document-derived evidence, and LLM-generated synthesis. The interface must not visually blur these categories.

Where relevant, design should help users understand whether a surface is:

raw evidence,
deterministic metric,
model inference,
generated narrative,
approval-required content,
or published artifact.

This does not require loud warning labels everywhere. It requires disciplined use of badges, captions, metadata treatment, provenance presentation, evidence containers, and generation states.

A premium institutional interface should make intelligence feel auditable.

18. Cross-Vertical Consistency

Credit and Wealth should not look like separate products.

They do have different functional personalities. Credit is more document-heavy, covenant-aware, pipeline-driven, and memo-centric. Wealth is more monitor-driven, analytics-heavy, screening-oriented, and portfolio-centric. But both must clearly belong to the same operating system.

This means the shared design language must persist across both verticals:

same surface hierarchy,
same typography logic,
same border semantics,
same spacing rhythm,
same depth model,
same action hierarchy,
same process state language.

Vertical-specific nuance should appear in page composition and domain modules, not in divergent visual foundations.

19. Token System Specification

The token system must be treated as system infrastructure.

It should define not only values but roles.

The definitive token categories should include surface tokens, border tokens, accent tokens, semantic status tokens, typography roles, semantic spacing roles, elevation tokens, motion durations, and state tokens for focus, selection, hover, and disabled states.

Legacy token names may be preserved for safe migration, but the internal conceptual model must be upgraded so that every token has an operational meaning.

The system should prioritize evolvability. New tokens should be introduced only when they correspond to durable roles, not local screen fixes.

20. Component Doctrine

Base components must now be understood as carriers of system logic.

Cards should express containment and internal hierarchy.
Buttons should reflect action class and decision gravity.
Inputs should feel precise, stable, and institutionally clean.
Tables should optimize for density and scanability.
Tabs should support navigation without visual overstatement.
Badges should convey state without becoming decorative pills.
Drawers and modals should feel meaningfully elevated.
Document views should support provenance and reading continuity.
Charts should feel analytical, not promotional.

A component library that is merely consistent is not enough. It must embody the product’s stance.

21. Page-Type Guidelines

The product contains multiple recurring page archetypes, and each should have explicit compositional logic.

Dashboard pages must prioritize summary and exception visibility.

Workbench pages must prioritize action locality, context continuity, and before-versus-after legibility.

Detail pages must balance metadata, narrative, and supporting evidence.

Review pages must surface status, responsibility, checklist logic, and decision controls without ambiguity.

Report-reading pages must optimize for long-form readability and chapter navigation.

Document pages must make provenance, classification, and lifecycle states visible without clutter.

Investor-facing pages must feel cleaner and calmer than internal operational pages, but still belong to the same system.

This layer of page doctrine is essential because the system map shows that the product spans all of these modes extensively.

22. Dark Mode Doctrine

Dark mode should not be treated as an inversion exercise.

Because the platform is dense and analytical, dark mode requires deliberate component-level adjustment. Elevated surfaces must remain distinct. Hover states must remain legible. Borders must not disappear into low-contrast mud. Charts and badges must remain restrained. Long-form reading views must avoid glowing fatigue.

Dark theme quality will materially affect perceived product maturity, especially in power-user contexts.

23. What This Means for Refactoring

The design refactor must be staged accordingly.

Stage one is foundational styling, which improves tokens, typography, spacing, surfaces, borders, depth, and motion.

Stage two is shared component alignment, ensuring cards, buttons, tabs, inputs, tables, badges, drawers, and page chrome correctly adopt the new logic.

Stage three is workflow surface alignment, especially for approvals, generation states, review queues, consequence dialogs, and investor publication flows.

Stage four is page archetype standardization across Credit and Wealth.

Stage five is chart and visualization alignment so that quantitative and macro outputs feel native to the platform.

Only after these stages will the system feel genuinely premium at product level.

24. Non-Negotiable Rules

No arbitrary new colors outside the token system.
No local gray mixing to solve component contrast.
No one-off shadows.
No decorative gradients except under strict system guidance.
No spontaneous visual variants that do not map to action hierarchy.
No status language that differs between domains without reason.
No component styling that hides process maturity.
No page-level improvisation that overrides semantic spacing and surface logic.

These constraints are not aesthetic rigidity. They are what allow a complex institutional product to remain trustworthy.

25. Final Position

The Netz Analysis Engine is not “a frontend with some backend services behind it.” It is an institutional analysis platform whose visual layer must express the seriousness of its architecture.

The system map makes this explicit: the product contains ingestion pipelines, OCR, classification, embeddings, vector search, memo engines, quant analytics, macro intelligence, background workers, approval workflows, reporting, and investor surfaces. A design system that ignores this and operates only at superficial frontend level will always feel insufficient.

The correct design ambition is therefore not to make pages prettier in isolation. It is to create a visual operating language that gives coherence, confidence, and pleasure to a complex analytical machine.

That is the standard the system should now be built to.
