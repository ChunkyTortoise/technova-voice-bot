# TechNova Voice AI Customer Service Bot

A real-time Voice AI demo showcasing a complete voice pipeline — speech-to-text (STT), LLM reasoning via Claude, and text-to-speech (TTS) — for an e-commerce electronics store.

## Architecture

```
Browser (OGG/Opus) → WebSocket → FFmpeg (OGG→PCM16) → Silero VAD (ONNX)
→ Deepgram Nova-3 STT → Claude Sonnet LLM → Sentence buffer
→ Deepgram Aura-2 TTS → PCM16 → WebSocket → Browser AudioContext
```

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | FastAPI + uvicorn | Async WebSocket support |
| Audio transcoding | FFmpeg (OGG input) | Streamable OGG/Opus, not WebM |
| VAD | Silero VAD (ONNX) | ~20 MB, no PyTorch dependency |
| STT | Deepgram Nova-3 | Sub-300ms streaming, best WER |
| LLM | Claude claude-sonnet-4-6 | 1.19s TTFB, ~3s total round-trip |
| TTS | Deepgram Aura-2 | ~90ms TTFB, same API key as STT |
| Session state | Redis | Survives Render spin-down |
| Database | SQLite (aiosqlite) | No expiry (unlike Render Postgres) |

## Quick Start

### Prerequisites
- Python 3.12+
- FFmpeg (`brew install ffmpeg` or `apt install ffmpeg`)
- Redis (`brew install redis` or Docker)
- API keys: Deepgram, Anthropic

### Local Development

```bash
git clone ...
cd technova-voice-bot

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # for tests

# Configure
cp .env.example .env
# Edit .env: add DEEPGRAM_API_KEY and ANTHROPIC_API_KEY

# Start Redis
redis-server &

# Run
uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000
```

### Docker (single command)

```bash
cp .env.example .env
# Edit .env with your API keys

docker-compose up
# Open http://localhost:8000
```

### Deploy to Render

1. Push this repo to GitHub
2. Create new Render Blueprint → connect repo → `render.yaml` handles the rest
3. Set `DEEPGRAM_API_KEY` and `ANTHROPIC_API_KEY` in Render dashboard
4. The `CORS_ORIGINS` is pre-set to your Render URL in `render.yaml`

## Architecture Decisions (Audit Fixes Applied)

| Fix | Issue | Solution |
|-----|-------|----------|
| #1 | WebM/FFmpeg pipe unreliable | Use OGG/Opus — streamable format |
| #2 | PyTorch OOM on Render free | ONNX Silero VAD — ~20 MB not ~400 MB |
| #3 | PostgreSQL 30-day expiry | SQLite — no expiry, persists on mounted volume |
| #4 | Session lost on refresh | localStorage session_id persistence |
| #5 | Single-stage Dockerfile | Multi-stage build — builder + runtime |
| #6 | CORS_ORIGINS=* insecure | Default to localhost; set Render URL in render.yaml |
| #7 | Sentence split on $19.99 | Regex with negative lookbehind for digits + abbreviations |
| #8 | No rate limiting | 5 concurrent WebSocket connections per IP |
| #9 | Lock TTL too short | 30s asyncio.Lock per session + Redis heartbeat |
| #10 | sampleRate constraint ignored | Removed — FFmpeg handles resampling |
| #11 | render.yaml Redis reference broken | Redis service defined in render.yaml |
| #12 | AudioContext.close() on barge-in | GainNode mute/unmute — no context recreation |
| #13 | Test deps missing | requirements-dev.txt separate from requirements.txt |
| #14 | Latency budget ignores buffer | 500ms sentence flush timeout documented |
| #15 | No structured logging | structlog with JSON in production |
| #16 | Order demo invisible | UI hint: "Try order TN-10023 or TN-10042" |
| #18 | Render 75s WS idle timeout | Client sends ping every 30s |

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=app --cov-report=html
```

## Latency Budget

| Stage | Typical Latency |
|-------|----------------|
| VAD endpointing | 700ms |
| Deepgram STT final | ~300ms |
| Claude TTFB | ~1,190ms |
| First sentence ready | variable (+ flush timeout max 500ms) |
| Deepgram TTS TTFB | ~90ms |
| **Total to first audio** | **~2.3–3.3s** |

> Success criteria: <3s to first audio byte, measured on short responses. Long LLM
> responses flush the sentence buffer after 500ms (FIX #14).
