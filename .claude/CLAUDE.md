# TechNova Voice Bot

## Stack
FastAPI | WebSockets | FFmpeg | Silero-ONNX (VAD) | Deepgram (STT) | Anthropic (claude-sonnet-4-6) | Redis | SQLite | Python

## Architecture
Real-time voice pipeline: OGG → FFmpeg → Silero VAD → Deepgram STT → Claude → TTS → WebSocket client. Demo mode auto-activates when `DEEPGRAM_API_KEY` missing (mocks STT). PWA manifest included.
- `app/main.py` — FastAPI + WebSocket entry point
- `app/pipeline/` — VAD, STT, LLM, TTS stages
- `app/demo/` — demo mode mock responses
- `Dockerfile` + `render.yaml` — Render deploy blueprint

## Deploy
Not yet deployed. Target: Render. URL will be `https://technova-voice-bot.onrender.com`. Guide: `output/technova-deploy-guide.md`. Needs Deepgram free tier ($200 credit).

## Test
```pytest tests/  # 26 tests```

## Key Env
DEEPGRAM_API_KEY, ANTHROPIC_API_KEY, REDIS_URL
