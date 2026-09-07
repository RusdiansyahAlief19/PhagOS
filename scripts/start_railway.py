"""Prepare generated runtime data and start the Railway web process."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import timedelta


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


def run_scoring_loop() -> int:
    """Recompute host scores from the persisted event database periodically."""
    sys.path.insert(0, str(REPO_ROOT / "api"))
    import db
    import scoring

    interval = max(10, int(os.environ.get("SENTINELOPS_SCORING_INTERVAL", "60")))
    window_minutes = max(1, int(os.environ.get("SENTINELOPS_SCORING_WINDOW_MINUTES", "5")))
    db.init_db()

    while True:
        try:
            with db.db_cursor() as cur:
                cur.execute("SELECT MIN(ts), MAX(ts) FROM events")
                first_ts, last_ts = cur.fetchone()

            if first_ts and last_ts:
                baseline_start = scoring.parse_argumen_waktu(first_ts)
                window_end = scoring.parse_argumen_waktu(last_ts)
                window_start = window_end - timedelta(minutes=window_minutes)
                if window_start > baseline_start:
                    hosts = scoring.get_all_hosts_seen(
                        (baseline_start, window_start),
                        (window_start, window_end),
                    )
                    for host in hosts:
                        result = scoring.hitung_skor_host(
                            host,
                            baseline_start,
                            window_start,
                            window_start,
                            window_end,
                            window_minutes,
                        )
                        db.upsert_host(
                            result["ip"],
                            result["risk_score"],
                            result["band"],
                            result["baseline_status"],
                            result["total_events"],
                            reason=result["reason"],
                        )
                        db.record_score(
                            result["ip"], result["risk_score"], result["band"]
                        )
                    print(f"[scoring] Memperbarui {len(hosts)} host.")
            time.sleep(interval)
        except Exception as exc:
            print(f"[scoring] Gagal memperbarui skor: {exc}", file=sys.stderr)
            time.sleep(interval)


def main() -> int:
    if "--score-loop" in sys.argv:
        return run_scoring_loop()

    ensure_retrieval_index()

    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--score-loop"],
        cwd=REPO_ROOT,
    )

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
