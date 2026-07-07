# Zzzpeak — easy reading for language learners

Public-domain books, pre-chunked into bite-size meaningful phrases, read one
phrase at a time — with a **loop recorder**: record yourself reading the
phrase, hear it played back, and recording starts again automatically
(say → listen → say), until you stop it.

Fully static. No accounts, no backend, no AI at runtime. Everything —
including the book data — is public and lives in this repo.

## Layout

```
docs/            the web app (GitHub Pages serves this folder)
  index.html     library
  read.html      reader (?book=alice)
  looper.html    standalone loop recorder
  data/          pre-chunked book JSON (generated, committed)
tools/
  chunk.py       deterministic spaCy phrase chunker (no AI)
  emoji_map.py   lemma -> emoji hints
  build_data.sh  regenerates docs/data/ from tools/sources/
  sources/       Project Gutenberg plain-text sources
```

## Deploy to GitHub Pages

1. Push this repo to GitHub (public).
2. Repo **Settings → Pages → Source**: branch `main`, folder `/docs`.
3. Open `https://<user>.github.io/<repo>/` on your iPhone, tap
   Share → **Add to Home Screen**. It runs full-screen like an app and the
   books work offline.

Recording requires HTTPS — GitHub Pages provides it. On iOS, allow
microphone access when Safari asks (Settings → Safari → Microphone if you
previously denied it).

## Rebuilding / adding book data

One-time setup on your machine:

```
pip install spacy
python -m spacy download en_core_web_sm
python -m spacy download de_core_news_lg
```

Regenerate everything: `bash tools/build_data.sh`

Add a new book: download the Project Gutenberg **Plain Text UTF-8** file
into `tools/sources/`, add a block to `tools/build_data.sh` (see the Alice
block; `--skip-until` is a regex marking where the actual text begins), run
the script, and add an entry to the `books.json` section at the bottom of
the script. Commit `docs/data/` — it is meant to be public.

Levels: `starter` (1–3 words per phrase — for languages like German whose
phrases pack a lot into few words), `beginner` (2–5), `intermediate` (≤8),
`advanced` (≤12). The chunker is deterministic — same input, same output —
and asserts for every sentence that the chunks reconstruct the original
text exactly.

## Practice settings (⚙︎ in the reader)

- **Auto-stop when you pause** (default on): voice activity detection ends
  the take after ~1s of silence — no second tap.
- **Hide text while you speak**: the phrase blurs away the moment your
  voice starts (the emoji hint stays) and returns for playback — recall
  practice.
- **Record when you go to the next phrase**: tapping next starts the next
  take immediately.
- **After playback**: repeat this phrase (classic loop) / go to the next
  phrase (hands-free flow) / stop.

With auto-stop + "next phrase" you tap Record once and just read: speak,
pause, hear yourself, next phrase appears, already recording.

Progress and settings live in `localStorage` — on the device, per browser
(the installed home-screen app has storage separate from the Safari tab);
nothing is ever sent anywhere.

## Notes on recording (the historically tricky part)

`docs/js/recorder.js` handles the platform quirks in one place:

- negotiates the container: `audio/mp4` on iOS Safari, `audio/webm` elsewhere;
- falls back to Web-Audio WAV capture where `MediaRecorder` is missing;
- unlocks the shared `<audio>` element inside the user's tap so the
  automatic loop playback isn't blocked by autoplay rules;
- keeps the mic stream alive between loop iterations (releasing it makes
  iOS flap its audio session and re-prompt), releasing it on Reset,
  page-hide, or when you move to another phrase.
