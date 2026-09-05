# 🦖 REX CODE — Autonomous AI Coding & Workflow Agent

Asisten coding otonom dan ahli otomatisasi pribadi Anda, dibuat khusus untuk membangun software dan alur kerja bisnis secara mandiri tanpa Anda perlu bisa coding.

---

## 🚀 Cara Menjalankan Rex Code (Super Mudah)

Anda punya **2 cara** untuk memakai Rex Code:

### Cara 1: Web Dashboard (Rekomendasi untuk Pemula)
Cukup **klik dua kali** file:
👉 `start_web.bat`
Browser Anda akan otomatis terbuka ke `http://localhost:8000`. Anda bisa langsung mengobrol, memilih mode, dan melihat file yang dibuat secara visual.

### Cara 2: Terminal CLI (Gaya Claude Code)
Cukup **klik dua kali** file:
👉 `start_cli.bat`
Jendela terminal modern akan terbuka dengan teks berwarna dan interaksi instan.

CLI menyimpan percakapan lokal. Gunakan `/sessions`, `/new`, `/use <id>`, dan `/delete <id>` untuk mengelola sesi.

---

## 🎯 2 Mode Operasi Utama

1. **📋 Mode PLAN:**
   Rex Code hanya meneliti, merancang arsitektur, dan membuat rencana kerja tertulis tanpa menyentuh atau mengubah file apa pun. Anda bisa berdiskusi dan memeriksa rencananya terlebih dahulu.
2. **🔨 Mode BUILD:**
   Setelah Anda setuju, Rex Code mulai mengeksekusi secara mandiri:
   - Menulis file kode lengkap ke folder `./workspace/`.
   - Menginstal paket dan menjalankan perintah di terminal.
   - **Auto-Debug:** Jika ada error/bug saat dijalankan, Rex Code otomatis membaca pesan error, memperbaiki kodenya, dan mengujinya kembali sampai berhasil!

---

## ⚡ Alur Otomasi n8n & Activepieces (1-Click Import)

Rex Code bisa membuat file alur kerja otomasi dalam format `.json` resmi untuk **n8n** dan **Activepieces**:
* File akan disimpan di folder `./workflows/`.
* Buka n8n atau Activepieces di browser Anda, klik **Import**, dan alur kerja langsung aktif tanpa perlu merakit node dari nol.
* Rex Code juga bisa menuliskan kode custom JavaScript / Python di dalam *Code Node* secara otomatis.

---

## 🛡️ Integrasi No-AI-Slop

Rex Code mematuhi prinsip anti-slop:
* Nol kata klise AI (*delve, foster, leverage, streamline, cutting-edge, game changer, tapestry*).
* Tanpa basa-basi pembuka (*"Here's the thing"*) atau penutup rangkuman (*"In conclusion"*).
* Teks aplikasi dan kode yang dihasilkan natural dan manusiawi.
* Perintah `/anti-slop` di terminal untuk mengaudit tulisan draf Anda.

---

## 📁 Struktur Direktori

* `workspace/` : Tempat Rex Code membuat file aplikasi dan kode proyek Anda.
* `workflows/` : Tempat Rex Code mengekspor file alur kerja JSON untuk n8n dan Activepieces.
* `sessions/` : Riwayat percakapan dashboard dalam JSON lokal; diabaikan Git.
* `config.json` : Pengaturan model aktif, provider, dan mode.
* `.env` : Tempat menyimpan API Key Anda dengan aman.

---

## Menambah Provider OpenAI-Compatible

Tambahkan metadata provider ke objek `providers` di `config.json`:

```json
"token_murah": {
  "name": "Token Murah",
  "type": "openai_compatible",
  "base_url": "https://alamat-provider.example/v1",
  "api_key_env": "TOKEN_MURAH_API_KEY",
  "model": "nama-model",
  "available_models": ["nama-model"]
}
```

Simpan token hanya di `.env`, bukan `config.json`:

```env
TOKEN_MURAH_API_KEY=isi-token-anda
```

Restart Rex Code. Provider dan model otomatis muncul di CLI `/models` dan pemilih model dashboard. `base_url` harus mencakup `/v1` bila layanan mensyaratkannya.

---

## Guardrail Terminal

Mode Build menjalankan terminal dari `workspace/`. Perintah sistem berbahaya, akses `.env`/`config.json`, path absolut, dan traversal `../` diblokir. Secret environment tidak diteruskan ke child process. Atur batas melalui `terminal_timeout_sec`, `terminal_output_max_chars`, dan `command_allowlist` di `config.json`.

Guardrail ini bukan sandbox OS penuh. Untuk menjalankan kode pihak ketiga yang tidak dipercaya, gunakan container atau akun Windows terbatas.

## Riwayat Percakapan

Dashboard menyimpan percakapan lokal per sesi dan memulihkannya setelah browser di-refresh. Buat, pilih, atau hapus sesi lewat panel kiri. `max_history_messages` di `config.json` membatasi jumlah pesan terakhir yang dikirim kembali ke model. Secret pada field sensitif serta output panjang diredaksi atau dipotong sebelum disimpan.

## Streaming Respons

Dashboard menampilkan respons Gemini dan provider OpenAI-compatible secara bertahap saat model menghasilkannya. Atur `stream_enabled` ke `false` di `config.json` untuk kembali ke respons non-streaming. Router yang tidak mendukung SSE otomatis memakai respons JSON biasa.

Tombol **Stop** meminta pembatalan kooperatif. Request provider aktif mungkin selesai lebih dulu, tetapi tool atau langkah berikutnya tidak dijalankan. Statistik jumlah pesan dan karakter tersimpan tersedia sebagai tooltip deskripsi mode.

## Pemeriksaan Lokal

Jalankan semua self-check tanpa layanan eksternal:

```bash
python run_all_checks.py
```
