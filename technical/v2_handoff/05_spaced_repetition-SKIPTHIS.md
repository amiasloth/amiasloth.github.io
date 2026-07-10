# Phase 05 — spaced repetition on the starred deck

Goal: the review deck (starred phrases) is ordered and filtered by a
simple spaced-repetition schedule instead of plain list order. Local-only,
no accounts. Toggleable, default OFF (off = today's behavior).

All work in `docs/v2/` only. Read `00_overview.md` first.

## Current behavior (for reference)

Stars are stored per book+level as `{i, t, e}` (`docs/v2/js/store.js`).
Review mode (`read.html?book=X&review=1`) flattens all starred phrases
across levels into a deck; un-starring removes from the deck
(`toggleStar` in reader.js).

## Design — keep it tiny (SM-2-lite)

Do not implement full SM-2. Per starred item track:
`{box: 0..4, due: epochMs}` — a Leitner box system.

- Boxes → intervals: 0 → 0 (due now), 1 → 1 day, 2 → 3 days,
  3 → 7 days, 4 → 21 days.
- "Success" on a review: box+1 (max 4), due = now + interval.
- "Again": box = 0, due = now.
- New stars start at box 0 (due immediately).

What counts as success (no self-grading buttons if avoidable — the owner
values low-friction UX):
- If Check mode (Phase 04) is available and the take passed → success.
- Otherwise: completing a record→playback cycle on the item counts as
  success; add ONE small "again" button (↻) shown in review mode so the
  user can demote an item they struggled with. That's the whole grading
  UI.

## Implementation

1. **Store** (`docs/v2/js/store.js`): add `srs` map keyed by
   `bookId:level:i` → `{box, due}`. New methods: `getSrs(key)`,
   `setSrs(key, box, due)`, `dueStars(bookId)` returning starred items
   whose `due <= now` (join stars × srs; items with no srs record are due).
   Un-starring deletes the srs record.
2. **Pref**: `srsReview` (bool, default false), settings sheet entry
   rendered in review mode (and/or the main sheet): "Smart review order" /
   "Practice starred phrases when they're due; spacing grows as you
   succeed."
3. **Reader review mode** (`loadDeck()` in reader.js): when `srsReview`
   is on, build the deck from due items only, ordered by `due` ascending;
   show "N due · M scheduled" in the header area. Empty due deck → message
   "Nothing due — come back tomorrow" (with total scheduled count).
4. **Grading hooks**: on playback end of a take in review mode (or check
   pass), call success; the ↻ button calls again. Update `{box, due}`
   immediately and advance to the next due item.
5. **Library page** (`docs/v2/index.html`): if it shows star counts, show
   due counts when the pref is on (optional, keep minimal).

## Acceptance criteria

- Pref off: review mode identical to before (whole deck, list order).
- Pref on: only due items appear; success moves an item up a box (verify
  the stored `due` moves out); ↻ resets to box 0 and it reappears due.
- Un-star removes both star and srs record.
- Time travel test: manually edit `zzzpeak.v2` in DevTools to set a `due`
  in the past/future and confirm filtering.
- Works on iPhone Safari.
- Original app untouched; regression check from `00_overview.md` passes.

Commit: `v2: phase 05 spaced repetition (Leitner) for starred deck`
