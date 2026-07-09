# Zzzpeak v2 — implementation handoff (overview)

Read this file FIRST before implementing any phase. Every phase doc
(01…06) assumes you have read and will obey this one.

## What v2 is

A second, separate reader app living under `docs/v2/`, served by the same
GitHub Pages site. It starts as a functional copy of the original reader and
gains new features phase by phase. The ORIGINAL app (everything currently in
`docs/` outside `v2/`) must keep working, byte-for-byte unchanged except
where this document explicitly allows.

Target platforms: iPhone Safari (primary), desktop Chrome/Firefox.
Constraints: fully static (GitHub Pages), no backend, no external API at
build time or runtime, no accounts. Book data JSONs in `docs/data/` are
shared read-only.

## THE ISOLATION RULES (non-negotiable)

1. **Frozen files.** Never modify:
   - `docs/index.html`, `docs/read.html`, `docs/looper.html`
   - `docs/js/*` (store.js, tts.js, recorder.js, reader.js)
   - `docs/css/app.css`
   - `docs/manifest.webmanifest`, `docs/icons/*`
   - `docs/data/**` (Phase 06 ADDS new files under `docs/data/`; it never
     edits or regenerates existing book JSONs)
   If a phase seems to require editing a frozen file, STOP and report back
   instead of editing it.

2. **v2 owns only `docs/v2/`** (plus `tools/` additions in Phase 06 and
   docs in `technical/`). v2 gets its OWN COPIES of any JS/CSS it needs —
   copy the file into `docs/v2/js/` and modify the copy. Never `<script src>`
   into `../js/`.

3. **localStorage.** The original uses the single key `zzzpeak.v1`
   (see `docs/js/store.js`). v2 must use the key `zzzpeak.v2` and must NEVER
   write to `zzzpeak.v1`. Reading `zzzpeak.v1` is allowed (one-time import,
   Phase 01).

4. **Service worker.** One `docs/sw.js` governs the whole origin — this is
   the only genuinely shared runtime component and the only frozen-adjacent
   file we touch, exactly once, in Phase 01, with the exact diff given
   there. After Phase 01, `sw.js` is frozen again. Reason: the current
   fetch handler is cache-first for ALL same-origin GETs, so without the
   Phase 01 change, v2 files would be cached on first visit and never
   update.

5. **No link from the original app to v2.** Do not add a v2 link to
   `docs/index.html` (that would modify a frozen file). v2 is reached by
   URL: `https://<site>/v2/`. (A link may be added later only with the
   owner's explicit approval, as its own commit.)

## Commit protocol

- One phase = one feature = at least one commit; commit message prefix
  `v2:` e.g. `v2: phase 02 sentence replay`.
- Before committing, run the regression check below.
- Never mix changes to `tools/` and `docs/` in one commit unless the phase
  doc says so.

## Regression check (run before EVERY commit)

```
git status --short   # confirm: no frozen file appears as modified
git diff --stat HEAD -- docs/index.html docs/read.html docs/looper.html \
    docs/js docs/css docs/manifest.webmanifest   # must be empty
```

Then serve locally (`scripts/serve.sh` or `python3 -m http.server -d docs`)
and manually verify the ORIGINAL app:
1. Library page lists books; opening a book shows the reader.
2. Record → speak → auto-stop → playback loop works.
3. TTS button speaks the phrase.
4. Star a phrase; confirm it appears in review mode.
5. Reload with DevTools offline (after one online visit): app still loads.

If any of these fail, do not commit; investigate.

## Phase order and status

| Phase | Doc | Feature | Depends on |
|-------|-----|---------|------------|
| 01 | 01_scaffold.md | v2 scaffold, storage split, SW rule | — |
| 02 | 02_sentence_replay.md | whole-sentence replay | 01 |
| 03 | 03_ab_compare.md | A/B compare (TTS then take) | 01 |
| 04 | 04_check_mode.md | Check mode (STT transcript diff) | 01 |
| 05 | 05_spaced_repetition.md | spaced repetition on starred deck | 01 |
| 06 | 06_glossary_pipeline.md | glossary + emoji build tooling, tap-gloss UI | 01 |

02–06 are independent of each other; implement in any order after 01.
Each phase doc ends with acceptance criteria — all must pass on desktop
Chrome AND iPhone Safari before the phase is considered done.

## Design principles for all v2 code

- Match the existing code style: plain browser JS, IIFE modules on
  `window`, no build step, no frameworks, no ES modules (keeps old-Safari
  compatibility and matches the codebase).
- Every new feature must be a settings toggle, default OFF, so v2 with all
  toggles off behaves exactly like the original.
- iOS Safari first: any audio/mic feature must respect the hard-won rules
  documented in `docs/js/recorder.js` header comments (user-gesture
  unlock, one shared audio element, keep mic stream alive between takes,
  negotiated mime types).
- Feature-detect and hide, never crash: if an API (SpeechRecognition,
  MediaRecorder) is missing, the related UI disappears and everything
  else still works.

## Future work (do NOT implement, just don't paint over it)

- Mistral API integration (build-time gloss/emoji improvement or runtime
  features) may come later. Keep the glossary JSON format (Phase 06)
  stable and documented so a later generator can slot in.
- More v2 features will follow; keep `docs/v2/js/` modular (one file per
  concern, like the original) so additions stay isolated.
