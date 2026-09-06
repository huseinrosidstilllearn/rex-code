# 🦖 PANDUAN INSTALASI REX CODE

Panduan singkat bahasa Indonesia — dari nol sampai Rex jalan.
Semua langkah di bawah ini hanya perlu dilakukan **sekali**.

---

## Bagian A — Memasang Rex Code di komputer (pengguna akhir)

1. **Jalankan installer** `RexCode-Setup-v0.1.0-x64.exe`.
   - Klik **Next** → pilih folder (default `C:\Program Files\RexCode`) → pilih opsi:
     - ☐ Ikon Desktop
     - ☐ Add to PATH (biar bisa ketik `rex` di terminal mana pun)
     - ☑ Keep user data (biar config/sesi aman saat uninstall)
2. **Buka Rex Code** dari Start Menu (atau ketik `rex` di terminal).
3. **Isi API key** (hanya saat pertama kali):
   - Tekan `Win + R`, ketik: `%LOCALAPPDATA%\RexCode` → Enter.
   - Buka file `.env` dengan Notepad. Kalau belum ada, salin `config.json` dulu
     sebagai cadangan lalu buat file baru bernama `.env`.
   - Isi satu baris:
     ```
     GEMINI_API_KEY=isikan-key-anda-disini
     ```
   - Key gratis didapat di `aistudio.google.com` → *Get API key*.
4. **Jalankan ulang Rex** — selesai. Banner versi (mis. `v0.1.0`) muncul di layar.

> Catatan: tanpa API key, Rex tetap terbuka dan menampilkan instruksi — tidak crash.

---

## Bagian B — Update otomatis (berlaku setelah rilis pertama)

Setiap kali Rex dibuka, dia memeriksa versi terbaru **maksimal 1× per hari**:

1. Ada versi baru → muncul tulisan `Pembaruan tersedia: v0.1.1`.
2. Installer baru otomatis diunduh ke `%LOCALAPPDATA%\RexCode\downloads\`.
3. Installer dijalankan otomatis → Windows menanyakan izin (UAC) → ikuti wizard
   seperti biasa. Rex menutup dirinya sendiri agar file tidak terkunci.

Mau mematikan sebagian? Edit `config.json` → bagian `"updates"`:

| Kunci | Default | Arti |
| --- | --- | --- |
| `enabled` | `true` | Periksa pembaruan saat startup |
| `auto_download` | `true` | Unduh installer otomatis |
| `auto_install` | `true` | Jalankan installer setelah terunduh |
| `check_interval_hours` | `24` | Jarak minimum antar pemeriksaan |

---

## Bagian C — SmartScreen & keamanan installer

Saat pertama kali menjalankan installer, Windows mungkin menampilkan layar biru
**"Windows protected your PC"** (SmartScreen). Ini **normal** — bukan berarti
file-nya berbahaya. Peringatan ini muncul karena installer Rex Code belum
ditandatangani dengan sertifikat kode berbayar (*code signing certificate*),
yang biasanya hanya dimiliki aplikasi komersial besar.

### Cara lanjut saat SmartScreen muncul

1. Klik **More info** (Info selengkapnya).
2. Klik **Run anyway** (Jalankan tetap).

Setelah itu muncul permintaan izin administrator (UAC) — juga normal, karena
installer menulis ke `C:\Program Files`.

### Cara memastikan installer yang Anda unduh asli

- Unduh **hanya** dari halaman resmi:
  `https://github.com/huseinrosidstilllearn/rex-code/releases/latest`,
  atau biarkan auto-update Rex yang mengunduh (dia hanya menerima URL resmi
  GitHub Releases).
- Nama file harus persis seperti `RexCode-Setup-v0.1.0-x64.exe` — waspada
  terhadap file dengan nama mirip dari sumber lain.
- Kalau tautan datang dari chat/email/social media, jangan dipakai — buka
  langsung halaman Releases di atas.

> Catatan: setelah suatu saat proyek memakai sertifikat kode, peringatan
> SmartScreen ini hilang dengan sendirinya.

---

## Bagian D — Untuk pemilik proyek (rilis versi baru)

Dilakukan **sekali** saat pertama kali, lalu tiap kali mau merilis versi baru.

### D.1. Persiapan sekali saja

1. **Buat repo GitHub** bernama `rex-code` (public) di `github.com`.
2. Di folder proyek ini, jalankan di terminal:
   ```
   git remote add origin https://github.com/huseinrosidstilllearn/rex-code.git
   git push -u origin master
   ```
