# Chart tools (vendored)

Copied from the Claude Code dataviz skill so the path is stable and committable.

- `validate_palette.py` / `validate_palette.js`: palette validator (lightness band, chroma floor,
  colour-blind separation, normal-vision floor, contrast). Exit code 1 if any check fails.
- `dataviz_palette_reference.md`: the default categorical, sequential and diverging palette values.

```bash
python components/predictive_farm_intelligence/docs/tools/validate_palette.py "#2a78d6,#eb6834,#6250d6" --mode light
node   components/predictive_farm_intelligence/docs/tools/validate_palette.js "#2a78d6,#eb6834,#6250d6" --mode light
```

Fixed model colours across all PFOI charts: current model blue `#2a78d6`, persistence orange
`#eb6834`, linear violet `#6250d6`. `docs/make_linear_figures.py` runs the validator before drawing
and stops if it fails. Validate dark mode too (`--mode dark`) if a chart is shown on a dark slide.
