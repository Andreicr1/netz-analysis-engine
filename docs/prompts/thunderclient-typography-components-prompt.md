# Prompt: Thunder Client Typography & Component Tokens — Wealth OS

## Objetivo

Atualizar a tipografia e tokens de componentes do Wealth OS para corresponder
exatamente ao sistema de design do Thunder Client Docs.
A sidebar já foi implementada em sessão anterior. Este prompt foca apenas em:
- Escala tipográfica (headings, body, labels)
- Tokens CSS de tipografia e espaçamento
- PageHeader component
- Componentes de conteúdo: Badge, KBD, inline code, links

---

## Medições exatas (DevTools getComputedStyle, light mode)

### Headings — padrão Thunder Client
```
H1: 30.4px  / weight 600 / line-height 33.8px / letter-spacing -0.76px / margin-top 16px
H2: 27.2px  / weight 600 / line-height 32.6px / letter-spacing -0.68px / margin-top 40px
H3: 24px    / weight 600 / line-height 32px   / letter-spacing -0.60px / margin-top 32px

Padrão: letter-spacing = -0.025em em TODOS os headings (2.5% negativo)
Cor light: rgb(36, 70, 127) = #24467f (azul institucional — NÃO preto)
Cor dark:  rgb(240, 240, 240) = #f0f0f0
```

### Body text
```
Paragraph: 16px / weight 400 / line-height 28px (1.75) / margin-top 20px
Strong:    16px / weight 700 / line-height 28px
Link:      16px / weight 400 / color rgb(0,107,230) = #006be6 (primary-600)
```

### Small elements
```
Breadcrumb: 14px / weight 400 / line-height 20px / color #4a5565
TOC item:   14px / weight 400 / line-height 20px / margin-left 12px
KBD:        11px / weight 500 / line-height 16.5px / padding 0px 6px
            border: 0.67px solid #e5e7eb / border-radius 4px / bg #fafafa
```

### Inline code
```
font-size:     14.4px (0.9em)
font-weight:   400
background:    rgba(147, 141, 189, 0.23)  ← roxo muito diluído, NÃO cinza
border:        0.67px solid rgba(0,0,0,0.04)
border-radius: 5.4px
padding:       1.7px 3.6px
```

---

## Tokens a atualizar em `packages/ui/src/lib/styles/tokens.css`

Adicionar/substituir a seção de tipografia:

```css
/* ══════════════════════════════════════
   TIPOGRAFIA — Thunder Client exact
   ══════════════════════════════════════ */
:root, [data-theme="light"], [data-theme="dark"] {
  /* Font family (Inter com OpenType features) */
  --netz-font-sans: "Inter Variable", "Inter", ui-sans-serif, system-ui, sans-serif;
  --netz-font-mono: ui-monospace, "SFMono-Regular", Menlo, Monaco, Consolas, monospace;

  /* Font feature settings — igual ao TC */
  --netz-font-features: "rlig" 1, "calt" 1, "ss01" 1;

  /* Escala de tamanhos */
  --netz-text-xs:   11px;   /* KBD, meta labels */
  --netz-text-sm:   14px;   /* breadcrumb, TOC, secondary */
  --netz-text-base: 16px;   /* body, paragraphs */
  --netz-text-md:   15px;   /* nav items sidebar */
  --netz-text-lg:   20px;   /* subtítulos menores */
  --netz-text-h3:   24px;   /* H3 — TC exact */
  --netz-text-h2:   27.2px; /* H2 — TC exact */
  --netz-text-h1:   30.4px; /* H1 — TC exact */

  /* Line heights */
  --netz-leading-tight:  1.11;  /* headings: H1 33.8/30.4 */
  --netz-leading-snug:   1.33;  /* H3: 32/24 */
  --netz-leading-normal: 1.5;   /* base */
  --netz-leading-relaxed: 1.75; /* body paragraphs: 28/16 */

  /* Letter spacing */
  --netz-tracking-tight:  -0.025em; /* todos os headings */
  --netz-tracking-normal: normal;
  --netz-tracking-wide:   0.07em;   /* labels uppercase (se usados) */

  /* Font weights */
  --netz-weight-normal:   400;
  --netz-weight-medium:   500;
  --netz-weight-semibold: 600;
  --netz-weight-bold:     700;

  /* Heading margins (margin-top) */
  --netz-heading-h1-mt: 16px;
  --netz-heading-h2-mt: 40px;
  --netz-heading-h3-mt: 32px;
  --netz-paragraph-mt:  20px;

  /* Border radius */
  --netz-radius-xs: 4px;   /* KBD, nav items — TC: 4px */
  --netz-radius-sm: 5.4px; /* inline code — TC exact */
  --netz-radius-md: 6px;   /* buttons, inputs */
  --netz-radius-lg: 8px;   /* cards */
  --netz-radius-xl: 12px;  /* modals, large cards */
}

/* Link color — TC usa primary-600 */
[data-theme="light"] {
  --netz-link-color:       #006be6;  /* TC: rgb(0,107,230) */
  --netz-link-hover-color: #0055c8;
  --netz-code-bg:          rgba(147, 141, 189, 0.23); /* TC exact — roxo diluído */
  --netz-code-border:      rgba(0, 0, 0, 0.04);
  --netz-kbd-bg:           #fafafa;
  --netz-kbd-border:       #e5e7eb;
}

[data-theme="dark"] {
  --netz-link-color:       #60b0ff;
  --netz-link-hover-color: #90c8ff;
  --netz-code-bg:          rgba(147, 141, 189, 0.15);
  --netz-code-border:      rgba(255, 255, 255, 0.06);
  --netz-kbd-bg:           #1e1e1e;
  --netz-kbd-border:       #333333;
}
```

