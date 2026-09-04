# Vendored design skills

Project-local Agent Skills (OpenCode discovers `.opencode/skills/*/SKILL.md`).
All files vendored byte-identical from upstream (only taste-skill directories were
renamed to match their frontmatter `name:`, which OpenCode requires).

| Source | Commit | License | Skills |
|---|---|---|---|
| `emilkowalski/skills` | `d23d7f8` | MIT | `emil-design-eng`, `animate`, `animate-expo`, `review-animations`, `improve-animations`, `find-animation-opportunities`, `animation-vocabulary`, `apple-design`, `write-swift`, `pick-ui-library`, `prototype`, `ask-sonner` |
| `Leonxlnx/taste-skill` | `ccbc156` | MIT | `design-taste-frontend` (+`v1`), `gpt-taste`, `image-to-code`, `redesign-existing-projects`, `high-end-visual-design`, `full-output-enforcement`, `minimalist-ui`, `industrial-brutalist-ui`, `stitch-design-taste`, `imagegen-frontend-web`, `imagegen-frontend-mobile`, `brandkit` |
| `pbakaus/impeccable` | `fbc5c95` | Apache 2.0 | `impeccable` (23 commands via `/impeccable`, see `.opencode/commands/impeccable.md`) |

## Which skill when (hub is Vite + vanilla JS)

- Existing UI audit/fix pass → `redesign-existing-projects`, then `/impeccable audit|critique|polish`
- Motion questions → `emil-design-eng` (main guide), `animate` (new), `review-animations` (critique), `improve-animations` (codebase-wide plan)
- Greenfield piece → `design-taste-frontend` (default) or `minimalist-ui` / `high-end-visual-design` once direction is chosen
- `write-swift`, `animate-expo`, `ask-sonner`, image-generation skills: not used by this repo (no native/mobile/Sonner targets) — kept for completeness

## Notes

- Impeccable provider hooks are NOT installed (they need per-harness trust + `npx impeccable`); the skill + detector scripts work standalone. Ephemeral `.impeccable/` output is gitignored (see root `.gitignore`).
- Update: re-clone upstream to `/tmp`, copy dirs per the table above, re-run the frontmatter validation (name == dirname, `^[a-z0-9]+(-[a-z0-9]+)*$`, description 1–1024 chars).
