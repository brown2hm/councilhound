# CouncilHound brand assets

- `hound.png` — the logo mark, 239×209, true alpha transparency, trimmed to
  content. The ear-separation stroke is a transparent knockout, so it adapts
  to the surface behind it (verified on cream and dark). Good for the header
  (~40px) and mid-size uses.
- `hound-source.png` — 3330×1248 original render. **No real transparency**
  (background is baked in). Keep for future vectorization or a higher-res
  background removal; don't ship it as-is.

Shipped: favicon set generated from the mark (app/favicon.ico 16-48,
app/icon.png 256, app/apple-icon.png 180 on cream) — regenerate with a
simplified variant if the facets prove muddy at 16px.

Still needed (see DESIGN.md for the system):
- SVG vectorization of the mark (it's flat geometric shapes — very traceable)
- Simplified small-size favicon variant if needed (the facets mush below ~32px)
- Social/OG card

Logo palette (matches DESIGN.md tokens):
- Coral `#d85a30`-family (ears/head) — lead color
- Hound gold / ochre `#e8b94a` (snout, neck)
- Peach `#ffb084` (face warmth)
- Deep teal `#1a3a3a` (ear shadow, eye)
- Ink `#0a0a0a` (nose, eye, detail)
- Sits on the cream canvas `#fffaf0`
