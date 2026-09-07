# Rex Code v0.3.2 — Agentic Excellence

Rilis keenam Rex Code: fokus internal pada **kualitas agentic** —
disiplin eksekusi, deteksi loop, pembacaan context yang hemat, sub-agent
penulis, dan memori proyek. Semua perubahan dievaluasi oleh suite self-
check baru (test_agentguard) tanpa jaringan. Tetap gratis dan open-source
(MIT).

## ✨ Fitur baru

- **Guard tool-call (anti-loop)** — panggilan tool identik (nama +
  argumen) yang diulang ≥3x otomatis diganti peringatan agar model ubah
  strategi; tool yang hasilnya bergantung state (run_command,
  task_output, git_status, web_*) dikecualikan agar siklus
  verifikasi-perbaikan-verifikasi yang sah tidak terganggu
- **Batas langkah sadar-progress** — saat `max_steps` tercapai, agent
  melaporkan ringkasan tool yang sudah dijalankan (bukan berhenti
  diam-diam) + StepEvent `step_limit` untuk UI
- **Cap loop native Gemini** — loop tool AFC Gemini kini mengikuti
  `max_steps` config (sebelumnya diam-diam dibatasi SDK di 10 panggilan)
- **read_file berjendela** — parameter `offset`/`limit` (1-based, offset
  negatif = N baris terakhir) + header posisi + footer sisa baris dengan
  hint offset lanjutan; boros context untuk file besar berakhir
- **edit_file fuzzy** — pencocokan toleran whitespace/indentasi; miss
  kini menyarankan `read_file` ulang atau fallback `apply_patch`
- **Prompt Build Mode baru** — disiplin eksplisit: baca-sebelum-edit,
  utamakan `apply_patch` (diff minimal), verifikasi via `run_command`
  sebelum klaim selesai, delegasi, dan memori
- **RexWorker** — sub-agent Mode Build pertama (tulis scoped): delegasi
  implementasi mandiri berjalan in-process dengan approval gate +
  checkpoint yang sama; tulisan **hard-scoped** ke `workspace/`
  (workflows/ + config proyek otomatis ditolak)
- **Memori proyek (.rex/memory.md)** — tool `memory_write` menyimpan
  konvensi/gotcha/preferensi (dedup, cap 200 entri, secret otomatis
  di-redaksi); di-inject ke system prompt setiap sesi (toggle
  `context.agent_memory`)

## 🔧 Perbaikan

- Loop Gemini tidak lagi berhenti di 10 langkah saat `max_steps` lebih
  besar — batas kini konsisten satu sumber (`agent.max_steps` config)
- Respons batas-langkah kini memandu model memecah tugas
  (`todo_write`) daripada sekadar gagal
- `delegate_to_worker` + `memory_write` terdaftar (26 tools total)

## 🧪 Kualitas

Suite self-check tumbuh **42 → 43** (test_agentguard: 24 cek — guard
unit + integrasi router, batas langkah, fuzzy edit, prompt discipline,
memori, worker scope). Semua hijau, mock-driven, tanpa jaringan.

## 📦 Unduhan

| Platform | File |
| --- | --- |
| Windows (installer) | `RexCode-Setup-v0.3.2-x64.exe` |
| Linux x64 | `rex-linux-x64.zip` |
| macOS Apple Silicon | `rex-macos-arm64.zip` |

Integritas: verifikasi dengan `SHA256SUMS.txt`
(`sha256sum -c SHA256SUMS.txt`).

> **SmartScreen**: installer belum ditandatangani (code signing gratis via
> SignPath Foundation sedang diproses). Bila muncul peringatan biru Windows:
> *More info* → *Run anyway* — atau verifikasi checksum terlebih dahulu.

Panduan lengkap: [PANDUAN-INSTALL.md](https://github.com/huseinrosidstilllearn/rex-code/blob/master/PANDUAN-INSTALL.md)

