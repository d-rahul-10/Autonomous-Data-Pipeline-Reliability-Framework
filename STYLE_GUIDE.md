# PipelineIQ cyberpunk design system

This guide documents the visual system and motion actually used by the Flask dashboard. The implementation lives in `static/cyberpunk.css`; the dashboard structure and behavior remain in `templates/index.html` and `static/app.js`.

## Visual direction

Use a restrained cyberpunk-anime influence: midnight surfaces, cool luminous cyan, a small violet counter-accent, precise monospaced data, and quiet grid/scanline texture. Keep information density and legibility ahead of decorative effects. Textures are pointer-transparent and low-contrast; no background video, particle canvas, or external font request is used.

## Color palette

| Token | Value | Use |
|---|---|---|
| `--bg-deep` / `--canvas` | `#080D14` | App background |
| `--bg-card` / `--white` | `#101923` | Cards, panels, controls |
| `--bg-elevated` | `#152330` | Elevated surfaces |
| `--bg-hover` | `#192B38` | Hover surfaces |
| `--line` | `#203541` | Default borders |
| `--ink` / `--text-primary` | `#E6F1F4` | Primary text |
| `--text-secondary` | `#BDCBD1` | Supporting text |
| `--muted` / `--text-muted` | `#A0B3BC` | Captions and secondary labels |
| `--neon-cyan` / `--blue` | `#60E8DF` | Primary action, selected navigation, focus |
| `--neon-magenta` | `#D9A0FF` | Secondary accent, charts |
| `--neon-green` / `--green` | `#7CE7B2` | Healthy and recovered states |
| `--neon-orange` | `#FFCA78` | Watch and warning states |
| `--error` / `--red` | `#FF8798` | Errors and critical states |

Do not use glow or color alone to convey status. Keep visible labels/icons and preserve the semantic good, watch, critical, and error treatments.

## Typography

| Role | Token | Stack |
|---|---|---|
| Interface | `--font-ui` | Segoe UI Variable, Bahnschrift, Segoe UI, sans-serif |
| Headings | `--font-display` | Bahnschrift, Segoe UI Variable Display, Segoe UI, sans-serif |
| Metrics and technical labels | `--font-mono` | Cascadia Code, SFMono-Regular, Consolas, monospace |

Fonts are local system fallbacks; the page does not depend on a remote font service. Use tabular numerals for metric values and keep body copy at readable sizes.

## Animation tokens

| Token / behavior | Value | Use |
|---|---|---|
| `--duration-fast` | `160ms` | Hover, focus, and control feedback |
| `--duration-normal` | `260ms` | Card and selected-state transitions |
| `--ease-out` | `cubic-bezier(.2, .75, .25, 1)` | Responsive settling |
| Tab transition | `300ms`, `power2.out` | Active dashboard view |
| Scroll reveal | `480ms`, `power2.out`, 16px rise | Panels entering view |
| `--glow-sm` | `0 0 14px rgba(96, 232, 223, .14)` | Focus/hover accent |
| `--glow-md` | `0 0 22px rgba(96, 232, 223, .22)` | Primary emphasis |

GSAP is bundled locally from the pinned npm dependency and used for tab transitions and one-time scroll reveals. An `IntersectionObserver` starts reveals only as content approaches the viewport; CSS handles hover and focus feedback. Motion is skipped when `prefers-reduced-motion: reduce` is set, and content remains visible if GSAP or `IntersectionObserver` is unavailable.

## Component variants

| Component | Variants / states |
|---|---|
| `.button-primary` | Main action, cyan gradient; hover brightens and lifts; active presses; disabled is non-interactive |
| `.button-secondary` | Quiet outlined action; cyan border/text on hover |
| `.nav-item` | Default, hover, and `.active` selected state with a cyan leading rule |
| `.metric-card` | Dark data card with a restrained top highlight; hover lifts on pointer devices |
| `.panel` | Standard dark information surface; use the shared border, radius, and shadow |
| `.health-pill.good` | Green healthy status |
| `.health-pill.watch` / `.risk-tag` | Amber watch state |
| `.health-pill.critical` / `.notice` | Coral critical/error state |
| `.source-panel` | Highlighted input surface with a cyan top edge |
| `.log-console` | Deep terminal surface with readable mint log text |

Keep existing semantic element roles, IDs, `data-tab` hooks, and form labels intact when changing markup; `app.js` uses them to wire dashboard behavior.

## Textures and effects

- A subtle 44px cyan grid and low-opacity scanlines are applied with fixed pseudo-elements.
- The welcome visualization uses slow CSS orbital motion and existing inline SVG nodes.
- Avoid per-frame layout changes, large animated backgrounds, and unnecessary particle canvases.
- Keep overlays `pointer-events: none`; disable non-essential texture in reduced-motion or print contexts.

## Accessibility and responsive behavior

- Use `:focus-visible` outlines with a cyan ring; retain native keyboard and form behavior.
- Support `prefers-reduced-motion` and `prefers-contrast: more`.
- Statuses use text labels as well as color; errors remain announced through the existing live region.
- Preserve SVG `aria-hidden` labels and explicit input/combobox labels.
- The sidebar collapses to icon navigation below 850px; the main content and metric grids reflow, and wide tables scroll within their containers.
- A print stylesheet removes texture and navigation and presents surfaces on white.

## Updating the local GSAP bundle

The Flask app serves `static/vendor/gsap.min.js` directly and does not need Node.js at runtime. GSAP is distributed under its standard no-charge license; see the [GSAP license terms](https://gsap.com/standard-license/). When updating the npm dependency, refresh the lockfile with `npm install` and copy the package's distribution bundle:

```powershell
Copy-Item .\node_modules\gsap\dist\gsap.min.js .\static\vendor\gsap.min.js
```
