"""Clipper application entry point and orchestration skeleton.

Run the full pipeline or a single stage:

    python main.py run --url "https://youtu.be/..."
    python main.py stage1 --url "https://youtu.be/..."
    python main.py stage2
    python main.py stage3
    python main.py stage4
    python main.py stage5
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import typer

from config import settings
from utils import ensure_dirs, setup_logging

app = typer.Typer(
    name="clipper",
    help="YouTube-to-short-video pipeline.",
    no_args_is_help=True,
)


def _bootstrap() -> None:
    """Ensure runtime directories exist and logging is configured."""
    ensure_dirs()
    setup_logging()


@app.command()
def run(
    url: str = typer.Option(..., "--url", "-u", help="Source YouTube URL."),
    stage: int | None = typer.Option(None, "--stage", "-s", help="Run specific stage (1-4)."),
    preset: Path | None = typer.Option(None, "--preset", help="Path ke render_preset.json untuk Stage 5 (opsional)."),
    count: int | None = typer.Option(
        None, "--count", "-n",
        help="MAX klip: jumlah yang DIMINTA ke Gemini (TARGET, bukan jaminan)."),
    min_count: int | None = typer.Option(
        None, "--min-count",
        help="MIN klip: ambang PERINGATAN saja, BUKAN jaminan. Kalau hasil kurang dari "
             "nilai ini, pipeline TETAP LANJUT dengan peringatan berangka."),
    min_seconds: int | None = typer.Option(
        None, "--min-sec", help="Durasi klip minimal (detik)."),
    max_seconds: int | None = typer.Option(
        None, "--max-sec", help="Durasi klip maksimal (detik)."),
    target_words: int | None = typer.Option(
        None, "--target-words", help="Kata per baris subtitle di SRT (1 atau 3)."),
    lang_tags: str | None = typer.Option(
        None, "--lang-tags",
        help="Tag bahasa dipisah koma untuk initial_prompt WhisperX, mis. 'id,su' atau "
             "'id,su,en'. Default 'id'. HANYA memengaruhi initial_prompt: parameter "
             "language= transkripsi TETAP 'id' karena whisperx tidak punya model "
             "forced-alignment untuk 'su'."),
) -> None:
    """Run the full pipeline or a specific stage."""
    _bootstrap()

    # Keep explicit single-stage commands unchanged.
    if stage == 1:
        from stages import stage1_curate
        stage1_curate.run(url, target_count=count, min_count=min_count,
                          min_seconds=min_seconds, max_seconds=max_seconds)
        return

    if stage == 2:
        from stages import stage2_download
        stage2_download.run()
        return

    if stage == 3:
        from stages import stage3_render
        stage3_render.run()
        return

    if stage == 4:
        from stages import stage4_subtitles
        stage4_subtitles.run(lang_tags=lang_tags)
        return

    # Full pipeline:
    # Stage 1 -> Stage 2 -> SKIP Stage 3 -> Stage 4 -> Stage 5.
    from stages import stage1_curate, stage2_download

    print("\n=== CLIPPER FULL PIPELINE ===")
    print("Stage 1 -> Stage 2 -> SKIP Stage 3 -> Stage 4 WhisperX -> Stage 5\n")

    print(">>> STAGE 1: CURATION")
    stage1_curate.run(url, target_count=count, min_count=min_count,
                      min_seconds=min_seconds, max_seconds=max_seconds)

    print("\n>>> STAGE 2: DOWNLOAD")
    stage2_download.run()

    print("\n>>> STAGE 3: SKIPPED")

    # Extract the exact YouTube video ID so we never select another video's
    # manifest by accident.
    match = re.search(
        r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})",
        url,
    )
    if not match:
        raise RuntimeError(f"Could not extract YouTube video ID from: {url}")
    video_id = match.group(1)

    # Stage 2 manifests live at output/<creator>/<title>/manifest.json;
    # also check the legacy output/clips/<folder>/ location.
    manifest = None
    candidates: list[Path] = []
    for pattern in ("*/*/manifest.json", "*/manifest.json", "clips/*/manifest.json"):
        candidates.extend(settings.output_dir.glob(pattern))
    # Prefer the most recently written manifest for this video (new layout wins).
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("video_id") == video_id:
            manifest = candidate
            break

    if manifest is None:
        raise RuntimeError(
            f"Stage 2 manifest not found for YouTube video {video_id}."
        )

    print("\n>>> STAGE 4: WHISPERX SUBTITLES")
    print(f"Manifest: {manifest}")
    _stage4_batch(manifest, target_words=target_words, lang_tags=lang_tags)

    print("\n>>> STAGE 5: FINAL COMPOSITION")
    from stages import stage5_final
    stage5_final.run(manifest_path=manifest, preset_path=preset)

    print("\n=== FULL PIPELINE COMPLETE ===")
    print("Stage 1: DONE")
    print("Stage 2: DONE")
    print("Stage 3: SKIPPED")
    print("Stage 4: DONE")
    print("Stage 5: DONE")
    print("Output: final/<creator>/<title>/")


def _stage4_batch(
    manifest: Path,
    target_words: int | None = None,
    lang_tags: str | None = None,
) -> None:
    """Jalankan Stage 4 di venv WhisperX yang terpisah.

    Diambil dari `run()` supaya jalur Auto (full pipeline) dan jalur Manual
    (`continue-from`) memakai kode yang SAMA — kalau digandakan, salah satu jalur
    akan tertinggal saat ada perbaikan.
    """
    project_root = Path(__file__).resolve().parent
    whisperx_python = project_root / ".whisperx-venv" / "Scripts" / "python.exe"
    batch_script = project_root / "stages" / "stage4_batch.py"

    if not whisperx_python.exists():
        raise RuntimeError(f"WhisperX Python not found: {whisperx_python}")
    if not batch_script.exists():
        raise RuntimeError(f"Stage 4 batch script not found: {batch_script}")

    cmd = [str(whisperx_python), str(batch_script), "--manifest", str(manifest)]
    if target_words:
        cmd += ["--target-words", str(int(target_words))]
    # Tag bahasa (Item 24). Dibersihkan dulu: daftar kosong / hanya koma TIDAK
    # diteruskan — stage4_subtitles punya default "id" sendiri, dan mengirim nilai
    # kosong akan membuat semua tag terbuang tanpa jejak di log.
    tags = ",".join(t.strip() for t in (lang_tags or "").split(",") if t.strip())
    if tags:
        cmd += ["--lang-tags", tags]

    result = subprocess.run(cmd, cwd=str(project_root))
    if result.returncode != 0:
        raise RuntimeError(f"Stage 4 batch failed with exit code {result.returncode}.")


@app.command()
def stage1(
    url: str = typer.Option(..., "--url", "-u", help="Source YouTube URL."),
    count: int | None = typer.Option(
        None, "--count", "-n",
        help="MAX klip: jumlah yang DIMINTA ke Gemini. Ini TARGET, bukan jaminan: "
             "Gemini bisa mengembalikan lebih sedikit dan kandidat bertumpuk dibuang "
             "validator.",
    ),
    min_count: int | None = typer.Option(
        None, "--min-count",
        help="MIN klip: ambang PERINGATAN saja, BUKAN jaminan. Hasil kurang dari "
             "nilai ini TIDAK menghentikan pipeline dan TIDAK memicu retry otomatis; "
             "hanya memunculkan peringatan berangka (dapat N, minimal diminta M).",
    ),
    min_seconds: int | None = typer.Option(
        None, "--min-sec",
        help="Durasi klip minimal (detik). Penentu utama berapa banyak klip yang "
             "MUNGKIN dihasilkan: maks = durasi video / nilai ini.",
    ),
    max_seconds: int | None = typer.Option(
        None, "--max-sec", help="Durasi klip maksimal (detik)."),
) -> None:
    """Run Stage 1: curate clips from a YouTube video."""
    _bootstrap()
    from stages import stage1_curate

    stage1_curate.run(
        url,
        target_count=count,
        min_count=min_count,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
    )


@app.command("continue-from")
def continue_from(
    curation: Path = typer.Option(
        ..., "--curation", "-c",
        help="Path file kurasi Stage 1 (output/<creator>/<judul>/<video_id>.json) "
             "yang sudah direview: klip terpilih + headline.",
    ),
    preset: Path | None = typer.Option(
        None, "--preset", help="Preset Stage 5 (opsional; default = preset aktif)."),
    target_words: int | None = typer.Option(
        None, "--target-words",
        help="Kata per baris subtitle di SRT (1 atau 3). Default 3. Stage 5 bisa "
             "memecah lebih halus saat render, tapi TIDAK bisa menggabungkan kembali.",
    ),
    lang_tags: str | None = typer.Option(
        None, "--lang-tags",
        help="Tag bahasa dipisah koma untuk initial_prompt WhisperX, mis. 'id,su' atau "
             "'id,su,en'. Default 'id'. HANYA memengaruhi initial_prompt: parameter "
             "language= transkripsi TETAP 'id' karena whisperx tidak punya model "
             "forced-alignment untuk 'su'.",
    ),
    force: bool = typer.Option(False, "--force", help="Ulang walau hasil sudah ada."),
) -> None:
    """Lanjutkan dari file kurasi yang sudah direview: Download -> Subtitle -> Render.

    Ini separuh kedua dari alur manual. Stage 1 sudah selesai (dan sudah direview user),
    jadi TIDAK dipanggil lagi di sini — memanggilnya ulang akan menimpa keputusan review
    dan membuang satu request Gemini.
    """
    _bootstrap()
    from stages import stage2_download

    curation = Path(curation)
    if not curation.exists():
        raise RuntimeError(f"File kurasi tidak ditemukan: {curation}")

    print("\n=== LANJUT DARI HASIL REVIEW ===")
    print(f"Kurasi: {curation}")

    print("\n>>> STAGE 2: DOWNLOAD")
    stage2_download.run(manifest_path=curation, force=force)

    # Manifest Stage 2 ditulis di folder yang sama dengan file kurasi. Dicari lewat
    # jalur itu, BUKAN dengan "manifest terbaru di output/", supaya dua video yang
    # diproses berdekatan tidak saling tertukar.
    manifest = curation.parent / "manifest.json"
    if not manifest.exists():
        raise RuntimeError(
            f"Manifest Stage 2 tidak ditemukan: {manifest}\n"
            "Stage 2 mungkin tidak mengunduh apa pun (semua klip tidak dipilih?)."
        )

    print("\n>>> STAGE 4: WHISPERX SUBTITLES")
    print(f"Manifest: {manifest}")
    _stage4_batch(manifest, target_words=target_words, lang_tags=lang_tags)

    print("\n>>> STAGE 5: FINAL COMPOSITION")
    from stages import stage5_final
    stage5_final.run(manifest_path=manifest, preset_path=preset, force=force)

    print("\n=== LANJUTAN SELESAI ===")
    print("Stage 2: DONE")
    print("Stage 4: DONE")
    print("Stage 5: DONE")
    print("Output: final/<creator>/<title>/")


@app.command()
def stage2(
    video_id: str | None = typer.Option(None, "--video-id", help="YouTube video ID. If not provided, uses latest manifest."),
    manifest_path: Path | None = typer.Option(None, "--manifest-path", help="Explicit path to curation manifest JSON."),
    force: bool = typer.Option(False, "--force", help="Force re-download even if clips already exist."),
) -> None:
    """Run Stage 2: download curated clip ranges."""
    _bootstrap()
    from stages import stage2_download

    # If video_id is provided, search the curation manifest under the new
    # output/<creator>/<title>/ layout, then legacy locations.
    resolved_manifest = manifest_path
    if resolved_manifest is None and video_id:
        candidates = [
            *settings.output_dir.glob(f"*/*/{video_id}.json"),
            *settings.output_dir.glob(f"creator/*/{video_id}.json"),
            *settings.output_dir.glob(f"curation/{video_id}.json"),
        ]
        if candidates:
            resolved_manifest = max(candidates, key=lambda p: p.stat().st_mtime)

    stage2_download.run(manifest_path=resolved_manifest, force=force)


@app.command()
def stage3(
    video_id: str | None = typer.Option(None, "--video-id", help="YouTube video ID. If not provided, uses latest manifest."),
    manifest_path: Path | None = typer.Option(None, "--manifest-path", help="Explicit path to Stage 2 manifest JSON."),
    force: bool = typer.Option(False, "--force", help="Force re-render even if clips already exist."),
) -> None:
    """Run Stage 3: render 9:16 vertical clips."""
    _bootstrap()
    from stages import stage3_render

    # If video_id is provided, search for the matching Stage 2 manifest
    resolved_manifest = manifest_path
    if resolved_manifest is None and video_id:
        resolved_manifest = stage3_render.find_manifest_by_video_id(video_id)

    stage3_render.run(manifest_path=resolved_manifest, force=force)


@app.command()
def stage4(
    video_id: str | None = typer.Option(None, "--video-id", help="YouTube video ID. If not provided, uses latest manifest."),
    manifest_path: Path | None = typer.Option(None, "--manifest-path", help="Explicit path to Stage 2 manifest JSON."),
    force: bool = typer.Option(False, "--force", help="Force re-transcription even if cache exists."),
    lang_tags: str | None = typer.Option(
        None, "--lang-tags",
        help="Tag bahasa dipisah koma untuk initial_prompt WhisperX, mis. 'id,su'. "
             "Default 'id'. HANYA memengaruhi initial_prompt: parameter language= "
             "transkripsi TETAP 'id'.",
    ),
) -> None:
    """Run Stage 4: generate smart subtitles."""
    _bootstrap()
    from stages import stage4_subtitles

    # If video_id is provided, search for the matching Stage 2 manifest
    resolved_manifest = manifest_path
    if resolved_manifest is None and video_id:
        resolved_manifest = stage4_subtitles.find_stage2_manifest(video_id)

    stage4_subtitles.run(
        manifest_path=resolved_manifest, force=force, lang_tags=lang_tags
    )


@app.command()
def stage5(
    manifest_path: Path | None = typer.Option(
        None,
        "--manifest-path",
        help="Explicit path to Stage 2 manifest JSON. If omitted, uses newest manifest.",
    ),
    frame_path: Path | None = typer.Option(
        None,
        "--frame",
        help="Stage 5 frame PNG. Defaults to assets/frame.png.",
    ),
    preset: Path | None = typer.Option(
        None,
        "--preset",
        help="Path ke render_preset.json (opsional; default = perilaku lama).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force re-render existing final clips.",
    ),
) -> None:
    """Run Stage 5: final portrait composition with burned subtitles."""
    _bootstrap()
    from stages import stage5_final

    stage5_final.run(
        manifest_path=manifest_path,
        frame_path=frame_path,
        force=force,
        preset_path=preset,
    )


@app.command()
def doctor() -> None:
    """Validate configuration and required system dependencies."""
    _bootstrap()
    from utils import check_ffmpeg

    ok = True

    if settings.gemini_api_key:
        print("[ok] GEMINI_API_KEY is set.")
    else:
        print("[warn] GEMINI_API_KEY is not set (Stage 1 will fail).")

    if check_ffmpeg():
        print("[ok] ffmpeg found on PATH.")
    else:
        print("[fail] ffmpeg not found on PATH.")
        ok = False

    for directory in settings.runtime_dirs:
        print(f"[ok] directory ready: {directory}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    app()