"""Prepare generated runtime data and start the Railway web process."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_FILES = (
    REPO_ROOT / "faiss_index" / "index.faiss",
    REPO_ROOT / "faiss_index" / "meta.json",
    REPO_ROOT / "bm25_index.pkl",
)


def ensure_retrieval_index() -> None:
    missing = [path for path in INDEX_FILES if not path.is_file()]
    if not missing:
        print("[startup] FAISS/BM25 index sudah tersedia; lewati rebuild.")
        return

    if not os.environ.get("GEMINI_API_KEY"):
        names = ", ".join(str(path.relative_to(REPO_ROOT)) for path in missing)
        raise RuntimeError(
            f"Index RAG belum tersedia ({names}). "
            "Set GEMINI_API_KEY di Railway agar index dapat dibuat saat deploy."
        )

    print("[startup] Index RAG belum lengkap; membangun FAISS + BM25...")
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "corpus" / "indexer.py")],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    ensure_retrieval_index()

    port = os.environ.get("PORT", "8000")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    os.execv(sys.executable, command)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[startup] Gagal: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