---

## Arquivo: `packages/ui/src/lib/layouts/PageHeader.svelte`

Atualizar o CSS interno do componente para corresponder ao TC:

```css
.netz-page-header {
  padding: 0;             /* sem padding próprio — pai fornece */
}

.netz-page-header__breadcrumbs ol {
  font-size: 14px;
  font-weight: 400;
  line-height: 20px;
  color: var(--netz-text-muted);   /* #4a5565 light */
  margin-bottom: 6px;
}

.netz-page-header__title {
  font-size: var(--netz-text-h1, 30.4px);
  font-weight: var(--netz-weight-semibold, 600);
  line-height: var(--netz-leading-tight, 1.11);
  letter-spacing: var(--netz-tracking-tight, -0.025em);
  color: var(--netz-text-secondary);    /* #24467f light — azul institucional */
  margin: 16px 0 0;
  font-feature-settings: var(--netz-font-features);
  -webkit-font-smoothing: antialiased;
}

.netz-page-header__subtitle {
  font-size: var(--netz-text-base, 16px);
  font-weight: var(--netz-weight-normal, 400);
  line-height: var(--netz-leading-relaxed, 1.75);
  color: var(--netz-text-muted);
  margin-top: 8px;
}
```

---

## Arquivo: `packages/ui/src/lib/components/Button.svelte`

Ajustes finos para alinhamento com TC (border-radius e fontes):

```css
/* Substituir border-radius dos variants para 4px (TC usa 4px nos itens) */
/* Manter --netz-radius-md (6px) para buttons maiores */

/* O variant default já está correto com --netz-brand-primary */
/* Apenas garantir font-feature-settings */
button, a[role="button"] {
  font-feature-settings: var(--netz-font-features);
  -webkit-font-smoothing: antialiased;
  letter-spacing: -0.01em;  /* leve tracking negativo nos botões */
}
```

---

## Estilos globais a adicionar em `packages/ui/src/lib/styles/app.css` (ou equivalente)

