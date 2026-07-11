# Anki

Language-learning flashcard pipeline: note strings live in this repo, Google Colab builds the `.apkg`, Google Drive delivers it to any device.

## Workflow

1. **Generate strings** — Claude (or you) turns language data into note lines and saves them in `batches/*.txt`, then pushes to this repo.
2. **Build** — open [`colab/AnkiBuilder.ipynb`](colab/AnkiBuilder.ipynb) in Google Colab and *Runtime ▸ Run all*. It pulls this repo, builds `anki-YYYY-MM-DD.apkg`, and writes it to `MyDrive/Anki/`.
3. **Import** — open the `.apkg` from Drive on any device with Anki. Decks and note types are created/updated automatically.

Re-importing is always safe: note GUIDs are derived from the key field (e.g. the hanzi character), so an updated batch **updates** existing cards without duplicating them or losing review history.

## Batch file format

One note per line, `Key:Value` pairs separated by `|`. Directives start with `#` and apply to the lines below them:

```
#notetype: hanzi
#deck: 汉语
#tags: hsk1
Hanzi:不|Pinyin:bù|Meaning:not, no|Words:不是,不好|WordPinyin:bù shì,bù hǎo|WordMeanings:is not,not good|Radicals:一 丿|Sentence:我不是学生。|SentencePinyin:wǒ bù shì xué shēng|SentenceMeaning:I am not a student.
```

### Note types

| slug | Anki name | key field | fields in the Content string |
|---|---|---|---|
| `hanzi` | 汉字 | `Hanzi` | Hanzi, Pinyin, Meaning, Words, WordPinyin, WordMeanings, Radicals, Sentence, SentencePinyin, SentenceMeaning |
| `kanji-ja` | 漢字 | `Kanji` | Kanji, Furigana, Meaning, OnYomi, KunYomi, WordExamples, WordFurigana, WordTranslations, Radicals |
| `vocab-ja` | 言葉 | `Word` | Word, Kana, Translation, Example, Furigana, ExampleTranslation |
| `sentence-ja` | 分達 | `Sentence` | Sentence, Translation, Furigana, Words, WordTranslations |

All note types have a single real Anki field (`Content`); the card's JavaScript parses the pipe-string and renders it. Pinyin/furigana are space-separated, one syllable per character; lists (Words, WordPinyin, …) are comma-separated, and pinyin for multi-character words uses spaces between syllables.

Everything after the key fields is optional — the `hanzi` template hides empty sections instead of breaking.

## Repo layout

```
notetypes/    card templates (front.html / back.html / style.css per note type)
              models.json — stable model & deck IDs (never change after first import)
batches/      note strings, one file per batch
colab/        AnkiBuilder.ipynb — builds the .apkg into Google Drive
tools/        build_apkg.py — the builder (works locally and in Colab)
              dump_collection.py — inspect the local Anki collection safely
out/          local build output (git-ignored)
```

## Local build

```
pip install genanki
python tools/build_apkg.py            # writes out/anki-YYYY-MM-DD.apkg
```

## Inspecting the local collection

```
python tools/dump_collection.py --templates
```

Reads a copy of `%APPDATA%\Anki2\User 1\collection.anki2`, so it's safe while Anki is running.
