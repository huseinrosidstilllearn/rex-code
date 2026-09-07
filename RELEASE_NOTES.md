# Rex Code v0.3.1 — Rex Desktop

Rilis kelima Rex Code: **Rex Desktop** menjadi front utama — jendela
aplikasi native (server lokal + SPA) dengan **Settings Center** terpadu,
plus CLI interaktif baru berbasis prompt_toolkit. Tetap gratis dan
open-source (MIT).

## ✨ Fitur baru

- **Rex Desktop (front utama)** — menjalankan `rex` tanpa argumen kini
  membuka jendela aplikasi desktop (WebView2): chat streaming SSE,
  sidebar sesi/file, modal approval, `@file` autocomplete — bukan lagi
  terminal. `--web` untuk mode browser
- **Settings Center** — kelola semua pengaturan dari UI: mode default,
  token budget, max steps, streaming, anti-slop, timeout, max history;
  tersimpan ke `config.json` dengan validasi yang sama persis
- **Provider manager** — lihat/aktifkan/tambah/ubah/hapus provider,
  ganti model, dan **test connection** round-trip per provider langsung
  dari Settings
- **API key vault** — key API hanya ditulis ke `.env` (chmod 600) dan
  variabel lingkungan live; **tidak pernah** tersentuh `config.json`,
  tidak pernah dikirim ke client
- **Onboarding terpadu** — API key + provider dipandu dari Desktop saat
  pertama kali; `--cli`/`--tui` tetap tersedia untuk power user
- **CLI interaktif baru** — REPL prompt_toolkit: riwayat input
  (`cli_history`, panah atas/bawah), autocomplete slash-command
  (~30 perintah), render ANSI penuh; fallback mulus ke `input()` polos
  bila prompt_toolkit tidak ada
- **UTF-8 di mana-mana** — stdout/stderr direkonfigurasi ke UTF-8 di
  Windows; banner/emoji/checkmark tidak lagi rusak (mojibake) atau
  crash di console cp1252

## 🔧 Perbaikan

- **Banner crash saat di-pipe** — `UnicodeEncodeError` cp1252 saat
  stdout dialihkan; sekarang stream dipaksa UTF-8 sejak startup
- **5 checkmark mojibake** di `cli.py` diperbaiki (U+2713)
- **prompt_toolkit tanpa console** — `NoConsoleScreenBufferError` saat
  stdout bukan terminal kini jatuh mulus ke fallback `input()` polos

## 🧪 Kualitas

Suite self-check tumbuh **39 → 42** (desktop + cli_ui baru + pengujian
ulang menyeluruh) — semua hijau, semuanya mock-driven tanpa jaringan.

## 📦 Unduhan

| Platform | File |
| --- | --- |
| Windows (installer) | `RexCode-Setup-v0.3.1-x64.exe` |
| Linux x64 | `rex-linux-x64.zip` |
| macOS Apple Silicon | `rex-macos-arm64.zip` |

Integritas: verifikasi dengan `SHA256SUMS.txt`
(`sha256sum -c SHA256SUMS.txt`).

> **SmartScreen**: installer belum ditandatangani (code signing gratis via
> SignPath Foundation sedang diproses). Bila muncul peringatan biru Windows:
> *More info* → *Run anyway* — atau verifikasi checksum terlebih dahulu.

Panduan lengkap: [PANDUAN-INSTALL.md](https://github.com/huseinrosidstilllearn/rex-code/blob/master/PANDUAN-INSTALL.md)
