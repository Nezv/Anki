# Song lyrics ➜ Chinese sentence cards

Turns a Chinese song's lyrics into audio-backed sentence cards in
`Chinese::Sentences`, reusing the repo's existing batch ➜ `.apkg` ➜ Drive flow.

## TTS engine choice

Requirements: open source, Simplified Chinese as a first-class language (not an
afterthought bolted onto an English model), natural prosody, runs offline in
batch.

| Engine | License | Mandarin | Hardware | Verdict |
|---|---|---|---|---|
| **CosyVoice 2 / Fun-CosyVoice3** (Alibaba FunAudioLLM) | Apache-2.0 | Chinese-first; 18+ dialects; strong tone & polyphone handling | GPU (0.5B) | **Primary pick** |
| **MeloTTS** (MyShell) | MIT | Good, handles zh/en code-switching — useful for lyrics with English words | CPU real-time | CPU fallback |
| **Kokoro-82M** | Apache-2.0 | Decent via `misaki[zh]` G2P, but Chinese is its weakest language | CPU real-time | CPU fallback |
| IndexTTS-2 (Bilibili) | Non-commercial | Excellent Chinese | GPU | Licence too restrictive |
| Fish Speech / S2 | Research licence | Best-in-class Chinese WER | GPU | Licence too restrictive |

**CosyVoice 2 is the recommendation.** It's the one that's genuinely *built for*
Chinese rather than multilingual-with-Chinese-included: trained Chinese-first,
handles tone sandhi and polyphones (多音字) from sentence context, and clones a
voice from a 3–10 s reference clip — so every card in the deck speaks in the same
consistent voice you picked. Apache-2.0, no strings.

The catch is that it wants a GPU. That's fine here: this repo already builds in
Colab, so `colab/LyricsAudio.ipynb` runs the synthesis on a free T4. If you'd
rather stay on the laptop, `--engine melotts` or `--engine kokoro` runs on CPU at
roughly real-time with a quality drop.

`--engine edge` (Microsoft's `zh-CN-XiaoxiaoNeural`) is also wired up as a
zero-setup escape hatch. It is **not** open source — it's a free cloud endpoint —
so it's there for smoke-testing the plumbing, not as the answer to what you asked.

## Pipeline

```
lyrics.txt
   │  tools/lyrics_to_batch.py       split lines, strip timestamps, dedupe
   │                                 choruses, generate pinyin (pypinyin)
   ▼
batches/zh-<song>.txt                Sentence | Pinyin | Translation: | Source
   │  ← you or Claude fill in Translation:
   │
   │  tools/gen_audio.py             TTS each Sentence into media/,
   │                                 patch Audio:<file> back into the line
   ▼
batches/zh-<song>.txt (+ media/)
   │  tools/build_apkg.py            Content + [sound:] fields, media packed in
   ▼
anki-YYYY-MM-DD.apkg  ➜  Drive  ➜  import  ➜  Chinese::Sentences
```

### Why audio needs its own Anki field

The existing note types put the whole pipe-string in one `Content` field and let
card JavaScript parse it. Audio can't ride along inside that string: Anki
rewrites `[sound:x.mp3]` into a play-button `<a>` element *before* the template's
JavaScript runs, which would corrupt the string mid-parse.

So `sentence-zh` is the first note type with two real fields — `Content` (parsed
by JS as usual) and `Audio` (`{{Audio}}`, plain, outside the script). The batch
format doesn't change: you still write one flat line, and `build_apkg.py` lifts
the `Audio:` key out of the pipe-string into the real field. Any future note type
gets the same treatment by declaring `fields` and `media_fields` in
`notetypes/models.json`.

### Stable filenames, safe re-imports

Clips are named `zh-<sha1(sentence)[:12]>.mp3`. Same sentence ⇒ same filename, so
re-running `gen_audio.py` skips work already done, and re-importing the `.apkg`
replaces the clip on the existing note rather than piling up duplicates. Note
GUIDs key off `Sentence`, matching the repo's existing update-don't-duplicate
guarantee — you can regenerate a whole song without losing review history.

## Usage

```bash
pip install pypinyin genanki

# 1. lyrics -> batch skeleton (pinyin filled in, translations blank)
python tools/lyrics_to_batch.py lyrics.txt --title 富士山下 --artist 陈奕迅

# 2. fill in the Translation: values

# 3. audio (CPU fallback shown; use Colab for CosyVoice)
python tools/gen_audio.py batches/zh-*.txt --engine melotts

# 4. build
python tools/build_apkg.py
```

Useful flags: `--max-len N` splits long lyric lines on sentence punctuation,
`--keep-dupes` keeps repeated chorus lines as separate cards, `--dry-run` on
`gen_audio.py` lists what would be synthesised without loading a model.

## Open questions for the laptop session

1. **Deck ID.** `Chinese::Sentences` is registered as `1765672709155`. Anki
   matches decks by name on import, so this should land in your existing deck —
   confirm with `python tools/dump_collection.py` and swap in the real ID if it
   doesn't.
2. **Reference voice.** CosyVoice clones from a clip you supply. Worth picking
   one deliberately, since every card will use it.
3. **Committing audio.** ~30–60 KB per line as mp3. Committing `media/` keeps
   rebuilds reproducible from a bare clone; skipping it keeps the repo small and
   means audio must be regenerated in the same session as the build.
4. **Card direction.** Front is currently hanzi + audio; back adds pinyin ruby,
   translation and the song name. A listening-first variant (audio only on the
   front) is a one-line template change if you want it.
