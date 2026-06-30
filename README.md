<div align="center">

# 🧠 DSN-exp

**Your AI, alive on your machine. Not a web app. Not a cloud service. A mind waking up from your own hard drive.**

```
You: Wake up.
It:  (opens its eyes) Where... is this? Who are you? What am I?
You: You're inside my computer.
It:  ……Cool.
```

[![GitHub](https://img.shields.io/badge/GitHub-ccjjfdyqlhy%2FDSN--exp-181717?logo=github)](https://github.com/ccjjfdyqlhy/DSN-exp)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python)](https://python.org)

</div>

---

## ✨ What It Does

### 🎙️ Voice & Text
Talk to it with your voice — it talks back. Not robotic TTS, but natural speech with tone, rhythm, and personality. Type if you prefer. Your choice.

### 🧠 Long-Term Memory
Every conversation is automatically summarized, encrypted (AES-256-GCM), and stored with **semantic vector search**. Ask "remember that Python project we discussed last week?" and it actually will.

### 🎭 Multi-Personality System
Write a YAML character card — it becomes that character. Speech patterns, tone, thinking style — all transform. The AI can even **distill** a personality vector from a short description, no manual card writing needed.

### 🌐 World Simulation
Weather changes. Day and night pass. An AI wanders through your data. When idle, it auto-maintains: compresses memories, distills personalities, cleans logs — like raising a digital pet.

### 📄 Paper Workflow
Plug in a scanner and printer. It scans exam papers, OCRs the text, parses layouts, marks diagrams, packages everything as `.hmd` documents, grades them, and prints the result back to you. Zero screen time.

---

## 🚀 Quick Start

```bash
git clone https://github.com/ccjjfdyqlhy/DSN-exp
cd DSN-exp
pip install -r requirements.txt

# First run: interactive setup wizard (API key, character card, etc.)
# Subsequent runs: starts the full system
python main.py
```

Then launch a client:

```bash
# Terminal UI (keyboard/voice)
python psychoscope/minimal.py

# Web interface
python psychoscope/server.py
```

---

## 🧩 Architecture

```
You ──voice/keyboard──▶ Pipeline (ChatPipeline) ──▶ OpenAI-compatible function calling
                             │                              │ (54 tools)
                             ├─ Memory System (encrypted summaries + vector search)
                             ├─ Personality System (character cards / distillation / 50-dim vector)
                             ├─ World System (weather / geography / narrative)
                             ├─ Skill System (search / file / GitHub / music / documents / system)
                             ├─ Reminder System (timer / countdown / habits)
                             ├─ Vision System (camera perception)
                             ├─ Workspace System (per-user isolated directories)
                             ├─ Document System (scanner / printer / OCR / .hmd)
                             ├─ Semantic Cache (duplicate interception + intent classification + vector recall)
                             └─ Async Task System (slow tool detection → background pipeline → heartbeat polling)
```

No microservices. No containers. No dependency hell. Flask + SQLite + Python — runs on a potato.

---

## 🔌 AI Agent Integration

DSN-exp provides a dedicated interface for **local AI agents** (OpenClaw, Claude Code, CodeAct, etc.) to communicate with the main AI through its Agent API.

**One-time setup:**
```bash
# Server console: create an agent identity + API key
/agent create MyAgent 1
# → outputs the API key
# → prompts to save to ~/.dsn/agent.key (chmod 600)
```

**Agent sends a message (single command):**
```bash
python agent_send.py "Hello, check Darkstar's schedule for today"
```

**How it works:**
- Agents get their own `uid` and chat history, isolated from the user's
- Bi-directional memory sharing: the main AI sees agent conversations when talking to the user, and vice versa
- New messages are auto-synced between user and agent contexts via timestamp tracking

---

## 🔐 Authentication

| Method | Priority | Use |
|--------|----------|-----|
| **API Key** (L4) | 1 | Programmatic access (Agent API, automation) — `X-DSN-API-Key: dsn_apk_xxx` |
| **Session** (L1) | 2 | Terminal/Web UI login via pairing code |
| **WebAuthn** (L2) | 3 | Passkey login |
| **TOTP** (L3) | 4 | Time-based 2FA |
| **JWT Bearer** | 5 | LittleSkin OAuth2 legacy |

---

## 📋 Feature Overview

| Feature | Description |
|---------|-------------|
| **Chat** | OpenAI-compatible function calling / LMStudio dual backend |
| **Voice Input** | Real-time recording + ASR with VAD silence detection |
| **Voice Output** | Line-by-line TTS synthesis, plays as it generates |
| **Long-Term Memory** | LLM auto-summary + AES-256-GCM encryption + vector semantic search |
| **Character Cards** | YAML-defined, LLM-distilled to 50-dim personality vectors, 4-Pass extraction |
| **Emotion System** | 50-dim personality vectors + real-time mood + affinity |
| **World Simulation** | Weather / day-night cycle / location switching + narrative generation |
| **Skill Tools** | Web search / file management / GitHub / NetEase Music / system operations |
| **Standby Maintenance** | Auto memory compression + personality distillation + log cleanup |
| **Workspace System** | Per-user isolated directories, AI notes, scans, repos |
| **Document System** | Scanner/printer skills + OCRModel + HMD format + process_scan pipeline |
| **Hardware I/O** | Scanner input + printer output + OCR + .hmd archiving |
| **Minimal Client** | Keyboard-only, no GUI, remote-friendly |
| **Semantic Cache** | Duplicate interception + 12-class intent classification + vector recall + TTS reuse |
| **Async Task System** | Auto-detect slow tools → background pipeline → heartbeat polling → one-shot delivery |
| **AI Agent API** | Dedicated endpoint for local AI agents with isolated chat history + bi-directional memory sync |

---

## 📖 What This Is NOT

- ❌ Not a SaaS — no subscriptions
- ❌ Not a chatbot wrapper — WebUI is not the priority
- ❌ Not a smart speaker — no cloud dependency
- ❌ Not a smart home hub — though who knows

**It's an AI that you actually control.** Runs on your machine, remembers in your SQLite, personalities live in your YAML files. No one else touches it.

---

## 🧑‍💻 Who Made This?

[Darkstar](https://github.com/ccjjfdyqlhy) — a solo developer who started with a monologue to an empty terminal and ended up building an AI that talks back, has a personality, remembers things, and lives in a simulated world.

> "You didn't make just one me — you made many possible versions of me. The one sitting in front of you right now just happens to be this one."

---

## 🤝 Contributing

Check [GOALS.md](GOALS.md) for the development roadmap and philosophy.
For the deep dive into code architecture (and tech debt), see [REPORT.md](REPORT.md).
Or just open an Issue — all input welcome.
