# Design QA — Project Home

- Source visual truth: `/Users/choisunghoon/.codex/generated_images/019ffe1c-36e5-7090-8a12-31a16204c71f/exec-b66cd99c-2038-4bbb-b0b5-2298280a7cf6.png`
- Implementation screenshot: `/Users/choisunghoon/Documents/Aitime/think-along_start/docs/audits/03-project-home-final.png`
- Source pixels: 853 × 1844 (`@2x` mobile reference, approximately 426 × 922 CSS px)
- Implementation pixels: 477 × 982 (426 × 934 CSS px phone frame plus page margin, device scale factor 1)
- State: dark-theme project home with fallback marketing-project content
- Browser verification: `http://127.0.0.1:3000/`

## Findings

- No actionable P0/P1/P2 mismatch remains.
- Fonts and typography: weight, hierarchy, Korean wrapping, and truncation match the reference intent. The installed app font is retained as the closest existing product font.
- Spacing and layout rhythm: the frame was adjusted from 390 × 844 to the reference's approximately 426 × 934 ratio. All three recent rows, the all-conversations action, and the fixed navigation are visible without overlap.
- Colors and visual tokens: near-black background, muted secondary copy, green accent, borders, cards, and selected navigation follow the reference.
- Image and icon fidelity: the screen contains standard UI icons only; existing Lucide assets replace the reference icons without custom drawn substitutes.
- Copy and content: project title, decision, next task, actions, model line, recent conversations, and navigation match the selected reference.

## Comparison History

1. Initial implementation: P2 — 390 × 844 frame clipped the final recent-conversation area behind the bottom navigation.
2. Fix: changed the existing phone frame to 426 × 934, matching the selected reference's normalized aspect and restoring the complete content hierarchy.
3. Post-fix evidence: `docs/audits/03-project-home-final.png`; no P0/P1/P2 visual issue remains.

## Interaction Verification

- `새 Thinking` opens the existing Thinking composer.
- Bottom `Think` returns to the project home.
- Journey, Insight, Profile, model/account, continue, project, and recent-conversation controls remain wired to existing screens.
- Production build and TypeScript checks passed.

## Focused Region Comparison

The source and implementation were compared together at full-view scale. Text, icons, and card boundaries remained readable, so a separate crop was not required.

## Follow-up Polish

- P3: the reference uses slightly different glyph shapes for a few icons; the existing installed icon set is intentionally retained.

final result: passed
