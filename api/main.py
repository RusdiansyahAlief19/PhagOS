import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import security
from . import db
from . import schemas

app = FastAPI(
    title="SentinelOps API",
    description="Lapisan interpretasi keamanan jaringan untuk institusi tanpa tim SOC",
    version="0.1.0",
)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

db.init_db()
_rag_engine = None
_rag_error = None
try:
    from .rag_loader import load_engine
    _rag_engine = load_engine()
except Exception as exc:
    _rag_error = str(exc)

@app.get("/")
def root():
    return FileResponse(WEB_DIR / "index.html")

@app.get("/")
def serve_frontend():
    html_path = os.path.join(os.path.dirname(__file__), "..", "web", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"message": "Frontend not found"}

@app.get("/health")
def health():
    hosts = db.get_hosts()
    return {
        "status": "ok" if _rag_engine is not None else "degraded",
        "hosts_tracked": len(hosts),
        "rag_ready": _rag_engine is not None,
        "rag_error": _rag_error,
    }

@app.post("/ingest", dependencies=[Depends(security.verify_hmac_signature)])
def ingest(batch: schemas.IngestBatch):
    if not batch.events:
        return {"received": 0, "stored": 0}

    rows = [schemas.flatten(ev) for ev in batch.events]
    stored = db.insert_events(rows)
    return {"received": len(batch.events), "stored": stored}

@app.get("/assets")
def list_assets():
    return {"hosts": db.get_hosts()}

@app.get("/assets/{ip}")
def get_asset(ip: str):
    host = db.get_host(ip)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {ip} tidak ditemukan")
    return host

@app.get("/timeline")
def timeline(limit: int = 100):
    limit = max(1, min(limit, 500))
    half = limit // 2

    with db.db_cursor() as cur:
        # Ambil alert (signature) terpisah supaya tidak tenggelam
        cur.execute(
            "SELECT ts, event_type, src_ip, dest_ip, dest_port, "
            "sid, signature, severity FROM events "
            "WHERE sid IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (half,),
        )
        sig_rows = [dict(r) for r in cur.fetchall()]

        # Ambil flow/dns tanpa alert, KECUALIKAN event_type 'stats'
        # karena stats adalah catatan internal Suricata (tanpa src/dest IP)
        cur.execute(
            "SELECT ts, event_type, src_ip, dest_ip, dest_port, "
            "sid, signature, severity FROM events "
            "WHERE sid IS NULL AND event_type != 'stats' "
            "ORDER BY id DESC LIMIT ?",
            (half,),
        )
        stat_rows = [dict(r) for r in cur.fetchall()]

    for r in sig_rows:
        r["source"] = "signature"
    for r in stat_rows:
        r["source"] = "statistical"

    return {"events": sig_rows + stat_rows}


class ChatRequest(BaseModel):
    query: str


@app.post("/chat")
def chat(req: ChatRequest):
    if _rag_engine is None:
        raise HTTPException(
            status_code=503,
            detail=f"Mesin RAG belum siap. Jalankan indexer dulu. ({_rag_error})",
        )
    if not req.query.strip():
        raise HTTPException(status_code=422, detail="Pertanyaan kosong")

    import re
    host_data = None
    ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', req.query)
    if ip_match:
        host_data = db.get_host(ip_match.group(0))

    return _rag_engine.answer(req.query, host_data=host_data)
