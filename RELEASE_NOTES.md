# Rex Code v0.2.0 — Sprint Mega: Keamanan & Paritas Agener

Rilis ketiga Rex Code: fondasi keamanan diperkuat dan banyak fitur baru,
semuanya gratis dan open-source (MIT).

## 🔐 Keamanan

- **Verifikasi checksum auto-update** — semua unduhan diverifikasi SHA256
  terhadap `SHA256SUMS.txt` sebelum boleh dieksekusi; mismatch = file dibuang
- **Approval gate untuk tool eksternal** — tool MCP dan plugin kini wajib
  konfirmasi (saat approval diaktifkan), sama seperti tool destruktif bawaan
- **Redaksi secret** — error dari tool eksternal disaring; nilai yang
  menyerupai API key/token diganti `<REDACTED>`
- **Sandbox perintah** — denylist perintah destruktif, sanitasi environment
  secret, blokir path absolut/traversal, secret scan sebelum git push

## ✨ Fitur baru

- **`/model`** — ganti provider/model di tengah sesi; **fallback chain**
  antar-provider saat provider utama gagal
- **`/diff`** — review per-file semua perubahan sesi (shadow git)
- **Auto test-run hook** — setelah edit, test proyek dijalankan otomatis;
  kegagalan diumpankan balik ke agen
- **`/doctor`** — cek kesehatan: API key, provider, config, updater
- **`/stats`** — akumulasi token & estimasi biaya per sesi
- **`/commit` & `/pr`** — susun pesan commit konvensional & deskripsi PR
  dengan AI dari diff nyata
- **Multimodal** — kirim gambar/screenshot ke agen (vision); `@file` untuk
  menyuntikkan file ke konteks
- **MCP HTTP/SSE** — transport baru selain stdio; `rex plugin add <git-url>`
- **`/ask`** — pencarian simbol cepat via indeks kode lokal
- **Klik-kanan Explorer** — "Open Rex here" di Windows (via installer)
- **Tema TUI** + tampilan changelog singkat setelah auto-update sukses

## 📦 Unduhan

| Platform | File |
| --- | --- |
| Windows (installer) | `RexCode-Setup-v0.2.0-x64.exe` |
| Linux x64 | `rex-linux-x64.zip` |
| macOS Apple Silicon | `rex-macos-arm64.zip` |

Integritas: verifikasi dengan `SHA256SUMS.txt`
(`sha256sum -c SHA256SUMS.txt`).

> **SmartScreen**: installer belum ditandatangani (code signing gratis via
> SignPath Foundation sedang diproses). Bila muncul peringatan biru Windows:
> *More info* → *Run anyway* — atau verifikasi checksum terlebih dahulu.

Panduan lengkap: [PANDUAN-INSTALL.md](https://github.com/huseinrosidstilllearn/rex-code/blob/master/PANDUAN-INSTALL.md)
