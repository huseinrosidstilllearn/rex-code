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

## Bagian C — Untuk pemilik proyek (rilis versi baru)

Dilakukan **sekali** saat pertama kali, lalu tiap kali mau merilis versi baru.

### C.1. Persiapan sekali saja

1. **Buat repo GitHub** bernama `rex-code` (public) di `github.com`.
2. Di folder proyek ini, jalankan di terminal:
   ```
   git remote add origin https://github.com/huseinrosidstilllearn/rex-code.git
   git push -u origin master
   ```
3. **Buat API key Gemini** di `aistudio.google.com` dan isi `.env` (Bagian A langkah 3)
   supaya Rex bisa diuji di komputer sendiri.

### C.2. Rilis versi baru (tiap kali, ~3 menit)

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

---

## Bagian D — Troubleshooting singkat

| Masalah | Solusi |
| --- | --- |
| `Provider gagal diinisialisasi` | `.env` belum ada / `GEMINI_API_KEY` salah → Bagian A langkah 3. |
| Windows SmartScreen menolak installer | Klik *More info* → *Run anyway* (normal untuk app tanpa sertifikat kode). |
| Update tidak muncul | Repo belum punya Releases, atau `enabled: false` di config. |
| Mau unduh manual | Buka `https://github.com/huseinrosidstilllearn/rex-code/releases/latest`. |
