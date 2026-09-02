"""
Batch Stage 4 runner.

Reads a Stage 2 manifest and runs the already-tested stage4_subtitles.py
once per successful clip. It uses the manifest's source_url + start_time +
end_time + output_path, so clips cannot be paired with the wrong YouTube URL
or wrong time range.

It does not modify Stage 1/2/3 or either Python environment.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate SRT even if it already exists.",
    )
    parser.add_argument(
        "--target-words",
        type=int,
        default=None,
        help="Kata per baris subtitle (diteruskan ke stage4_subtitles.py).",
    )
    parser.add_argument(
        "--lang-tags",
        default=None,
        help="Tag bahasa dipisah koma untuk initial_prompt WhisperX, mis. 'id,su' "
             "atau 'id,su,en'. Default 'id'. Diteruskan apa adanya ke "
             "stage4_subtitles.py — di sana tag HANYA merakit initial_prompt, "
             "parameter language= transkripsi TETAP 'id' (whisperx tidak punya model "
             "forced-alignment untuk 'su').",
    )
    args = parser.parse_args()

    # Normalisasi ringan di sini: daftar kosong / hanya koma JANGAN diteruskan ke
    # subprocess (Item 24 poin 2 — jangan pernah mengirim --lang-tags kosong).
    # Normalisasi tag yang sesungguhnya tetap di stage4_subtitles.parse_lang_tags().
    lang_tags = ",".join(
        t.strip() for t in (args.lang_tags or "").split(",") if t.strip()
    )

    manifest_path = Path(args.manifest).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    source_url = data["source_url"]
    clips = data.get("clips", [])
    stage4 = Path(__file__).with_name("stage4_subtitles.py")

    if not stage4.exists():
        raise FileNotFoundError(f"Missing Stage 4 script: {stage4}")

    print("=== CLIPPER STAGE 4 BATCH ===")
    print(f"Manifest: {manifest_path}")
    print(f"YouTube:  {source_url}")
    print(f"Clips:    {len(clips)}")
    print(f"Lang tags: {lang_tags or '(default: id)'}")
    print("Stage 3:  SKIPPED")
    print()

    failures = []
    completed = 0
    skipped = 0

    for clip in clips:
        if clip.get("status") != "success":
            print(f"[SKIP] clip {clip.get('clip_id')}: status={clip.get('status')}")
            skipped += 1
            continue

        video = Path(clip["output_path"])
        srt = video.with_suffix(".srt")

        print("=" * 72)
        print(f"CLIP {clip['clip_id']}: {clip.get('title', '')}")
        print(f"MP4:   {video}")
        print(f"Range: {clip['start_time']} -> {clip['end_time']}")
        print(f"SRT:   {srt}")

        if not video.exists():
            msg = f"MP4 not found: {video}"
            print(f"[FAIL] {msg}")
            failures.append((clip["clip_id"], msg))
            continue

        if srt.exists() and not args.force:
            print("[SKIP] SRT already exists. Use --force to regenerate.")
            skipped += 1
            continue

        cmd = [
            sys.executable,
            str(stage4),
            "--video",
            str(video),
            "--youtube-url",
            source_url,
            "--start",
            clip["start_time"],
            "--end",
            clip["end_time"],
        ]
        if args.target_words:
            cmd += ["--target-words", str(args.target_words)]
        # Diteruskan HANYA kalau tidak kosong: subprocess punya defaultnya sendiri
        # ("id"), dan mengirim string kosong akan membuat semua tag terbuang.
        if lang_tags:
            cmd += ["--lang-tags", lang_tags]

        result = subprocess.run(cmd)
        if result.returncode != 0:
            msg = f"Stage 4 exited with code {result.returncode}"
            print(f"[FAIL] {msg}")
            failures.append((clip["clip_id"], msg))
            continue

        if not srt.exists():
            msg = f"SRT was not created: {srt}"
            print(f"[FAIL] {msg}")
            failures.append((clip["clip_id"], msg))
            continue

        print(f"[OK] {srt}")
        completed += 1

    print()
    print("=" * 72)
    print("BATCH SUMMARY")
    print(f"Completed: {completed}")
    print(f"Skipped:   {skipped}")
    print(f"Failed:    {len(failures)}")

    if failures:
        for clip_id, reason in failures:
            print(f"  clip {clip_id}: {reason}")
        return 1

    print("STAGE 4 BATCH PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
