# Prompt: Thunder Client Design System — Wealth OS

## Objetivo

Reimplementar o design visual do Wealth OS adotando exatamente o sistema de design
do Thunder Client Docs como referência. Todos os valores abaixo são computados reais
medidos via `getComputedStyle` na página ao vivo.

---

## Medições exatas (DevTools computed, light mode)

### Sidebar (ASIDE.nextra-sidebar)
```
width:      256px
background: rgb(245, 248, 253)  →  #f5f8fd
color:      rgb(36, 70, 127)    →  #24467f
border:     NENHUMA (0px)       →  separação visual apenas por background
padding:    0px (o aside em si não tem padding — padding fica nos filhos)
```

### Nav item ativo (A.nextra-focus — estado active/current)
```
padding:       6px 8px
font-size:     15.2px  (≈ 0.95rem)
font-weight:   600
line-height:   21.7px
border-radius: 4px
color:         rgb(36, 70, 127)   →  #24467f  (mesmo do texto geral)
background:    rgb(224, 239, 255) →  #e0efff  (azul muito claro)
height:        ~34px
```

### Nav item inativo
```
color:      rgb(75, 85, 105)  →  text-gray-600 Tailwind
background: transparent
hover bg:   rgb(243, 244, 246) →  #f3f4f6  (gray-100)
```

### Section label (separador de grupo — LI sem link)
```
padding:       6px 8px
font-size:     14px        ← NÃO é uppercase pequeno. É 14px semibold normal case
font-weight:   600
color:         #101828     (quase preto — lab(8.11 0.81 -12.25))
background:    transparent
margin-top:    20px        (classe x:not-first:mt-5)
margin-bottom: 8px         (classe x:mb-2)
```

### Article (área de conteúdo principal)
```
padding:    16px (mobile) / 48px horizontal em md+
padding-bottom: 32px
background: rgb(245, 248, 253)  →  #f5f8fd  (MESMO que sidebar no light)
color:      rgb(36, 70, 127)    →  #24467f
font-size:  16px
line-height: 24px
```

### Navbar (header nav)
```
height:     58px
padding:    0px 24px
background: rgb(255, 255, 255)  →  #ffffff  (BRANCO — diferente do conteúdo)
gap:        16px entre items
font-size:  16px
```

---

## Implicações arquiteturais importantes

1. **Sem border entre sidebar e conteúdo** — a separação é apenas pelo fundo `#f5f8fd` vs
   `#ffffff` do navbar. No nosso app, o navbar deve ser branco e o conteúdo/sidebar `#f5f8fd`.

2. **Section labels NÃO são uppercase** — são 14px semibold, cor quase preta, caixa normal.
   Nada de `text-transform: uppercase` ou `letter-spacing`.

3. **Nav items são 15px, não 13px** — mais legíveis que o comum em sidebars.

4. **Active state é azul claro `#e0efff`** — não é o brand color puro. É uma versão
   muito diluída do azul, com o texto na cor escura `#24467f`.

5. **Accordion de subitens** usa uma linha vertical `::before` à esquerda (1px, `#e5e7eb` light /
   `#262626` dark), com `padding-left: 12px` e `margin-left: 12px` nos subitens.

---

## Mapeamento para tokens Netz

Substituir `packages/ui/src/lib/styles/tokens.css` com os seguintes valores:

```css
/* ══════════════════════════════════════
   LIGHT THEME — Thunder Client exact
   ══════════════════════════════════════ */
[data-theme="light"], :root {
  /* Backgrounds */
  --netz-bg:                #f5f8fd;  /* tc: rgb(245,248,253) — azulado suave */
  --netz-surface:           #f5f8fd;  /* artigo e sidebar = mesmo fundo */
  --netz-surface-elevated:  #ffffff;  /* navbar, cards elevados = branco puro */
  --netz-surface-alt:       #f5f8fd;  /* sidebar */
  --netz-surface-panel:     #ffffff;
  --netz-surface-highlight: #e0efff;  /* active nav item bg */

  /* Borders */
  --netz-border-subtle:     #e8eef7;
  --netz-border:            #d8e2f0;
  --netz-border-accent:     #c5d3e8;
  --netz-border-focus:      #0077e6;

  /* Text */
  --netz-text-primary:      #101828;  /* section labels — quase preto */
  --netz-text-secondary:    #24467f;  /* tc: rgb(36,70,127) — azul institucional */
  --netz-text-muted:        #4b5565;  /* nav items inativos */
  --netz-text-tertiary:     #7a8fad;
  --netz-text-on-accent:    #ffffff;

  /* Brand */
  --netz-brand-primary:     #0077e6;  /* nextra primary hsl(212,100%,45%) */
  --netz-brand-secondary:   #24467f;  /* azul institucional TC */
}

/* ══════════════════════════════════════
   DARK THEME — Thunder Client exact
   ══════════════════════════════════════ */
[data-theme="dark"] {
  /* Backgrounds */
  --netz-bg:                #111111;  /* tc dark: rgb(17,17,17) = nextra-bg dark */
  --netz-surface:           #111111;
  --netz-surface-elevated:  #1a1a1a;
  --netz-surface-alt:       #111111;  /* sidebar dark = mesmo bg */
  --netz-surface-panel:     #1e1e1e;
  --netz-surface-highlight: rgba(59,130,246,0.1); /* active nav dark */

  /* Borders */
  --netz-border-subtle:     #262626;  /* dark:before:bg-neutral-800 */
  --netz-border:            #333333;
  --netz-border-accent:     #404040;
  --netz-border-focus:      #3b9eff;

  /* Text */
  --netz-text-primary:      #f0f0f0;
  --netz-text-secondary:    #a8a8a8;  /* dark:text-neutral-400 */
  --netz-text-muted:        #666666;
  --netz-text-tertiary:     #444444;
  --netz-text-on-accent:    #ffffff;

  /* Brand */
  --netz-brand-primary:     #3b9eff;  /* primary mais claro no dark */
  --netz-brand-secondary:   #60b0ff;
}
```

---