```css
/* Global typography reset — Thunder Client style */
*, *::before, *::after {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

html {
  font-feature-settings: var(--netz-font-features, "rlig" 1, "calt" 1, "ss01" 1);
}

h1 {
  font-size: var(--netz-text-h1);
  font-weight: var(--netz-weight-semibold);
  line-height: var(--netz-leading-tight);
  letter-spacing: var(--netz-tracking-tight);
  color: var(--netz-text-secondary);
  margin-top: var(--netz-heading-h1-mt);
}

h2 {
  font-size: var(--netz-text-h2);
  font-weight: var(--netz-weight-semibold);
  line-height: 1.2;
  letter-spacing: var(--netz-tracking-tight);
  color: var(--netz-text-secondary);
  margin-top: var(--netz-heading-h2-mt);
  padding-bottom: 4px;
  border-bottom: 1px solid var(--netz-border-subtle);
}

h3 {
  font-size: var(--netz-text-h3);
  font-weight: var(--netz-weight-semibold);
  line-height: var(--netz-leading-snug);
  letter-spacing: var(--netz-tracking-tight);
  color: var(--netz-text-secondary);
  margin-top: var(--netz-heading-h3-mt);
}

p { line-height: var(--netz-leading-relaxed); margin-top: var(--netz-paragraph-mt); }

a { color: var(--netz-link-color); text-decoration: underline; }
a:hover { color: var(--netz-link-hover-color); text-decoration: none; }

code:not(pre code) {
  font-family: var(--netz-font-mono);
  font-size: 0.9em;
  background: var(--netz-code-bg);
  border: 0.67px solid var(--netz-code-border);
  border-radius: var(--netz-radius-sm);
  padding: 0.1em 0.3em;
}

kbd {
  font-family: var(--netz-font-mono);
  font-size: var(--netz-text-xs);
  font-weight: var(--netz-weight-medium);
  background: var(--netz-kbd-bg);
  border: 0.67px solid var(--netz-kbd-border);
  border-radius: var(--netz-radius-xs);
  padding: 0 6px;
  line-height: 20px;
}
```

---

## Descobertas críticas que mudam o design atual

### 1. Headings são azul institucional, NÃO preto
TC usa `#24467f` (rgb 36,70,127) para todos os headings no light mode.
O Netz atual usa `--netz-text-primary` que é próximo do preto.
**Correção:** headings devem usar `--netz-text-secondary` (o azul).

### 2. Letter-spacing negativo em TODOS os headings
`-0.025em` consistente em H1, H2, H3.
O Netz atual não tem tracking negativo nos headings.
**Impacto visual:** headings ficam mais "tight" e elegantes, sensação premium.

### 3. Line-height dos headings é muito comprimido
H1: `33.8px / 30.4px = 1.11` — quase unitário.
H2: `32.6px / 27.2px = 1.20`
H3: `32px / 24px = 1.33`
Body: `28px / 16px = 1.75` — muito mais relaxado.
Essa diferença dramática entre heading/body é o que cria a hierarquia visual do TC.

### 4. Inline code tem background ROXO diluído, não cinza
`rgba(147, 141, 189, 0.23)` — é uma mistura de roxo/índigo muito suave.
Cria diferenciação visual sutil sem ser intrusivo. Muito mais elegante que cinza.

### 5. H2 tem border-bottom
TC separa H2 sections com `border-bottom: 1px solid` e `padding-bottom: 4px`.
O Netz atual não tem isso, o que causa menor hierarquia entre seções.

### 6. Antialiasing explícito
TC usa `-webkit-font-smoothing: antialiased` globalmente.
Faz diferença especialmente em macOS/Retina — texto fica mais fino e elegante.

---

## Arquivos a modificar (resumo)

| Arquivo | Mudança |
|---|---|
| `packages/ui/src/lib/styles/tokens.css` | Adicionar tokens de tipografia completos |
| `packages/ui/src/lib/styles/app.css` | Global typography reset estilo TC |
| `packages/ui/src/lib/layouts/PageHeader.svelte` | Atualizar heading styles |
| `packages/ui/src/lib/components/Button.svelte` | font-feature-settings + tracking |

**NÃO modificar:**
- `frontends/wealth/src/routes/(app)/+layout.svelte` (sidebar já feita)
- Nenhuma rota, service, ou lógica de negócio

---

## Regras obrigatórias

1. Apenas CSS/tokens — zero mudanças em lógica de componentes
2. Tokens via `var(--netz-*)` — nunca hardcoded
3. Ambos os temas devem funcionar (dark/light)
4. `make check` deve passar após as mudanças
5. Verificar arquivo `app.css` existente antes de criar — pode já existir como `global.css`

## Deploy após implementar

```powershell
pnpm --filter @netz/ui build
pnpm --filter netz-wealth-os build
npx wrangler pages deploy frontends/wealth/.svelte-kit/cloudflare --project-name netz-wealth
```
