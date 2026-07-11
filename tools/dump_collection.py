#!/usr/bin/env python3
"""Inspect the local Anki collection: note types, fields, templates, decks.

Reads a COPY of collection.anki2 (never the live file), so it's safe to run
while Anki is open.

Usage:
    python tools/dump_collection.py [--profile "User 1"] [--templates]
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def parse_pb(data):
    """Minimal protobuf reader: {field_no: [values]}."""
    out, i = {}, 0
    while i < len(data):
        tag = 0
        shift = 0
        while True:
            b = data[i]; i += 1
            tag |= (b & 0x7F) << shift; shift += 7
            if not b & 0x80:
                break
        fno, wtype = tag >> 3, tag & 7
        if wtype == 0:
            v = 0
            shift = 0
            while True:
                b = data[i]; i += 1
                v |= (b & 0x7F) << shift; shift += 7
                if not b & 0x80:
                    break
        elif wtype == 2:
            ln = 0
            shift = 0
            while True:
                b = data[i]; i += 1
                ln |= (b & 0x7F) << shift; shift += 7
                if not b & 0x80:
                    break
            v = data[i:i + ln]; i += ln
        elif wtype == 5:
            v = data[i:i + 4]; i += 4
        elif wtype == 1:
            v = data[i:i + 8]; i += 8
        else:
            break
        out.setdefault(fno, []).append(v)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="User 1", help="Anki profile name")
    ap.add_argument("--templates", action="store_true", help="also print template HTML/CSS")
    args = ap.parse_args()

    src = Path(os.environ["APPDATA"]) / "Anki2" / args.profile / "collection.anki2"
    if not src.exists():
        sys.exit(f"Not found: {src}")

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "collection.anki2"
        shutil.copy(src, copy)
        db = sqlite3.connect(copy)
        db.create_collation("unicase", lambda a, b: 0)

        print("=== NOTE TYPES ===")
        for ntid, name in db.execute("SELECT id, name FROM notetypes").fetchall():
            count = db.execute("SELECT count(*) FROM notes WHERE mid=?", (ntid,)).fetchone()[0]
            fields = [r[0] for r in db.execute(
                "SELECT name FROM fields WHERE ntid=? ORDER BY ord", (ntid,)).fetchall()]
            print(f"\n{name}  (id={ntid}, notes={count})")
            print(f"  fields: {fields}")
            if args.templates:
                (config,) = db.execute(
                    "SELECT config FROM notetypes WHERE id=?", (ntid,)).fetchone()
                css = parse_pb(config).get(3, [b""])[0].decode("utf8", "replace")
                print(f"  --- css ---\n{css}")
                for tname, tconfig in db.execute(
                        "SELECT name, config FROM templates WHERE ntid=? ORDER BY ord",
                        (ntid,)).fetchall():
                    tpb = parse_pb(tconfig)
                    print(f"  --- {tname} front ---")
                    print(tpb.get(1, [b""])[0].decode("utf8", "replace"))
                    print(f"  --- {tname} back ---")
                    print(tpb.get(2, [b""])[0].decode("utf8", "replace"))

        print("\n=== DECKS ===")
        for did, name in db.execute("SELECT id, name FROM decks").fetchall():
            count = db.execute("SELECT count(*) FROM cards WHERE did=?", (did,)).fetchone()[0]
            print(f"  {name.replace(chr(31), '::')}  (id={did}, cards={count})")


if __name__ == "__main__":
    main()
