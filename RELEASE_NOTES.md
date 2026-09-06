# Rex Code v0.3.0 — Fondasi Agen Native

Rilis keempat Rex Code: 15 fitur baru yang menutup gap terbesar menuju
paritas agen native sekelas Claude Code — tetap gratis dan open-source (MIT).

## ✨ Fitur baru

- **`/cost` + usage meter** — akumulasi token per sesi dengan rincian
  per-model, estimasi biaya dari config `model_costs`, dan meter live
  di status bar (`1.8k tok · ~$0.0021`)
- **Token budget guard** — set `token_budget` (total token per sesi,
  0 = tanpa batas): peringatan kuning di 80%, berhenti keras di 100%
  sebelum panggil provider berikutnya
- **Hooks Pre/PostToolUse** — `.rex/hooks.json` menjalankan perintah Anda
  di sekitar setiap tool call: exit code 2 pada `PreToolUse` memblokir
  call (stdout jadi alasan yang dilihat model), `PostToolUse` diumpankan
  balik ke model; sandboxed, fail-open
- **Session resume** — sesi yang terputus (crash) otomatis dilanjutkan
  saat start berikutnya; `/resume` melihat 8 sesi terakhir, `/resume <n>`
  memuat ulang riwayat penuh, `/new` mulai segar
- **`/rewind <n>`** — timeline checkpoint bernomor; kembalikan workspace
  N langkah, perubahan belum-commit di-auto-simpan dan `/redo`
  membatalkannya
- **Background shell tasks** — `run_command_bg` menjalankan dev server /
  build tanpa memblokir percakapan; `task_output` memantau (opsional
  tunggu 0–30 detik), `task_kill` menghentikan; maks 8 task paralel
- **`/status`** — laporan kesehatan seluruh subsistem: provider, API key,
  fallback chain, MCP, plugin, hooks, scheduler, sesi, checkpoint,
  updater, approval, budget
- **`web_search` + `web_fetch`** — riset web via DuckDuckGo (tanpa API
  key, tanpa dependensi baru); host private/link-local diblokir
  (SSRF-safe), allowlist domain opsional, semua respons disaring dari
  secret dan dibatasi ukurannya
- **`@` autocomplete + `@file:symbol`** — ketik `@` di TUI untuk saran
  file (Tab untuk melengkapi); `@path/file.py:ClassName` meng-inline
  hanya rentang sumber simbol itu, bukan seluruh file
- **`/compare`** — satu prompt dijalankan paralel di provider aktif +
  fallback chain (maks 3), jawaban ditampilkan berdampingan dengan waktu;
  varian yang gagal tidak mempengaruhi yang lain
- **`/export md|html`** — simpan sesi ke file Markdown atau HTML
  standalone; footer token + biaya; redaksi secret tetap terjaga
- **Aturan proyek berlapis** — `.rex/rules/*.md` di root berlaku di mana
  saja; di subfolder berlaku saat mengerjakan folder itu; toggle via
  `context.rules`
- **Skills on-demand** — `<name>/SKILL.md` di `.rex/skills/`: ringkasan
  masuk system prompt, isi lengkap dimuat model via tool `load_skill`,
  atau langsung dengan `/skill <name> [args]` (`/skills` untuk daftar)
- **Delegasi paralel via git worktree** — `delegate_parallel` menjalankan
  hingga 3 sub-agent secara serentak, masing-masing di worktree terpisah
  sebagai child Rex headless (tulisannya hanya menyentuh salinan);
  worktree dibuang setelahnya dan patch-nya direview lalu diterapkan via
  `apply_patch` (approval gate + checkpoint)
- **Plugins API v2** — manifest `plugin.toml` opsional (nama, versi,
  deskripsi, izin eksplisit `net|shell|fs|env`);
  `plugins.blocked_permissions` menutup plugin yang menyatakan izin yang
  diblokir; `/plugins` merender tabel status

## 🔧 Perbaikan

- **TUI crash saat startup** — `rex.__version__` dirujuk tanpa import;
  terdeteksi lewat smoke test build
- **Stylesheet TUI** — variabel CSS `$rex-*` dipakai sebelum
  didefinisikan (approval box kehilangan background-nya secara diam)

## 🧪 Kualitas

Suite self-check tumbuh **33 → 39** (usage, hooks, status, websearch,
export, skills baru + 8 ekstensi suite lama) — semua hijau, semuanya
mock-driven tanpa jaringan.

## 📦 Unduhan

| Platform | File |
| --- | --- |
| Windows (installer) | `RexCode-Setup-v0.3.0-x64.exe` |
| Linux x64 | `rex-linux-x64.zip` |
| macOS Apple Silicon | `rex-macos-arm64.zip` |

Integritas: verifikasi dengan `SHA256SUMS.txt`
(`sha256sum -c SHA256SUMS.txt`).

> **SmartScreen**: installer belum ditandatangani (code signing gratis via
> SignPath Foundation sedang diproses). Bila muncul peringatan biru Windows:
> *More info* → *Run anyway* — atau verifikasi checksum terlebih dahulu.

Panduan lengkap: [PANDUAN-INSTALL.md](https://github.com/huseinrosidstilllearn/rex-code/blob/master/PANDUAN-INSTALL.md)
