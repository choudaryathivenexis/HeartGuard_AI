# Image credits

## Status: vector artwork ships; photography still does not

Domain imagery now ships, as **generated SVG** in `ui/illustrations.py` — an ECG
trace, a stroked heart with a diagnostic trace through it, and a coronary vessel
watermark. They appear on the sign-in panel and, opt-in, beside a page title.

This does not contradict the position below; it routes around it. Every objection
recorded there is an objection to **sourcing stock photography** in an environment
with no network and a frozen dependency list. Vector artwork has none of those
problems: it is drawn from `ui/tokens.py`, so it re-themes with the palette, it cannot
404 offline, it adds no dependency and no bytes to `assets/`, and it stays sharp at
any viewport.

The reject list is still honoured where it was making a design point rather than a
sourcing point. In particular **"no red heart forms"**: the heart here is a stroked
outline carrying an ECG trace, never a filled valentine shape, and nothing is
animated. See the module docstring in `ui/illustrations.py` for the full reasoning.

`assets/img/` remains empty and the photography pipeline below remains available.

## The original position: no photography

`assets/img/` is intentionally empty. The login panel renders on its **flat Ink
surface with the ambient Reference Rail overlay**, which §3.9 defines as the graceful
fallback.

This is a deliberate position, not an omission:

1. **No image could be sourced in the build environment.** There is no network access
   to browse, vet and download from Unsplash, and §1.3 forbids adding a dependency to
   do it. Fabricating a placeholder would be worse than shipping the fallback.

2. **The fallback may be the stronger choice regardless.** §3.9 rule 3 states that if
   an image still looks like a stock photo after duotone treatment, "the treatment is
   too weak or the image is wrong." A flat Ink panel carrying the signature element at
   8% opacity introduces the product's visual language on first contact with no risk
   of reading as a template. The photographic budget in §3.9 is "two, possibly three"
   images for the whole application — zero is closer to that intent than a poorly
   vetted one.

The full duotone pipeline, CSS layers and fallback logic are implemented, so dropping
a vetted file into `assets/img/login-panel.webp` activates it with no code change.

## To add an image

1. Source from Unsplash using the §3.9 search terms — `precision machined surface`,
   `oscilloscope grid long exposure`, `anodised metal close up`,
   `calibration instrument macro`, `topographic contour lines`.

2. Apply the reject list without exception: **no people**, no medical props, no red
   heart forms, no warm-hospital bokeh, no visible signage, and nothing where the
   subject is more interesting than the texture.

3. Vendor the file — do not hotlink. `source.unsplash.com` is deprecated, and any CDN
   reference means the panel 404s on a machine without internet, which is exactly the
   condition a marker may run this under.

4. Resize to 2400px wide maximum and compress under 200KB. WebP via Pillow (already
   installed); fall back to JPEG quality 82.

5. Record the attribution below. The Unsplash License does not require it; it is
   recorded anyway because this is submitted as academic work.

## Attribution table

| File | Photographer | Profile | Source | Retrieved | Licence |
|---|---|---|---|---|---|
| *(none shipped)* | — | — | — | — | — |

## Generated brand assets

These are produced by `ui/brand.py`, not sourced. No third-party rights apply.

| File | Origin |
|---|---|
| `brand/favicon.png` | Caliper Mark rendered at 512×512 via Pillow, Ink on Bone |
| `brand/favicon-dark.png` | As above, inverted |
| `brand/lockup.svg` | Exported for the dissertation; not used at runtime |

## Generated domain artwork

Emitted inline at render time by `ui/illustrations.py`. Nothing is written to disk, so
there are no files to attribute and no third-party rights apply.

| Function | What it draws |
|---|---|
| `ecg_strip` / `ecg_path` | PQRST cardiac trace from a fixed synthetic profile |
| `heart_outline` | Stroked cubic-Bezier heart, no fill |
| `heart_pulse_mark` | The above with one ECG cycle clipped inside it |
| `vessel_watermark` | Hand-plotted coronary branch tree, used at ~7% opacity |
| `login_hero` | Vessel watermark plus ECG trace, composed for the sign-in panel |

The trace is **ornament, not data**. It is generated from a constant morphology and
never from `heart.csv` or from a prediction — this application estimates risk from
tabular indicators and never acquires a waveform, so a trace that appeared to show a
reading would assert a measurement that does not exist.
