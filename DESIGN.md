# Design

Visual system for the systematic trading control plane. Strategy, users and
principles live in [PRODUCT.md](PRODUCT.md); this file is how it looks and why.

Source of truth is `web/src/app/globals.css`. If the two disagree, the
stylesheet is right and this file is stale.

## Theme

**Dark by default, light supported.** Chosen from one sentence about the room
rather than from taste: *one person at a desk, late, in a room lit by the
screen, reading a table of numbers to decide whether a month of compute
produced anything real.* A screen-lit room and a long session force dark; the
light theme exists because daytime happens and is a full peer, not an
afterthought.

Colour strategy: **restrained**. Tinted neutrals plus one accent that never
exceeds about a tenth of the surface. The signal colours below are not part of
that budget; they appear only where there is a state to report.

## Colour

OKLCH throughout, so lightness is perceptual and the two themes can be reasoned
about in the same units.

### Surfaces

Graphite with a small chroma toward the accent's own hue (255), not the default
drift toward warm. Warm-tinting neutrals "because the brand feels that way" is
the move every project makes at once.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `0.178 0.011 255` | `0.977 0.003 255` | Page |
| `--panel` | `0.221 0.013 255` | `1 0 0` | Cards, top bar |
| `--panel-2` | `0.262 0.015 255` | `0.958 0.004 255` | Inputs, pills, row hover |
| `--border` | `0.322 0.016 255` | `0.885 0.006 255` | Hairlines |
| `--border-strong` | `0.412 0.018 255` | `0.800 0.010 255` | Buttons, table head rule |

### Ink

| Token | Dark | Light | Use |
|---|---|---|---|
| `--text` | `0.955 0.004 255` | `0.240 0.014 255` | Body |
| `--muted` | `0.723 0.013 255` | `0.487 0.016 255` | Secondary prose, labels, placeholders |
| `--faint` | `0.645 0.012 255` | `0.528 0.014 255` | Unreachable lifecycle stages |

`--faint` still clears 4.5:1. It is de-emphasis, not decoration, and everything
it is used on is read.

### Accent

`0.740 0.093 232` dark, `0.520 0.110 232` light. A low-chroma steel.

Reserved for primary actions, current selection and focus. Never decorative.
Deliberately not the SaaS blue this project's palette used to be borrowed from,
and low enough in chroma to sit beside the signal colours without competing.

### Signal

Three states, and the ordering is the point.

| Token | Dark | Light | Chroma | Means |
|---|---|---|---|---|
| `--blocked` | `0.725 0.185 30` | `0.404 0.190 30` | highest | Refused, failed, halted |
| `--unknown` | `0.800 0.140 78` | `0.464 0.130 70` | middle | Not measured, indeterminate |
| `--settled` | `0.660 0.072 158` | `0.524 0.075 158` | lowest | Met, passed, alive |

**Attention is carried by chroma, not lightness.** `--blocked` is the most
saturated thing on any screen and `--settled` the least, which inverts the usual
dashboard instinct where success is the bright colour. An operator opens this to
find out what is wrong; a page where "passed" shouts and "refused" murmurs is
optimised for the wrong reader.

**Lightness is spent on accessibility instead.** The three are held at least
0.06 apart in L, so they remain distinguishable in greyscale and under
protanopia and deuteranopia. Hues additionally sit on the blue/orange axis,
which is the one that survives both.

Every value was solved for, not chosen. Each clears 4.5:1 against `--panel-2`,
which is what a pill actually renders on. The first draft tinted each pill with
16% of its own hue; that coupled the contrast target to the lightness target and
made them jointly unsatisfiable on dark, with `blocked` and `settled` both
pinned near L 0.70. Three values failed a measured check. Dropping the tint for
a neutral chip freed lightness entirely and is quieter on a status-dense page
besides.

### `--unknown` is not grey, and that is the most important decision here

An unmeasured figure used to render in the same muted grey as "nothing to say
about this". Those are different facts. The system's first principle is that
absence is a state rather than a zero, and rendering the most important honest
state in the quietest colour available made it the easiest thing on the page to
miss.

The same amber marks model-authored content (`.badge`). The link is deliberate:
a model-drafted hypothesis card and an unmeasured metric are both *not
established fact*, and they should read as the same category of thing.

## Typography

System stacks. `ui-sans-serif` for everything, `ui-monospace` for figures.

A product UI does not need a display face. One well-tuned sans carrying
headings, labels, buttons and prose is one fewer thing that can drift out of
tune, and the register permits it.

**Fixed rem, never `clamp()`.** Users read this at one DPI at one desk. A
heading that resizes with the viewport looks worse inside a panel, not better.

