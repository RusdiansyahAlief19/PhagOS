# SentinelOps

**Virtual SOC Analyst** untuk kampus, UMKM, dan instansi daerah yang memiliki
sensor jaringan tetapi belum memiliki tim SOC khusus. SentinelOps menjadi
lapisan analitik di atas Suricata: log `eve.json` dikumpulkan, diringkas menjadi
prioritas risiko per host, lalu dijelaskan dalam Bahasa Indonesia melalui
chatbot RAG dengan sitasi.

Dibangun untuk HoloDev, HOLOGY 9.0 (Universitas Brawijaya), subtema
**Infrastruktur Sosial**.

## Konsep dan fitur utama

SentinelOps menggunakan arsitektur **dual-engine**:

1. **Statistical Risk Scoring** membandingkan traffic terbaru dengan baseline
   historis menggunakan percentile scoring pada enam fitur perilaku jaringan.
2. **Virtual SOC Analyst (RAG)** menerjemahkan SID dan konteks ancaman melalui
   hybrid search FAISS + BM25 dan Reciprocal Rank Fusion (RRF), dengan sumber
   MITRE ATT&CK dan ET Open.

Fitur yang tersedia:

- matriks risiko aset yang diurutkan berdasarkan skor;
- timeline dengan atribusi `signature` atau `statistical`;
- chatbot RAG dengan sitasi; dan
- API ingest dengan HMAC-SHA256 serta replay protection.

Sistem bersifat **advisory-only/read-only**: tidak memblokir IP, mengubah
firewall, atau menjalankan mitigasi otomatis. Scoring dan penyimpanan event
berjalan lokal; hanya pertanyaan dan konteks corpus publik yang dikirim ke
Gemini.

## Arsitektur singkat

```text
Suricata (eve.json)
        |
        v
Log Shipper -- HMAC --> FastAPI (/ingest)
                            |             |
                            v             v
                   Statistical Scoring   RAG Engine
                            |             |
                            +------> SQLite
                                      |
                                      v
                         API (/assets, /timeline, /chat)
                                      |
                                      v
                                Dashboard web
```

## Struktur project

```text
sentinelops/
├── api/                         Backend FastAPI dan logika analitik
│   ├── main.py                 Endpoint API dan integrasi dashboard
│   ├── db.py                   Skema dan query SQLite terparameterisasi
│   ├── schemas.py              Validasi dan flattening event Suricata
│   ├── scoring.py              Baseline dan percentile scoring
│   ├── security.py             HMAC-SHA256 dan replay protection
│   └── rag_loader.py           Memuat engine RAG
├── agent/shipper.py             Tail eve.json dan kirim batch bertanda tangan
├── corpus/                      Pipeline corpus dan retrieval RAG
│   ├── build_attack.py         Ekstraksi MITRE ATT&CK
│   ├── parse_et_rules.py       Parsing Emerging Threats rules
│   ├── build_corpus.py         Membuat chunks bilingual
│   ├── indexer.py              FAISS dan BM25 index
│   ├── engine.py               Hybrid retrieval dan Gemini
│   ├── prompts.py              System prompt SOC analyst
│   └── eval_retrieval.py       Evaluasi kualitas retrieval
├── scripts/setup_data.py        Orkestrasi setup corpus dan index
├── security/                    Baseline dan skenario pengujian
├── docs/                        Threat model, evaluasi, dan lisensi
├── web/                         Dashboard frontend
├── requirements.txt             Dependensi Python
└── .gitignore                   Secret dan artefak runtime
```

## Menjalankan secara lokal

Prasyarat: Python 3.10+, Gemini API key, dan dependensi pada
`requirements.txt`.

```powershell
git clone https://github.com/RusdiansyahAlief19/SentinelOps.git
cd SentinelOps
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Buat `.env` di root:

```dotenv
GEMINI_API_KEY=isi_key_anda
SENTINELOPS_HMAC_SECRET=ganti_dengan_secret_acak
```

Siapkan corpus dan index:

```powershell
python scripts\setup_data.py
```

Untuk membangun corpus tanpa ringkasan Gemini, gunakan `--dry-run`. Opsi ini
tidak menonaktifkan Gemini pada tahap embedding; gunakan `--skip-index` jika
ingin validasi lokal tanpa API:

```powershell
python scripts\setup_data.py --dry-run --skip-index
```

Jalankan backend:

```powershell
uvicorn api.main:app --reload --port 8000
```

Dokumentasi OpenAPI tersedia di `http://localhost:8000/docs`.

Jalankan dashboard sederhana pada terminal lain:

```powershell
cd web
python -m http.server 5500
```

Buka `http://localhost:5500`. URL backend dikonfigurasi pada konstanta `API` di
`web/index.html`.

## Memasukkan data dan menghitung skor

```powershell
python agent\shipper.py `
  --eve-path C:\path\ke\eve.json `
  --api-url http://127.0.0.1:8000/ingest `
  --secret $env:SENTINELOPS_HMAC_SECRET `
  --exit-when-caught-up
```

Scoring dilakukan dengan membandingkan periode observasi terhadap baseline:

```powershell
python api\scoring.py `
  --baseline-start "<waktu_mulai_baseline>" `
  --baseline-end "<waktu_selesai_baseline>" `
  --window-start "<waktu_mulai_window>" `
  --window-end "<waktu_selesai_window>" `
  --window-minutes 1
```

Ukuran window observasi harus sama dengan ukuran window baseline agar hasil
perbandingan valid.

## Dokumentasi dan keterbatasan

- `docs/threat_model.md` — analisis STRIDE dan risiko residual.
- `docs/LICENSES.md` — lisensi serta atribusi sumber data.
- `docs/retrieval-eval.md` — evaluasi retrieval RAG.
- `security/README.md` — metodologi dan bukti validasi keamanan.

Artefak `corpus/raw/`, `faiss_index/`, `bm25_index.pkl`, database SQLite,
`.env`, dan log runtime tidak dilacak Git. Endpoint baca belum menyediakan
autentikasi pada versi prototipe; deployment produksi memerlukan autentikasi,
HTTPS/TLS, rate limiting, serta kebijakan retensi data.
