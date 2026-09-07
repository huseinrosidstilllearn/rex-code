# Rex Code v0.3.3 — Desktop Foundations

Rilis ketujuh Rex Code: fondasi **desktop-first**. Rex Desktop kini bukan
hanya jendela chat — ia menggerakkan seluruh subsistem Rex (checkpoints,
todos, diff, health, export, stats) lewat API lokal, plus harness CI yang
menggerti setiap push. Tetap gratis, open-source (MIT), tanpa dependency
runtime baru.

## 🛡️ CI & Harness Hardening

- **`tests.yml`** — workflow CI baru: seluruh **43 suite self-check**
  (117s lokal) berjalan di GitHub Actions pada setiap push/PR ke master,
  di runner yang sama dengan pipeline release (windows-latest, Python 3.12).
  Sebelumnya CI hanya menjalankan `test_packaging.py` saat rilis — regresi
  bisa lolos tanpa terdeteksi
- **`run_all_checks.py` di-hardening** — timeout 300s per suite (satu test
  hang tidak lagi menggantung seluruh harness), suite berikut tetap jalan
  saat ada yang gagal, ringkasan kegagalan lengkap + exit code CI-friendly

## 🖥️ Desktop API (10 endpoint baru, `rex/desktop/server.py`)

Semua endpoint **never-raise** (JSON error envelope) dan meng-reuse fungsi
core yang sudah teruji — tanpa logika baru:

- `GET /api/checkpoints` — `rex.checkpoints.list_checkpoints`
- `POST /api/rewind {steps}` — `rex.checkpoints.rewind` (validasi 1–100)
- `POST /api/undo` / `POST /api/redo` — `rex.checkpoints.undo/redo`
- `GET /api/todos` — `rex.todos.get + summary`
- `GET /api/diff` — `rex.review.session_diff`
- `GET /api/health` — `rex.status.collect_status`
- `GET /api/export?fmt=md|html` — `rex.export.export_session`
- `GET /api/stats` — `rex.stats.collect_stats`

- Input `steps` divalidasi (bulat 1–100 → `400` kalau tidak); rollback
  yang tidak mungkin mengembalikan `{ok: false}` ramah, bukan error
- Setiap rollback sukses memancarkan event SSE `checkpoint_rolled` — UI
  lain yang tersambung ikut refresh
- Endpoint bersifat **frontend-agnostic**: SPA vanilla sekarang, Tauri/
  Electron di masa depan — kerja backend tetap terpakai

## 🎨 Desktop UI (SPA wiring)

- **Sidebar tabs**: Sesi · Files · Todos · Cekpoin — Files klik → sisip
  `@path` ke composer; Cekpoin klik → rewind ke checkpoint itu
- **Kontrol checkpoint**: Undo / Redo / Rewind di sidebar. Aksi destruktif
  **selalu** lewat modal konfirmasi (pola approval yang sudah ada); rewind
  punya input jumlah langkah
- **Topbar**: health badge (dot hijau/kuning, klik → detail doctor/status),
  tombol Diff (perubahan sejak checkpoint terakhir), Stats (token/biaya),
  Export (markdown sesi aktif)

## 🔧 Perbaikan

- **CRITICAL: `rex/plugins.py` crash di Python ≤3.13** — `Optional` dipakai di
  signature `read_manifest`/`_manifest_meta`/`install_plugin_from_git` tanpa
  pernah diimpor. Di Python 3.14 (PEP 649) annotation dievaluasi lazy sehingga
  tersembunyi saat develop; di runtime installer (3.12) dievaluasi eager →
  `NameError` saat import `rex.core` → aplikasi gagal memuat chat. Bug ini
  juga ada di installer v0.3.1/v0.3.2 — pengguna exe disarankan update ke
  0.3.3. Ditemukan oleh workflow `tests.yml` baru (CI Python 3.12) pada run
  pertamanya — persis celah yang sprint ini tutup
- **`app.js` syntax corruption** — ekor `paintProviderEditor`/
  `paintProvidersTab` (Settings Center) dari sesi develop sebelumnya
  tercecer di top-level setelah `boot()` → SyntaxError, SPA tidak bisa
  dimuat sama sekali. Sudah dipulihkan (`node --check` bersih)
- **Bug validasi rewind** — `steps=0` lolos validasi (`0 or 1` → 1) dan
  memicu rewind asli; tertangkap oleh test baru sebelum merugikan user
- **test_vision di CI** — perbandingan path image kini memakai `.resolve()`:
  runner CI menyerahkan TEMP path 8.3 pendek (`C:\Users\RUNNER~1\...`)
  sementara `extract_references` mengkanonikalisasi ke bentuk panjang
- `test_desktop.py` diperluas: smoke test seluruh 10 endpoint + validasi
  input; core destruktif (rewind/undo/redo/export) di-mock agar test
  tidak pernah menyentuh shadow-history workspace user

## 📦 Upgrade

- Windows: download `RexCode-Setup-v0.3.3-x64.exe` dari
  [Releases](https://github.com/huseinrosidstilllearn/rex-code/releases/latest)
  — installer update-in-place, semua data user tetap aman
- Pengguna lama: auto-update akan menawarkan 0.3.3 (cek harian, bisa
  dimatikan per langkah di `config.json → updates`)

## 🙏 Catatan

Rex Code adalah proyek belajar terbuka dari Husein AI Project. Laporan bug
dan ide lewat [Issues](https://github.com/huseinrosidstilllearn/rex-code/issues)
sangat diterima.

— Husein AI Project, September 2026
