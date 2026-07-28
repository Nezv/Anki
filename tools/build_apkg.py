#!/usr/bin/env python3
"""Build an .apkg from the batch files in batches/.

Usage:
    python tools/build_apkg.py [--out OUTPUT_DIR] [--batches BATCH_DIR]

Batch file format (batches/*.txt, UTF-8):
    #notetype: hanzi          <- key from notetypes/models.json (required)
    #deck: 汉语               <- optional, defaults to the notetype's default_deck
    #tags: hsk1 chapter-03    <- optional, space-separated, applied to notes below
    Hanzi:不|Pinyin:bù|Meaning:not|...
    Hanzi:是|Pinyin:shì|Meaning:is|...

Each non-comment line is one note: the whole line becomes the single
`Content` field, parsed by JavaScript in the card template. Directives may
appear mid-file and apply to the lines that follow.

Note GUIDs are derived from the notetype + its guid_key value (e.g. the
Hanzi character), so re-importing an .apkg UPDATES existing notes instead
of creating duplicates.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import genanki

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTETYPES_DIR = REPO_ROOT / "notetypes"


def load_registry():
    with open(NOTETYPES_DIR / "models.json", encoding="utf-8") as f:
        return json.load(f)


def build_model(slug, spec):
    d = NOTETYPES_DIR / slug
    return genanki.Model(
        spec["model_id"],
        spec["name"],
        fields=[{"name": name} for name in spec.get("fields", ["Content"])],
        templates=[
            {
                "name": "Card 1",
                "qfmt": (d / "front.html").read_text(encoding="utf-8"),
                "afmt": (d / "back.html").read_text(encoding="utf-8"),
            }
        ],
        css=(d / "style.css").read_text(encoding="utf-8"),
    )


def extract_key(content, guid_key):
    """Pull the guid_key value (e.g. 'Hanzi:不' -> '不') out of a note line."""
    m = re.search(rf"(?:^|\|)\s*{re.escape(guid_key)}\s*:\s*([^|]*)", content)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return content  # fall back to the whole line


def split_media_fields(content, spec):
    """Pull media keys out of the pipe-string into their own Anki fields.

    A notetype with `media_fields: {"Audio": "Audio"}` turns
    `Sentence:我爱你|Audio:zh-ab12.mp3` into
    Content=`Sentence:我爱你`, Audio=`[sound:zh-ab12.mp3]`.

    Returns (content_without_media_segments, {field_name: value}, [filenames]).
    """
    media_fields = spec.get("media_fields", {})
    if not media_fields:
        return content, {}, []

    values, filenames = {}, []
    for field_name, key in media_fields.items():
        pattern = rf"(?:^|\|)\s*{re.escape(key)}\s*:\s*([^|]*)"
        m = re.search(pattern, content)
        filename = m.group(1).strip() if m else ""
        if m:
            # Drop the segment (and its leading separator) from Content.
            content = (content[: m.start()] + content[m.end() :]).strip("|").strip()
        values[field_name] = f"[sound:{filename}]" if filename else ""
        if filename:
            filenames.append(filename)
    return content, values, filenames


class ContentNote(genanki.Note):
    def __init__(self, model, fields, guid_seed, tags):
        super().__init__(model=model, fields=fields, tags=tags)
        self._guid_seed = guid_seed

    @property
    def guid(self):
        return genanki.guid_for(self._guid_seed)


def parse_batches(batch_dir, registry):
    """Yield (deck_name, notetype_slug, content, tags) per note line."""
    files = sorted(batch_dir.glob("*.txt"))
    if not files:
        sys.exit(f"No .txt batch files found in {batch_dir}")
    for path in files:
        notetype = None
        deck = None
        tags = []
        for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                m = re.match(r"#\s*(\w+)\s*:\s*(.*)", line)
                if m:
                    key, value = m.group(1).lower(), m.group(2).strip()
                    if key == "notetype":
                        if value not in registry["notetypes"]:
                            sys.exit(f"{path.name}:{lineno}: unknown notetype '{value}' "
                                     f"(known: {', '.join(registry['notetypes'])})")
                        notetype = value
                        deck = deck or registry["notetypes"][value]["default_deck"]
                    elif key == "deck":
                        deck = value
                    elif key == "tags":
                        tags = value.split()
                continue
            if notetype is None:
                sys.exit(f"{path.name}:{lineno}: note line before '#notetype:' directive")
            if ":" not in line or "|" not in line:
                print(f"WARNING {path.name}:{lineno}: line doesn't look like key:value|key:value, "
                      f"including it anyway", file=sys.stderr)
            yield deck, notetype, line, list(tags)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO_ROOT / "out"), help="output directory")
    ap.add_argument("--batches", default=str(REPO_ROOT / "batches"), help="batch files directory")
    ap.add_argument("--media", default=str(REPO_ROOT / "media"),
                    help="directory holding audio referenced by media fields")
    args = ap.parse_args()

    registry = load_registry()
    media_dir = Path(args.media)
    models = {}
    decks = {}
    counts = {}
    media_files = []
    missing_media = []

    for deck_name, slug, content, tags in parse_batches(Path(args.batches), registry):
        if slug not in models:
            models[slug] = build_model(slug, registry["notetypes"][slug])
        if deck_name not in decks:
            deck_id = registry["decks"].get(deck_name) or abs(hash(deck_name)) % (10**13)
            decks[deck_name] = genanki.Deck(deck_id, deck_name)
        spec = registry["notetypes"][slug]
        guid_seed = f"{spec['name']}\x1f{extract_key(content, spec['guid_key'])}"

        content, media_values, filenames = split_media_fields(content, spec)
        for filename in filenames:
            path = media_dir / filename
            if path.is_file():
                media_files.append(str(path))
            else:
                missing_media.append(filename)

        fields = [content] + [media_values.get(name, "")
                              for name in spec.get("fields", ["Content"])[1:]]
        decks[deck_name].add_note(ContentNote(models[slug], fields, guid_seed, tags))
        counts[deck_name] = counts.get(deck_name, 0) + 1

    if not decks:
        sys.exit("No notes found in any batch file.")

    if missing_media:
        print(f"WARNING: {len(missing_media)} media file(s) missing from {media_dir}; "
              f"those cards will have no audio:", file=sys.stderr)
        for filename in missing_media[:10]:
            print(f"  {filename}", file=sys.stderr)
        if len(missing_media) > 10:
            print(f"  ... and {len(missing_media) - 10} more", file=sys.stderr)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.date.today().strftime("%Y-%m-%d")
    out_file = out_dir / f"anki-{stamp}.apkg"
    existed = out_file.is_file()
    package = genanki.Package(list(decks.values()))
    package.media_files = sorted(set(media_files))
    package.write_to_file(str(out_file))

    # The filename is date-stamped, so rebuilding on the same day replaces
    # yesterday's-style clutter rather than piling up — say so, since an
    # unchanged filename otherwise looks like nothing happened.
    size_kb = out_file.stat().st_size / 1024
    verb = "Replaced" if existed else "Wrote"
    print(f"{verb} {out_file} ({size_kb:,.0f} KB)")
    for deck_name, n in counts.items():
        print(f"  {deck_name}: {n} notes")
    if package.media_files:
        print(f"  media: {len(package.media_files)} file(s)")


if __name__ == "__main__":
    main()
