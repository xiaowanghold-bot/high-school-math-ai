# Design — 数研备课

A locked design system for the high-school mathematics teacher workspace. Every
page redesign reads this file before emitting code. Extend this file when the
system needs to grow; do not create per-page themes.

## Genre

Modern-minimal, with a restrained academic and paper-like reading register.

## Macrostructure family

- Marketing pages: not in the current product scope.
- App pages: Workbench — persistent tool rail, compact task header, asymmetric
  working panes, and action bars that stay close to the content they affect.
- Content pages: Catalogue — chapter-led index, visible hierarchy, hairline
  groups, and no decorative card grid.

## Theme

- `--color-paper`: `oklch(98% 0.008 250)`
- `--color-paper-2`: `oklch(96% 0.012 250)`
- `--color-paper-3`: `oklch(93% 0.016 250)`
- `--color-ink`: `oklch(22% 0.025 255)`
- `--color-ink-2`: `oklch(38% 0.022 255)`
- `--color-rule`: `oklch(85% 0.015 250)`
- `--color-rule-2`: `oklch(91% 0.012 250)`
- `--color-accent`: `oklch(51% 0.18 255)`
- `--color-focus`: `oklch(34% 0.16 255)`
- State colours are semantic exceptions: teal for verified, amber for caution,
  and red for destructive or blocked actions. Every state also carries text.

## Typography

- Display: Noto Sans SC, weight 700, normal style.
- Body: Noto Sans SC, weight 400.
- Reading outlier: Noto Serif SC, weight 500, used only for mathematical stems,
  explanations, and the wordmark.
- Mono: ui-monospace fallback, used only for identifiers and tabular metadata.
- Display tracking: `-0.025em`.
- Scale: major-third scale anchored at 16 px; app-page H1 uses
  `clamp(1.875rem, 2.6vw, 2.75rem)`.

## Spacing

The 4-point named scale lives in `tokens.css`. New styles use named spacing
tokens and never introduce isolated raw spacing values.

## Motion

- `--ease-out`: `cubic-bezier(0.16, 1, 0.3, 1)`.
- `--ease-in`: `cubic-bezier(0.7, 0, 0.84, 0)`.
- `--ease-in-out`: `cubic-bezier(0.65, 0, 0.35, 1)`.
- No page reveal sequence. Workbench content is immediately available.
- Hover and press feedback use transform or opacity only.
- Reduced-motion fallback removes spatial movement and caps feedback at 150 ms.

## Microinteractions stance

- Silent success when the result is already visible.
- Errors remain visible until dismissed and name the failed operation.
- Hover feedback is subtle; keyboard focus is immediate and never animated.
- Disabled actions retain their label and use opacity plus cursor treatment.

## CTA voice

- Primary CTA: compact ink-filled rectangle, 8 px radius, direct verb label.
- Secondary CTA: paper surface with a rule border; no decorative gradient.
- Destructive CTA: paper surface with red text and border, never colour alone.

## Per-page allowances

- App pages must not use decorative enrichment; function carries the page.
- Question and lesson content may use the reading serif inside controlled
  content surfaces.
- Question images remain inside fixed, overflow-safe figure frames.
- Mobile views may collapse workbench panes into a linear reading order.

## What pages MUST share

- The 数研备课 wordmark and the left work rail.
- The accent colour and its signal-only placement.
- The display, body, reading, and mono roles.
- Button geometry, input heights, focus rings, status language, and spacing.
- Page titles use a compact context line, a roman heading, and one explanatory
  sentence in the same column.

## What pages MAY differ on

- Dashboard uses an asymmetric task launch grid.
- Curriculum uses the Catalogue content variant.
- Search uses a list/detail review split.
- Lesson plans use a control/document editing split.

## Hallmark fingerprint

- Genre: modern-minimal.
- Macrostructure: Workbench, with Catalogue content variant.
- Navigation: adapted N3 app rail — left, 20ch, text labels, filled current-state.
- CTA: C1 compact outlined controls plus one filled primary action per region.
- Theme route: custom tuned.
- Vibe: restrained, academic, precise, paper-like.
- Axes: light / geometric-sans / cool.
- Enrichment: none.