3. **Buat API key Gemini** di `aistudio.google.com` dan isi `.env` (Bagian A langkah 3)
   supaya Rex bisa diuji di komputer sendiri.

### D.4. Manifest winget & Scoop (distribusi via package manager)

CI otomatis membuat manifest `winget` + `scoop` untuk setiap tag rilis dan
menempelkannya ke halaman *Releases* (job `distribution-manifests`). Untuk
menyinkronkan salinan di repo (agar `run_all_checks.py` tetap hijau):

```
python packaging/generate_manifests.py --fetch
python test_packaging.py
git add packaging && git commit -m "chore: manifests for v0.x.y"
```

Agar bisa dipasang lewat `winget install RexCodeTeam.RexCode` / `scoop
install rexcode`, manifest harus di-merge ke repo publik:

- **winget-pkgs**: salin 3 file YAML ke
  `manifests/r/RexCodeTeam/RexCode/<versi>/` di fork `microsoft/winget-pkgs`,
  lalu buka Pull Request.
- **Scoop Extras**: tambahkan `rexcode.json` di fork
  `ScoopInstaller/Extras`, lalu buka Pull Request.

Detail: [`packaging/README.md`](packaging/README.md).

### D.2. Rilis versi baru (tiap kali, ~3 menit)

1. Naikkan versi di **satu tempat** saja — `rex/__init__.py`:
   ```python
   __version__ = "0.1.1"
   ```
2. Commit dan buat tag (namanya harus diawali `v`):
   ```
   git add rex/__init__.py
   git commit -m "chore: bump version to 0.1.1"
   git tag v0.1.1
   git push origin master --tags
   ```
3. GitHub Actions (`.github/workflows/release.yml`) otomatis:
   - build installer Windows + zip Linux/macOS,
   - membuat halaman *Releases* dan mengunggah semua filenya.
4. Selesai — semua pengguna mendapat update otomatis besok hari (atau saat
   dibuka berikutnya, maksimal 1× per hari).

> Opsional: peringatan SmartScreen (Bagian C) hilang jika installer
> ditandatangani sertifikat kode — mis. Certum/Sectigo (sekitar $100–400/tahun)
> atau Azure Trusted Signing. Untuk tahap prototype, praktik "More info →
> Run anyway" adalah hal yang umum untuk aplikasi open-source.

### D.3. Review PR otomatis via webhook (opsional)

Rex bisa mem-review Pull Request secara otomatis — komentar 🦖 muncul di PR
begitu dibuka, atau saat seseorang menulis komentar berisi `/rex`:

1. **Set dua environment variable** di mesin tempat Rex berjalan:
   ```
   GITHUB_TOKEN=ghp_...          (token dengan akses repo)
   GITHUB_WEBHOOK_SECRET=rahasia (string bebas, dibuat sendiri)
   ```
2. **Jalankan receiver**:
   ```
   rex --serve-webhook
   ```
   Default mendengarkan di `http://127.0.0.1:8765` (hanya komputer sendiri).
   Untuk bisa dihubungi GitHub, jalankan di server/VM dan sesuaikan
   `config.json → webhook` (`host`, `port`) atau pakai argumen
   `--host 0.0.0.0 --port 9000` (letakkan di belakang reverse proxy HTTPS).
3. **Daftarkan webhook di GitHub** — repo → *Settings → Webhooks → Add webhook*:
   - Payload URL: `http://server-anda:8765/webhook/github`
   - Content type: `application/json`
   - Secret: sama dengan `GITHUB_WEBHOOK_SECRET`
   - Events: *Pull requests* + *Issue comments*
4. **Uji**: buka PR → beberapa detik kemudian komentar review dari Rex muncul.

Cek kesehatan receiver: `GET /healthz` (mis. `curl http://127.0.0.1:8765/healthz`).
Jawaban `202` berarti review dijadwalkan, `200` event valid tapi tidak perlu
review, `403` signature salah. Matikan semua: set `webhook.enabled: false` di
`config.json` — receiver menolak start (deny by default).

---

## Bagian E — Troubleshooting singkat

| Masalah | Solusi |
| --- | --- |
| `Provider gagal diinisialisasi` | `.env` belum ada / `GEMINI_API_KEY` salah → Bagian A langkah 3. |
| Windows SmartScreen menolak installer | Normal — lihat **Bagian C**: klik *More info* → *Run anyway*. |
| Update tidak muncul | Repo belum punya Releases, atau `enabled: false` di config. |
| Mau unduh manual | Buka `https://github.com/huseinrosidstilllearn/rex-code/releases/latest`. |
