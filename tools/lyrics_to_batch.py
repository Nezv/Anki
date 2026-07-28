#!/usr/bin/env python3
"""Turn a Chinese song's lyrics into a `sentence-zh` batch file.

One lyric line becomes one note. Pinyin is generated automatically with
pypinyin (word-context aware, so 不 / 一 sandhi and heteronyms come out right).
Translations are left blank for you (or Claude) to fill in afterwards.

Usage:
    pip install pypinyin
    python tools/lyrics_to_batch.py lyrics.txt --title 富士山下 --artist 陈奕迅

    # then fill in the Translation: values, then generate audio:
    python tools/gen_audio.py batches/zh-fu-shi-shan-xia.txt

Input may be plain lyrics or an .lrc file — timestamps, blank lines and
bracketed annotations are stripped.
"""
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CJK = r"一-鿿㐀-䶿"
CJK_RE = re.compile(f"[{CJK}]")
RUN_RE = re.compile(f"[{CJK}]+|[^{CJK}]+")
LRC_TIMESTAMP_RE = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
ANNOTATION_RE = re.compile(r"[\[【(（][^\]】)）]*[\]】)）]")
SENTENCE_END = "。！？!?；;"


def sentence_pinyin(text):
    """Space-separated tone-marked pinyin, one syllable per hanzi.

    Non-hanzi characters produce no syllable, so the result lines up with the
    hanzi in order — which is what the card template's ruby renderer expects.
    """
    from pypinyin import Style, pinyin

    syllables = []
    for run in RUN_RE.findall(text):
        if CJK_RE.match(run[0]):
            syllables.extend(item[0] for item in pinyin(run, style=Style.TONE))
    return " ".join(syllables)


def clean_line(line):
    line = LRC_TIMESTAMP_RE.sub("", line)
    line = ANNOTATION_RE.sub("", line)
    # '|' is the batch-format separator, so it can never appear in a value.
    line = line.replace("|", "｜")
    return " ".join(line.split())


def split_long(line, max_len):
    """Break an over-long line after sentence-ending punctuation."""
    if max_len <= 0 or len(line) <= max_len:
        return [line]
    parts, current = [], ""
    for ch in line:
        current += ch
        if ch in SENTENCE_END and len(current) >= max_len // 2:
            parts.append(current)
            current = ""
    if current:
        parts.append(current)
    return [p.strip() for p in parts if p.strip()] or [line]


def read_lines(path, max_len, keep_dupes):
    seen = set()
    out = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = clean_line(raw)
        if not line or not CJK_RE.search(line):
            continue  # skip blanks, credits, pure-latin lines
        for part in split_long(line, max_len):
            if not keep_dupes and part in seen:
                continue  # choruses repeat; one card per distinct line
            seen.add(part)
            out.append(part)
    return out


def slugify(text):
    ascii_only = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return ascii_only or "song"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lyrics", help="lyrics .txt or .lrc file")
    ap.add_argument("--title", default="", help="song title, shown on the card back")
    ap.add_argument("--artist", default="", help="artist, shown on the card back")
    ap.add_argument("--deck", default=None, help="override the deck (default Chinese::Sentences)")
    ap.add_argument("--tags", default="", help="space-separated tags, e.g. 'song lyrics'")
    ap.add_argument("--out", default=None, help="output batch file (default batches/zh-<slug>.txt)")
    ap.add_argument("--max-len", type=int, default=0,
                    help="split lines longer than N chars on sentence punctuation (0 = never)")
    ap.add_argument("--keep-dupes", action="store_true",
                    help="keep repeated lines (choruses) instead of deduplicating")
    ap.add_argument("--no-pinyin", action="store_true", help="leave Pinyin blank")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    lines = read_lines(Path(args.lyrics), args.max_len, args.keep_dupes)
    if not lines:
        sys.exit(f"No Chinese lyric lines found in {args.lyrics}")

    source = " – ".join(p for p in (args.artist, args.title) if p).replace("|", "｜")
    slug = slugify(args.title) if args.title else Path(args.lyrics).stem
    out_path = Path(args.out) if args.out else REPO_ROOT / "batches" / f"zh-{slugify(slug)}.txt"

    tags = args.tags.split() if args.tags else ["song"]
    if args.title:
        tags.append(f"song::{slugify(args.title)}")

    header = ["#notetype: sentence-zh"]
    header.append(f"#deck: {args.deck}" if args.deck else "#deck: Chinese::Sentences")
    header.append(f"#tags: {' '.join(dict.fromkeys(tags))}")

    body = []
    for line in lines:
        parts = [f"Sentence:{line}"]
        parts.append(f"Pinyin:{'' if args.no_pinyin else sentence_pinyin(line)}")
        parts.append("Translation:")
        if source:
            parts.append(f"Source:{source}")
        body.append("|".join(parts))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(header + body) + "\n", encoding="utf-8")

    print(f"Wrote {out_path} ({len(body)} lines)")
    print("Next: fill in the Translation: values, then")
    print(f"      python tools/gen_audio.py {out_path}")


if __name__ == "__main__":
    main()
