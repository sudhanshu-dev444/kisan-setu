---
name: KisanDirect Field-First UI
colors:
  surface: '#faf8ff'
  surface-dim: '#d2d9f4'
  surface-bright: '#faf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3ff'
  surface-container: '#eaedff'
  surface-container-high: '#e2e7ff'
  surface-container-highest: '#dae2fd'
  on-surface: '#131b2e'
  on-surface-variant: '#3f493f'
  inverse-surface: '#283044'
  inverse-on-surface: '#eef0ff'
  outline: '#6f7a6e'
  outline-variant: '#becabc'
  surface-tint: '#006d30'
  primary: '#00652c'
  on-primary: '#ffffff'
  primary-container: '#15803d'
  on-primary-container: '#d3ffd5'
  inverse-primary: '#79db8d'
  secondary: '#904d00'
  on-secondary: '#ffffff'
  secondary-container: '#fe932c'
  on-secondary-container: '#663500'
  tertiary: '#9a3500'
  on-tertiary: '#ffffff'
  tertiary-container: '#c34500'
  on-tertiary-container: '#fff0ec'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#95f8a7'
  primary-fixed-dim: '#79db8d'
  on-primary-fixed: '#00210a'
  on-primary-fixed-variant: '#005323'
  secondary-fixed: '#ffdcc3'
  secondary-fixed-dim: '#ffb77d'
  on-secondary-fixed: '#2f1500'
  on-secondary-fixed-variant: '#6e3900'
  tertiary-fixed: '#ffdbce'
  tertiary-fixed-dim: '#ffb599'
  on-tertiary-fixed: '#370e00'
  on-tertiary-fixed-variant: '#7f2b00'
  background: '#faf8ff'
  on-background: '#131b2e'
  surface-variant: '#dae2fd'
typography:
  headline-xl:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
  headline-xl-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 34px
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '600'
    lineHeight: 18px
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
  metric-price:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '800'
    lineHeight: 32px
  metric-unit:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-tablet: 1.25rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 1.5rem
  margin-desktop: 2.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1.25rem
  space-xl: 2rem
---

## Brand & Style
This design system establishes an earthy, high-utility, utilitarian aesthetic engineered specifically for field resilience, direct agricultural trade, and dual-actor ergonomics (rural smallholders/FPOs and institutional bulk buyers).

The visual personality balances agrarian vitality with institutional transparency mandated by the Ministry of Consumer Affairs, Food & Public Distribution. It rejects decorative clutter, fragile gradients, and micro-text in favor of high-contrast tactile surfaces, crisp structural data containers, and sunlight-resilient legibility.

### Core Tenets
- **High-Sunlight Legibility**: High luminance contrast across all primary workflows, resisting glare in direct outdoor environments.
- **Physicality & Tactile Feedback**: Tap targets strictly calibrated to $\ge 48\text{px}$ to accommodate one-handed operation in field scenarios.
- **Transactional Transparency**: Metric hierarchy prioritizes market parity indices, Agmarknet/e-NAM benchmark comparisons, net margins, and lot grade statuses without visual obfuscation.

## Colors
The palette utilizes nature-derived functional tones balanced against crisp neutral backgrounds to maximize clarity under varying outdoor ambient light conditions.

### Palette Architecture
- **Primary Green (`#15803d` / Deep `#166534`, Accent `#22c55e`)**: Represents growth, harvest assurance, and primary affirmative actions (e.g., "Accept Offer", "List Produce").
- **Mandi Amber & Gold (`#d97706`, Highlight `#f59e0b`)**: Reserved for statutory markers, live market benchmarks (Agmarknet, e-NAM daily rates), and escrow/payment updates.
- **Harvest Alert Tiers**:
  - Direct Availability: Status Green (`#16a34a`) with light wash backdrop (`#f0fdf4`).
  - Upcoming / In-transit: Amber (`#ca8a04`) with backdrop (`#fefce8`).
  - Urgent / Expiring Lot: Crimson (`#dc2626`) with backdrop (`#fef2f2`).
- **Surfaces & Typographic Neutral (`#0f172a`, Secondary Slate `#334155`, Divider `#cbd5e1`, Canvas `#f8fafc`, Surface `#ffffff`)**: Crisp neutrals offering high contrast against dirty, scratched, or glare-compromised mobile screen hardware.

## Typography
Plus Jakarta Sans provides geometric legibility with wide apertures and distinct counters, optimizing reading speeds for bilingual and multi-lingual Indian regional scripts when rendered alongside Devanagari or regional font fallbacks.

### Numeric & Currency Styling
- Pricing metrics must couple `metric-price` (e.g., `₹2,450`) with `metric-unit` (e.g., `/Qtl` or `/kg`) baseline-aligned, never floating or detached.
- Mandi delta percentages utilize strict tabular numbers (`font-variant-numeric: tabular-nums`) to prevent jitter in live auction boards.

