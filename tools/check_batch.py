#!/usr/bin/env python3
"""Validate batch files before building.

The card templates line pinyin up with hanzi positionally and read the
Words / WordPinyin / WordMeanings lists in parallel. When those drift out of
sync nothing errors — the card just renders wrong annotations on the wrong
characters — so it's worth checking mechanically.

Usage:
    python tools/check_batch.py                    # every file in batches/
    python tools/check_batch.py batches/zh-*.txt

Exits non-zero if any problem is found.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

# Field -> the field its comma-separated entries must line up with.
PARALLEL_LISTS = {
    "hanzi": [("Words", "WordPinyin", "WordMeanings")],
    "sentence-zh": [("Words", "WordPinyin", "WordMeanings")],
    "vocab-ja": [],
    "kanji-ja": [("WordExamples", "WordFurigana", "WordTranslations")],
    "sentence-ja": [("Words", "WordTranslations")],
}

# Field holding text -> field holding one annotation per CJK character.
ALIGNED = {
    "hanzi": [("Sentence", "SentencePinyin")],
    "sentence-zh": [("Sentence", "Pinyin")],
}


def parse_line(line):
    fields = {}
    for segment in line.split("|"):
        key, sep, value = segment.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def check_file(path, registry, problems):
    notetype = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*notetype\s*:\s*(.*)", line)
            if m:
                notetype = m.group(1).strip()
            continue

        where = f"{path.name}:{lineno}"
        if notetype is None:
            problems.append(f"{where}: note line before '#notetype:' directive")
            continue

        fields = parse_line(line)
        key = registry["notetypes"].get(notetype, {}).get("guid_key")
        if key and not fields.get(key):
            problems.append(f"{where}: missing or empty '{key}:' (it's the note's identity)")

        # One pinyin syllable per hanzi, or the ruby lands on the wrong character.
        for text_field, annotation_field in ALIGNED.get(notetype, []):
            text, annotation = fields.get(text_field), fields.get(annotation_field)
            if not text or not annotation:
                continue
            hanzi = len(CJK_RE.findall(text))
            syllables = len(annotation.split())
            if hanzi != syllables:
                problems.append(
                    f"{where}: {hanzi} hanzi in {text_field} but {syllables} syllables in "
                    f"{annotation_field} — annotations will be shifted"
                )

        # Parallel comma-separated lists must be the same length.
        for group in PARALLEL_LISTS.get(notetype, []):
            present = {f: fields[f] for f in group if fields.get(f)}
            lengths = {f: len(v.split(",")) for f, v in present.items()}
            if len(set(lengths.values())) > 1:
                detail = ", ".join(f"{f}={n}" for f, n in lengths.items())
                problems.append(f"{where}: parallel lists have different lengths ({detail})")

            # Each word's pinyin needs one syllable per hanzi too.
            words_field, pinyin_field = group[0], group[1]
            if "Pinyin" in pinyin_field and words_field in present and pinyin_field in present:
                words = present[words_field].split(",")
                pinyins = present[pinyin_field].split(",")
                for word, pinyin in zip(words, pinyins):
                    hanzi = len(CJK_RE.findall(word))
                    syllables = len(pinyin.split())
                    if hanzi and hanzi != syllables:
                        problems.append(
                            f"{where}: '{word.strip()}' has {hanzi} hanzi but "
                            f"{syllables} syllables ('{pinyin.strip()}')"
                        )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batches", nargs="*", help="batch files (default: all of batches/)")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with open(REPO_ROOT / "notetypes" / "models.json", encoding="utf-8") as f:
        registry = json.load(f)

    paths = [Path(p) for p in args.batches] or sorted((REPO_ROOT / "batches").glob("*.txt"))
    if not paths:
        sys.exit("No batch files to check.")

    problems = []
    for path in paths:
        check_file(path, registry, problems)

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        sys.exit(f"\n{len(problems)} problem(s) in {len(paths)} file(s)")
    print(f"OK — {len(paths)} file(s) checked, no problems")


if __name__ == "__main__":
    main()
