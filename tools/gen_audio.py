#!/usr/bin/env python3
"""Generate sentence audio for `sentence-zh` batch files and patch it back in.

Reads batch files, synthesises every `Sentence:` value that doesn't have audio
yet, writes the clips into media/, and rewrites each line with the filename in
an `Audio:` key. build_apkg.py turns that into a real `[sound:...]` Anki field
and packs the file into the .apkg.

    python tools/gen_audio.py batches/zh-my-song.txt --engine cosyvoice

Filenames are content-addressed (`zh-<sha1 of sentence>.mp3`), so re-running is
idempotent, and re-importing replaces the clip on the existing note instead of
duplicating it.

Engines (`--engine`):
    cosyvoice  CosyVoice 2 / Fun-CosyVoice3 — Apache-2.0, Chinese-first, best
               quality. Needs a GPU and the CosyVoice repo on PYTHONPATH.
               Voice comes from a reference clip: --ref-audio / --ref-text.
    kokoro     Kokoro-82M — Apache-2.0, runs on CPU. pip install kokoro
               "misaki[zh]"; voices zf_xiaobei, zf_xiaoni, zm_yunjian, ...
               For the Chinese-specific model, add
               --repo-id hexgrad/Kokoro-82M-v1.1-zh --voice zf_001
    melotts    MeloTTS — MIT, CPU real-time, handles zh/en code-switching well.
    edge       Microsoft Edge voices via edge-tts. NOT open source (a free
               cloud endpoint) — offered only as a zero-setup fallback.

Add a new engine by writing a `synth_*` function and registering it in ENGINES.
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEDIA = REPO_ROOT / "media"
SAMPLE_RATE = 24000


# --------------------------------------------------------------------------
# batch file plumbing
# --------------------------------------------------------------------------

def parse_line(line):
    """`a:1|b:2` -> {'a': '1', 'b': '2'}, preserving order."""
    fields = {}
    for segment in line.split("|"):
        key, sep, value = segment.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def set_key(line, key, value):
    """Replace `key:...` in a pipe-string, appending it if it isn't there."""
    pattern = rf"(^|\|)\s*{re.escape(key)}\s*:[^|]*"
    if re.search(pattern, line):
        return re.sub(pattern, lambda m: f"{m.group(1)}{key}:{value}", line, count=1)
    return f"{line}|{key}:{value}"


def audio_name(sentence, ext):
    digest = hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:12]
    return f"zh-{digest}.{ext}"


# --------------------------------------------------------------------------
# audio helpers
# --------------------------------------------------------------------------

def have_ffmpeg():
    return shutil.which("ffmpeg") is not None


def require(module, install_hint):
    """Import a backend's dependency, or explain how to install it."""
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError:
        sys.exit(f"This engine needs the '{module}' package:\n\n    pip install {install_hint}\n")


def write_wav(path, samples, sample_rate=SAMPLE_RATE):
    """Write mono samples (numpy or torch, float or int16) to a wav."""
    import wave

    import numpy as np

    data = np.asarray(samples).squeeze()
    if data.dtype != np.int16:
        peak = float(np.max(np.abs(data))) or 1.0
        data = (data / peak * 0.95 * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(data.astype("<i2").tobytes())


def to_mp3(wav_path, mp3_path):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-ac", "1", "-ar", "24000", "-b:a", "48k", str(mp3_path)],
        check=True,
    )


# --------------------------------------------------------------------------
# engines — each returns a callable synth(text, out_path_without_ext) -> Path
# --------------------------------------------------------------------------

def engine_cosyvoice(args):
    """CosyVoice 2 zero-shot cloning. Requires the CosyVoice repo on PYTHONPATH."""
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice2
        from cosyvoice.utils.file_utils import load_wav
    except ImportError:
        sys.exit("CosyVoice isn't importable. It installs from source, not pip:\n\n"
                 "    git clone --recursive https://github.com/FunAudioLLM/CosyVoice\n"
                 "    pip install -r CosyVoice/requirements.txt\n"
                 "    set PYTHONPATH=...\\CosyVoice;...\\CosyVoice\\third_party\\Matcha-TTS\n\n"
                 "Easier: run colab/LyricsAudio.ipynb, which does all of this on a free GPU.\n")

    if not args.ref_audio:
        sys.exit("--engine cosyvoice needs --ref-audio (a 3-10s reference clip) "
                 "and --ref-text (what is said in it)")
    model = CosyVoice2(args.model_dir, load_jit=False, load_trt=False, fp16=args.fp16)
    prompt = load_wav(args.ref_audio, 16000)

    def synth(text, stem):
        chunks = [out["tts_speech"].numpy().flatten()
                  for out in model.inference_zero_shot(text, args.ref_text, prompt, stream=False)]
        import numpy as np
        wav = stem.with_suffix(".wav")
        write_wav(wav, np.concatenate(chunks), model.sample_rate)
        return wav

    return synth