## Layout & Spacing
A fluid 4-column layout is adopted on mobile viewport (`<640px`), expanding to 8 columns on tablet (`640px-1024px`), and 12 columns for desktop procurement dashboards (`>1024px`).

### Spatial Principles
- **Touch Perimeter**: All interactable items adhere to a strict minimum bounding box of $48 \times 48\text{px}$, regardless of interior icon size.
- **Thumb Zone Anchoring**: Critical transactional CTAs ("Confirm Bid", "Book Logistics", "Call Farmer") are pinned persistently to bottom viewports in mobile form factors.
- **Rhythm**: Element stacks scale strictly against a 4px/8px root baseline, preserving compact data density without triggering accidental taps.

## Elevation & Depth
This system intentionally minimizes blur-heavy shadows, which render unpredictably under intense glare. Visual hierarchy is established through surface tinting and structural border containment.

### Stratification Model
- **Base Canvas**: Neutral tint `#f8fafc`.
- **Card Surface**: Solid `#ffffff` bordered with `#e2e8f0` (1px solid).
- **Floating Interactive Surfaces (Modals, Bottom Sheets)**: `#ffffff` supported by an ambient, low-spread drop shadow: `0 8px 24px -4px rgba(15, 23, 42, 0.12)`.
- **Benchmark Accent Layer**: Flat `#fef3c7` border-accentuated surface (1.5px `#f59e0b`) dedicated exclusively to live APMC/e-NAM official comparative data tiers.

## Shapes
A balanced curve geometry is applied across elements:
- Buttons, text inputs, and primary lot cards employ a base corner radius of `0.5rem` (8px).
- Modals, action sheets, and collapsible price breakdown containers use `rounded-lg` (`1rem` / 16px).
- Status badges, pulse pills, and Mandi trade comparison chips strictly utilize full pill structures (`9999px`) to immediately distinguish system indicators from interactive form components.

## Components

### Buttons
- **Primary CTA**: `#15803d` background, `#ffffff` text, minimum height 48px, horizontal padding `1.25rem`. High contrast active state `#166534`.
- **Secondary Mandi Action**: Neutral slate outline (`#cbd5e1`), `#0f172a` text, `#ffffff` background with light `#f1f5f9` active feedback.
- **Destructive/Expiring Action**: Solid `#dc2626` or 1.5px `#dc2626` outline on light crimson wash `#fef2f2`.

### Status Badges with Pulse Dots
- Status components contain a living 8px circular indicator dot.
- "Available Now": Green background `#dcfce7`, text `#166534`, dot `#16a34a` with subtle CSS ring animation.
- "Upcoming Harvest": Amber background `#fef9c3`, text `#854d0e`, static dot `#ca8a04`.
- "Expiring Lot": Red background `#fee2e2`, text `#991b1b`, static dot `#dc2626`.

### Mandi Comparison Chips
- Inline pills displaying local APMC vs. platform direct prices.
- Structure: Tagged with "e-NAM" or local mandi name in small-caps bold, followed by directional price trend indicators (`▲` in `#15803d`, `▼` in `#dc2626`).
- Flat background `#fef3c7` with border `#fde68a`.

### Cards (Commodity & Produce Lots)
- Container: White background `#ffffff`, border 1px solid `#e2e8f0`, internal padding `1rem`.
- Layout: 
  - Header: Crop name + variety tag + quality grade badge (Grade A / FAQ).
  - Body: Net quantity available (Quintals), harvesting date, location radius (km from buyer).
  - Financial Strip: Split columns highlighting "Farmer Asking Price" alongside "Agmarknet Benchmark Modal Rate".
  - Footer: Direct call action button alongside primary "Make Counter-Offer" button.

### Form Inputs & Date Range Selectors
- Tap target height strictly 48px to 52px.
- Inactive border: 1.5px `#cbd5e1`. Active focus state: 2px `#15803d` with clear green boundary ring.
- Numeric inputs for quantities include persistent trailing units ("Qtl", "Kg", "Bags") lock-welded into the input adornment slot.
- Date selectors feature high-contrast quick chips: "Harvested Today", "Next 48 Hours", "Next 7 Days".

### Sparkline Containers & Cost Calculators
- Sparkline containers feature fixed 40px height visualization rows for 7-day rate shifts without extraneous axis labels.
- Net breakdown cost sheets compute: Base Crop Value + Mandi Cess Exemption + Freight/Logistics + Packaging = Final Landed Price per quintal, utilizing alternating tonal backgrounds (`#f8fafc` and `#ffffff`) for rapid readability.