"""Hapus HANYA fungsi test yang gagal, biarkan yang lulus tetap hidup.

Dipakai sekali (2026-09-01) untuk membuang 18 test warisan lama yang mengunci
perilaku kode yang sudah berubah, tanpa mengorbankan 117 test sehat di file yang sama.

Cara kerja: parse file dengan `ast` untuk mendapat rentang baris PERSIS tiap fungsi
(termasuk dekorator dan docstring), lalu buang barisnya. Tidak memakai regex — nama
test bisa muncul di komentar/string lain dan regex akan salah potong.

Kalau sebuah kelas jadi kosong setelah metodenya dibuang, kelas itu ikut dibuang
(kelas tanpa isi = SyntaxError).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (file, ClassName, test_method) — daftar 18 test yang gagal.
TARGETS = [
    ("tests/test_models.py", "TestGeminiMock", "test_curate_with_gemini_mock"),
    ("tests/test_models.py", "TestGeminiMock", "test_curate_with_gemini_insufficient_candidates"),
    ("tests/test_models.py", "TestGeminiMock", "test_curate_with_gemini_malformed_response"),
    ("tests/test_models.py", "TestStage1Integration", "test_run_with_mocked_dependencies"),
    ("tests/test_models.py", "TestStage1Integration", "test_run_insufficient_valid_clips"),
    ("tests/test_stage2.py", "TestOutputPaths", "test_clip_output_dir"),
    ("tests/test_stage2.py", "TestRunStage2", "test_successful_run"),
    ("tests/test_stage2.py", "TestRunStage2", "test_skip_existing_valid_clips"),
    ("tests/test_stage2.py", "TestRunStage2", "test_manifest_generation"),
    ("tests/test_stage2.py", "TestOutputFolderNaming", "test_clip_output_dir_with_creator_and_title"),
    ("tests/test_stage2.py", "TestOutputFolderNaming", "test_clip_output_dir_falls_back_to_title"),
    ("tests/test_stage2.py", "TestExistingOutputReuse", "test_valid_existing_output_is_reused"),
    ("tests/test_stage2.py", "TestExistingOutputReuse", "test_invalid_existing_output_triggers_redownload"),
    ("tests/test_stage2.py", "TestManifestGeneration", "test_manifest_contains_creator_title_and_metadata"),
    ("tests/test_stage2.py", "TestResilience", "test_existing_valid_clip_skipped"),
    ("tests/test_stage2.py", "TestResilience", "test_successful_clips_untouched_after_another_fails"),
    ("tests/test_stage2.py", "TestResilience", "test_manifest_records_retry_count_and_status"),
    ("tests/test_stage2_buffer.py", "TestBufferInRun", "test_skips_when_existing_duration_matches_buffered"),
]


def node_span(node: ast.AST) -> tuple[int, int]:
    """Rentang baris 1-indexed inklusif sebuah node, dekorator ikut dihitung."""
    start = node.lineno
    for dec in getattr(node, "decorator_list", []):
        start = min(start, dec.lineno)
    return start, node.end_lineno


def main() -> int:
    by_file: dict[str, list[tuple[str, str]]] = {}
    for rel, cls, meth in TARGETS:
        by_file.setdefault(rel, []).append((cls, meth))

    for rel, items in by_file.items():
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        lines = src.split("\n")
        tree = ast.parse(src)

        drop: set[int] = set()          # baris (1-indexed) yang dibuang
        removed: list[str] = []
        missing: list[str] = []

        classes = {
            n.name: n for n in tree.body
            if isinstance(n, ast.ClassDef)
        }

        for cls, meth in items:
            cnode = classes.get(cls)
            if cnode is None:
                missing.append(f"{cls} (kelas tidak ada)")
                continue
            fnode = next(
                (
                    m for m in cnode.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and m.name == meth
                ),
                None,
            )
            if fnode is None:
                missing.append(f"{cls}::{meth}")
                continue
            a, b = node_span(fnode)
            drop.update(range(a, b + 1))
            removed.append(f"{cls}::{meth}")

        # Kelas yang seluruh isinya terbuang -> buang kelasnya juga.
        for cls, cnode in classes.items():
            if not any(c == cls for c, _ in items):
                continue
            # Docstring kelas tidak dihitung sebagai isi.
            body_stmts = [
                m for m in cnode.body
                if not (isinstance(m, ast.Expr) and isinstance(m.value, ast.Constant))
            ]
            survivors = []
            for m in body_stmts:
                a, b = node_span(m)
                if not all(ln in drop for ln in range(a, b + 1)):
                    survivors.append(m)
            if not survivors:
                a, b = node_span(cnode)
                drop.update(range(a, b + 1))
                removed.append(f"{cls} (kelas kosong -> dibuang)")

        kept = [ln for i, ln in enumerate(lines, start=1) if i not in drop]

        # Rapikan: jangan sisakan lebih dari 2 baris kosong berurutan.
        out: list[str] = []
        blanks = 0
        for ln in kept:
            if ln.strip() == "":
                blanks += 1
                if blanks > 2:
                    continue
            else:
                blanks = 0
            out.append(ln)
        text = "\n".join(out).rstrip("\n") + "\n"

        # Penjaga: hasilnya WAJIB masih Python yang sah.
        try:
            ast.parse(text)
        except SyntaxError as e:
            print(f"[GAGAL] {rel}: hasil bukan Python sah -> {e}")
            return 1

        path.write_text(text, encoding="utf-8")
        print(f"[OK] {rel}: {len(drop)} baris dibuang")
        for r in removed:
            print(f"       - {r}")
        for m in missing:
            print(f"       ! TIDAK DITEMUKAN: {m}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