| Token | Size | Use |
|---|---|---|
| `--t-xs` | 11px | Uppercase labels, metric keys, pills |
| `--t-sm` | 12px | Table cells, dense metadata |
| `--t-base` | 13px | Secondary prose, inputs, buttons |
| `--t-body` | 14px | Body |
| `--t-md` | 16px | h3, metric values |
| `--t-lg` | 19px | h2 |
| `--t-xl` | 23px | h1 |

Ratio about 1.2. Tighter than a marketing page on purpose: there are many type
roles on these screens and exaggerated contrast between them reads as noise.

`font-variant-numeric: tabular-nums` on every figure. Numbers here are read down
a column and compared with the one above; proportional digits turn a glance into
a reading task.

**Tables set in sans, not monospace.** Only `.num` and `.mono` cells opt into
the monospace face. A table set entirely in monospace turns every label and
sentence inside it into pseudo-data: "Risk-adjusted return" renders with a
hyphen the width of an en dash and reads as a formula.

Prose is capped at 65–75ch (`.subtitle`, `.gate-criterion-detail`, `td.prose`).
Tables and dense metadata are exempt and run as wide as they need.

## Spacing and layout

4px base, `--s-1` through `--s-7`. Varied deliberately: sections breathe at
`--s-6`, table rows hold at `--s-2`.

Cards are used where a boundary is real and not as the default container. A card
inside a card is reset to nothing, because the second border says "separate
thing" about something that is part of the first.

The pipeline board scrolls inside its own container rather than widening the
page. Nine stage columns never fit a laptop, and a body that scrolls sideways
makes every other page feel broken. Stages the system cannot yet evidence are
dimmed rather than hidden, so the lifecycle reads as one thing with an end the
operator has not reached.

Z-index is a named scale: `--z-sticky` 100 → `--z-dropdown` 200 →
`--z-backdrop` 300 → `--z-modal` 400 → `--z-toast` 500. Never an arbitrary 999.

## Components

Every interactive element has default, hover, focus, active and disabled.

**Buttons carry the asymmetry between stopping and starting.** The committing
action is the only filled control on a screen (`button.primary`, accent fill);
everything else is an outline. The shape says which way is which before the
label is read, which is the visual half of a rule the API already enforces.
Disabled controls never keep a saturated fill: a disabled button that still
looks primary invites the click it is about to refuse.

**Pills are neutral chips.** `--panel-2` background with coloured text, a
coloured border and a leading glyph. Colour is never the only channel:

| State | Glyph | Colour |
|---|---|---|
| met, pass, alive | `✓` | `--settled` |
| unmet, fail, blocked | `✕` | `--blocked` |
| caution, N unmet | `▲` | `--unknown` |
| not measured, unknown | `?` | `--unknown` |
| neutral, open | `•` | `--muted` |

Each glyph is set with an empty alternative text (`content: "✓" / ""`) so a
screen reader announces the label rather than the decoration.

**Absent figures say so.** `.no-data` renders the words rather than a dash:
beside right-aligned numbers a dash reads as a minus sign, and an absent
measurement must never be mistakable for a value.

**Skeletons, not spinners.** A skeleton in the shape of what is arriving tells
an operator how much of it there is; a spinner tells them only that something is
happening.

## Motion

150–250ms, `cubic-bezier(0.16, 1, 0.3, 1)`. Exponential ease-out only. No
bounce, no elastic: a control panel that springs is a control panel you distrust.

Motion reports a change and does nothing else. There are no page-load sequences.
The two animations that exist are the skeleton sweep and `.changed`, which marks
a value that has just updated: on a page that polls every ten seconds, a figure
changing with no acknowledgement is a figure the operator has to diff against
memory.

`prefers-reduced-motion` gets an alternative rather than a removal. The skeleton
becomes a steady opacity pulse, which still reads as "loading" without
translating anything across the screen.

## Accessibility

WCAG 2.2 AA, verified by computation rather than by eye. Every pair below was
measured; three of the first-draft values failed and were solved for.

| Pair | Dark | Light |
|---|---|---|
| `--text` on `--bg` | 16.6 | 15.4 |
| `--muted` on `--panel` | 7.0 | 6.3 |
| `--faint` on `--panel-2` | 4.7 | 4.7 |
| accent link on `--bg` | 8.3 | 5.0 |
| `--accent-ink` on accent | 8.2 | 5.3 |
| `--blocked` pill | 5.7 | 6.4 |
| `--unknown` pill | 8.1 | 6.4 |
| `--settled` pill | 5.1 | 4.6 |

One focus ring, applied via `:focus-visible` to every interactive element,
2px accent at 2px offset. Never suppressed without replacement.

Placeholders use `--muted`, not `--faint`. The first draft used the latter and
measured 3.32:1, which is the exact failure the surrounding comment claimed to
prevent.

## Anti-references

Recorded in PRODUCT.md and repeated here because they are visual decisions:
navy-and-gold institutional finance, terminal-green-on-black, and cream or
warm-neutral paper backgrounds. The palette this replaced was GitHub Primer
near-verbatim.