def engine_kokoro(args):
    kokoro = require("kokoro", 'kokoro "misaki[zh]"')
    require("misaki.zh", 'kokoro "misaki[zh]"')

    # Passing repo_id explicitly also suppresses kokoro's "defaulting repo_id" warning.
    # The zf_*/zm_* named voices (zf_xiaobei, zm_yunjian, ...) live in Kokoro-82M;
    # the Chinese-specific Kokoro-82M-v1.1-zh ships numbered voices (zf_001, zm_009, ...).
    pipeline = kokoro.KPipeline(lang_code="z", repo_id=args.repo_id)  # 'z' = Mandarin
    voice = args.voice or ("zf_001" if args.repo_id.endswith("-zh") else "zf_xiaobei")

    def synth(text, stem):
        import numpy as np

        chunks = []
        for result in pipeline(text, voice=voice, speed=args.speed):
            # .audio is a property over .output and is None when synthesis produced
            # nothing; older kokoro yielded a plain (graphemes, phonemes, audio) tuple.
            audio = getattr(result, "audio", None)
            if audio is None and not hasattr(result, "output"):
                audio = result[2]
            if audio is not None:
                chunks.append(np.asarray(audio).squeeze())
        if not chunks:
            sys.exit(f"kokoro produced no audio for: {text}")
        wav = stem.with_suffix(".wav")
        write_wav(wav, np.concatenate(chunks), 24000)
        return wav

    return synth


def engine_melotts(args):
    melo = require("melo.api", "git+https://github.com/myshell-ai/MeloTTS.git")
    TTS = melo.TTS

    model = TTS(language="ZH", device=args.device)
    speaker_id = model.hps.data.spk2id["ZH"]

    def synth(text, stem):
        wav = stem.with_suffix(".wav")
        model.tts_to_file(text, speaker_id, str(wav), speed=args.speed)
        return wav

    return synth


def engine_edge(args):
    import asyncio

    edge_tts = require("edge_tts", "edge-tts")

    voice = args.voice or "zh-CN-XiaoxiaoNeural"

    def synth(text, stem):
        mp3 = stem.with_suffix(".mp3")

        async def run():
            rate = f"{int((args.speed - 1) * 100):+d}%"
            await edge_tts.Communicate(text, voice, rate=rate).save(str(mp3))

        asyncio.run(run())
        return mp3

    return synth


ENGINES = {
    "cosyvoice": engine_cosyvoice,
    "kokoro": engine_kokoro,
    "melotts": engine_melotts,
    "edge": engine_edge,
}


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batches", nargs="+", help="batch file(s) to process")
    ap.add_argument("--engine", default="cosyvoice", choices=sorted(ENGINES))
    ap.add_argument("--media", default=str(DEFAULT_MEDIA), help="where clips are written")
    ap.add_argument("--voice", default=None, help="engine-specific voice id")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--device", default="cpu", help="melotts: cpu / cuda / auto")
    ap.add_argument("--repo-id", default="hexgrad/Kokoro-82M",
                    help="kokoro: model repo. Use hexgrad/Kokoro-82M-v1.1-zh (with a "
                         "numbered --voice like zf_001) for the Chinese-specific model")
    ap.add_argument("--model-dir", default="pretrained_models/CosyVoice2-0.5B",
                    help="cosyvoice: local model directory")
    ap.add_argument("--ref-audio", default=None, help="cosyvoice: reference wav to clone")
    ap.add_argument("--ref-text", default="", help="cosyvoice: transcript of the reference wav")
    ap.add_argument("--fp16", action="store_true", help="cosyvoice: half precision")
    ap.add_argument("--force", action="store_true", help="regenerate clips that already exist")
    ap.add_argument("--dry-run", action="store_true", help="show what would be generated")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    media_dir = Path(args.media)
    media_dir.mkdir(parents=True, exist_ok=True)
    ext = "mp3" if (have_ffmpeg() or args.engine == "edge") else "wav"
    if ext == "wav":
        print("ffmpeg not found — writing .wav (Anki plays those fine, they're just bigger)")

    # Collect the work first so --dry-run can report it without loading a model.
    jobs = []  # (batch_path, line_index, sentence, filename)
    files = {}
    for batch in args.batches:
        path = Path(batch)
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        files[path] = lines
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            sentence = parse_line(stripped).get("Sentence", "")
            if not sentence:
                continue
            jobs.append((path, i, sentence, audio_name(sentence, ext)))

    if not jobs:
        sys.exit("No 'Sentence:' lines found in the given batch files.")

    todo = [j for j in jobs if args.force or not (media_dir / j[3]).is_file()]
    print(f"{len(jobs)} sentence(s); {len(todo)} need audio")
    if args.dry_run:
        for _, _, sentence, filename in todo:
            print(f"  {filename}  {sentence}")
        return

    if todo:
        synth = ENGINES[args.engine](args)
        with tempfile.TemporaryDirectory() as tmp:
            stem = Path(tmp) / "clip"
            for n, (_, _, sentence, filename) in enumerate(todo, 1):
                target = media_dir / filename
                print(f"[{n}/{len(todo)}] {sentence}")
                produced = synth(sentence, stem)
                if produced.suffix == ".wav" and ext == "mp3":
                    to_mp3(produced, target)
                else:
                    shutil.move(str(produced), target)
                for leftover in Path(tmp).glob("clip.*"):
                    leftover.unlink()

    # Patch Audio: into every line, including ones whose clip already existed.
    for path, lines in files.items():
        for _, i, _, filename in [j for j in jobs if j[0] == path]:
            lines[i] = set_key(lines[i].rstrip(), "Audio", filename)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Updated {path}")

    print(f"Audio in {media_dir}. Now run: python tools/build_apkg.py")


if __name__ == "__main__":
    main()
