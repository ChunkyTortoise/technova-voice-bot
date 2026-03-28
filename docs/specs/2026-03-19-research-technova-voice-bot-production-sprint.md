---
research_for: 2026-03-19-feature-technova-voice-bot-production-sprint-spec
date: 2026-03-19
---

# Research: technova-voice-bot Production Sprint

## Current State Audit

- **Test count**: 26 passing
- **Test files**: 3 — `test_llm_orchestrator.py` (7), `test_routes.py` (11), `test_session_manager.py` (8)
- **Coverage estimate**: ~25% — session_manager, routes_rest, and llm_orchestrator.split_sentences are covered; audio_pipeline, ws_manager, stt_client, tts_client, mock_clients, routes_websocket have zero test coverage
- **Demo mode**: Active when `DEEPGRAM_API_KEY` or `ANTHROPIC_API_KEY` is missing (both checked at module load in `routes_websocket.py` line 19 and `main.py` line 18)
- **Deployment status**: NOT live. render.yaml and Dockerfile are complete and correct. Blocked by Render requiring a credit card even for free-tier blueprints.
- **.env.example**: Exists at repo root, complete, documents all env vars with placeholder values and inline FIX comments.

## Module Inventory

### `app/audio_pipeline.py`
**What it does**: Receives OGG/Opus audio from the browser WebSocket, spawns an FFmpeg subprocess to transcode OGG → PCM16 at 16 kHz mono, reads output in 512-sample (1024-byte) frames, runs each frame through Silero VAD (ONNX), accumulates speech into a buffer, and fires `on_speech_end(pcm_bytes)` after 700ms of post-speech silence.

Key classes/functions:
- `_vad_probability(pcm_bytes)` — runs ONNX inference, returns float 0–1; returns 1.0 if `onnxruntime` not installed
- `AudioPipeline.__init__` — stores `session_id`, `on_speech_end` callback
- `AudioPipeline.start()` — spawns FFmpeg with `subprocess.Popen`, creates `_read_pcm` asyncio Task
- `AudioPipeline.feed_chunk(chunk)` — writes OGG bytes to FFmpeg stdin
- `AudioPipeline._read_pcm()` — runs in executor to avoid blocking event loop, reads 1024-byte frames
- `AudioPipeline._process_frame(pcm_chunk)` — VAD state machine: detects speech start/end, fires callback
- `AudioPipeline.stop()` — cancels task, terminates FFmpeg with 2s timeout, kills if needed

**Current test coverage**: 0 tests

### `app/ws_manager.py`
**What it does**: Manages the mapping between `session_id` strings and live FastAPI `WebSocket` objects. Tracks per-IP connection counts for rate limiting. Provides `send_audio` (bytes) and `send_event` (JSON text) helpers.

Key class: `WebSocketManager` (singleton `manager`)
- `connect(session_id, websocket)` — calls `websocket.accept()`, stores in `_connections`
- `register_ip(session_id, ip)` — populates `_session_ip` and `_ip_sessions` dicts
- `get_connection_count_for_ip(ip)` — returns len of IP's session set
- `disconnect(session_id)` — removes from all dicts
- `send_audio(session_id, chunk)` — `ws.send_bytes(chunk)`, swallows exceptions
- `send_event(session_id, event)` — `ws.send_text(json.dumps(event))`, swallows exceptions
- `is_connected(session_id)` — bool lookup

**Current test coverage**: 0 tests

### `app/stt_client.py`
**What it does**: Wraps the Deepgram SDK's async WebSocket live transcription client (Nova-3, `linear16`, 16 kHz, punctuate+smart_format). SDK import is deliberately deferred to `connect()` to avoid module-level failures across SDK versions (requires `deepgram-sdk>=3.7.0,<4.0.0`). Fires `on_transcript(text)` callback only on final transcripts.

Key class: `DeepgramSTTClient`
- `__init__(on_transcript)` — stores callback
- `connect()` — deferred SDK import, sets up `LiveOptions`, registers event handler, calls `_connection.start(options)`
- `send_audio(pcm_chunk)` — `_connection.send(pcm_chunk)` if connected
- `disconnect()` — `_connection.finish()`, sets `_connected = False`

**Current test coverage**: 0 tests

### `app/tts_client.py`
**What it does**: Calls Deepgram Aura-2 REST streaming TTS endpoint via httpx, streams back PCM16 chunks (no container) at 24 kHz. Supports cancellation via `_cancelled` flag for barge-in.

Key class: `DeepgramTTSClient`
- `__init__(on_audio_chunk)` — stores callback
- `synthesize(text)` — POST to `https://api.deepgram.com/v1/speak`, streams `aiter_bytes(4096)`, calls `on_audio_chunk(chunk)` per chunk, checks `_cancelled` between chunks
- `cancel()` — sets `_cancelled = True`

**Current test coverage**: 0 tests

### `app/mock_clients.py`
**What it does**: Provides demo-mode replacements for all three real clients.
- `MockSTTClient.transcribe_stream(audio_chunks)` — consumes chunks, returns one of 3 canned transcripts after 0.5s
- `MockTTSClient.synthesize(text)` — returns a minimal valid WAV header (0-byte audio body) after 0.1s
- `MockLLMOrchestrator.generate_response(transcript, session_id)` — cycles through 5 canned responses; `generate_response_stream` yields word by word with 50ms delay

Note: `MockSTTClient` is not used in the live WebSocket route — `routes_websocket.py` uses a direct `await on_transcript_received("Demo user speech detected")` call in demo mode instead. `MockTTSClient` and `MockLLMOrchestrator` are used.

**Current test coverage**: 0 tests

### `app/llm_orchestrator.py`
**What it does**: Streams Claude claude-sonnet-4-6 responses with sentence-boundary splitting and a 500ms flush timeout. Maintains conversation history (last 20 messages from Redis). Uses per-session asyncio.Lock (FIX #9).

Notable: `split_sentences(text)` has a dedicated test file (`test_llm_orchestrator.py`, 7 tests). The streaming `generate_response()` function itself has no tests.

**Current test coverage**: 7 tests (all for `split_sentences`) — `generate_response()` is untested

### `app/routes_websocket.py`
**What it does**: The main `audio_websocket` endpoint. Validates session_id as UUID, rate-limits by IP via `ws_manager`, verifies session exists in Redis, starts `AudioPipeline`, handles binary audio chunks and JSON control messages (ping/interrupt/barge-in).

**Current test coverage**: 0 direct tests (covered indirectly only via `test_routes.py` which tests REST routes via `app_client` fixture, not the WebSocket endpoint)

## Demo Mode Analysis

Demo mode activates automatically when either `DEEPGRAM_API_KEY` or `ANTHROPIC_API_KEY` is an empty string (the default in `app/config.py`).

The check is at module level:
```python
DEMO_MODE = not settings.DEEPGRAM_API_KEY or not settings.ANTHROPIC_API_KEY
```

When `DEMO_MODE = True`:
- `MockLLMOrchestrator` and `MockTTSClient` are instantiated as module-level singletons in `routes_websocket.py`
- On speech end: instead of creating a `DeepgramSTTClient`, the code directly calls `on_transcript_received("Demo user speech detected")`
- LLM: `_mock_llm.generate_response(text, session_id)` — cycles through 5 canned text responses
- TTS: `_mock_tts.synthesize(sentence)` — returns silent WAV bytes
- The `AudioPipeline` and `WebSocketManager` still run normally in demo mode — all the WebSocket plumbing is exercised

Demo mode works end-to-end without Redis if it is running (Redis is still required; it is not mocked in production startup). The `init_db()` call creates the SQLite DB on startup with no external dependencies.

## .env.example Status

`.env.example` EXISTS at `/Users/cave/Projects/technova-voice-bot/.env.example`. It is complete and documents:
- `DEEPGRAM_API_KEY` (placeholder)
- `ANTHROPIC_API_KEY` (placeholder)
- `DATABASE_URL` (SQLite default)
- `REDIS_URL` (localhost default)
- `CORS_ORIGINS` (localhost default, Render URL commented out)
- `ENVIRONMENT`, `VERSION`
- `SESSION_TTL_SECONDS`, `LOCK_TTL_SECONDS`
- `MAX_CONCURRENT_WS_PER_IP`
- `SENTENCE_FLUSH_TIMEOUT_MS`
- `SILERO_VAD_PATH` (commented out, optional)

Missing from `.env.example`: `ADMIN_API_KEY`, `OPERATOR_API_KEY`, `VIEWER_API_KEY` — these exist in `app/config.py` and are used by `routes_rest.py` for report endpoint auth. They default to empty strings.

## render.yaml / Dockerfile Analysis

### render.yaml
- Web service: `technova-voice-bot`, Dockerfile runtime, free plan
- Health check: `GET /api/health`
- `DEEPGRAM_API_KEY`: `sync: false` — must be set manually in Render dashboard
- `ANTHROPIC_API_KEY`: `sync: false` — must be set manually in Render dashboard
- `REDIS_URL`: auto-populated from `technova-redis` Redis service via `fromService`
- `DATABASE_URL`: SQLite (persistent on 1GB disk mounted at `/app/data`)
- `CORS_ORIGINS`: pre-set to `https://technova-voice-bot.onrender.com`
- Redis service `technova-redis`: free plan, `ipAllowList: []`
- Note: `ADMIN_API_KEY`, `OPERATOR_API_KEY`, `VIEWER_API_KEY` not in render.yaml — will default to empty (report endpoints will be accessible to anyone with no key)

### Dockerfile
- Multi-stage build (FIX #5): builder + runtime
- Runtime installs FFmpeg via apt
- Copies `app/` and `static/` only — no test deps in image
- Exposes 8000, runs uvicorn
- Health check: urllib.request to `http://localhost:8000/api/health`
- Silero VAD ONNX model: auto-downloaded at runtime on first voice session if missing; stored at `/app/data/silero_vad.onnx` (on the 1GB mounted disk)

## Test Gap Analysis

### Currently tested (26 tests)
| File | Tests | What's covered |
|------|-------|---------------|
| `test_llm_orchestrator.py` | 7 | `split_sentences()` edge cases only |
| `test_routes.py` | 11 | REST endpoints: health, sessions, history, ROI auth, reports CRUD |
| `test_session_manager.py` | 8 | Redis create/get/append, locks, heartbeat |

### Not tested (0 tests)
| Module | Key behaviors needing coverage |
|--------|-------------------------------|
| `audio_pipeline.py` | FFmpeg spawn, OGG feed, VAD state machine (speech start/end/silence), stop/cleanup |
| `ws_manager.py` | connect/disconnect, IP counting, send_audio/send_event, is_connected |
| `stt_client.py` | connect with mocked SDK, send_audio gating, disconnect, deferred import |
| `tts_client.py` | synthesize (mock httpx), cancel mid-stream, empty text guard |
| `mock_clients.py` | MockTTSClient returns WAV bytes, MockLLMOrchestrator cycles responses, MockSTTClient |
| `routes_websocket.py` | Full WebSocket lifecycle via TestClient |
| `llm_orchestrator.generate_response()` | Streaming with mock Anthropic client |

### Coverage delta needed
- 26 tests → 60+ tests = 34+ new tests required
- Highest-ROI targets: `audio_pipeline.py` (~15 tests), `ws_manager.py` (~10 tests), `tts_client.py` (~8 tests), `stt_client.py` (~6 tests), `mock_clients.py` (~5 tests)

## Mock Strategy

### FFmpeg (audio_pipeline.py)
`subprocess.Popen` is the only external dependency. Mock strategy:
```python
from unittest.mock import patch, MagicMock
mock_proc = MagicMock()
mock_proc.poll.return_value = None
mock_proc.stdin = MagicMock()
mock_proc.stdout = MagicMock()
mock_proc.stdout.read.return_value = b"\x00" * 1024  # silent PCM frame
with patch("app.audio_pipeline.subprocess.Popen", return_value=mock_proc):
    ...
```
For `_vad_probability`, patch at module level to return controlled floats:
```python
with patch("app.audio_pipeline._vad_probability", return_value=0.9):  # speech
    ...
```
The `_read_pcm` task uses `loop.run_in_executor` for `stdout.read` — this is testable by making `mock_proc.stdout.read` return bytes then `b""` to signal EOF.

### WebSocket (ws_manager.py)
Use `unittest.mock.AsyncMock` for the FastAPI `WebSocket` object:
```python
mock_ws = AsyncMock()
mock_ws.accept = AsyncMock()
mock_ws.send_bytes = AsyncMock()
mock_ws.send_text = AsyncMock()
```
`WebSocketManager` has no external dependencies beyond the WebSocket object itself — it is purely in-memory. No patching of Redis or DB needed for ws_manager tests.

### Deepgram STT SDK (stt_client.py)
The SDK import is deferred inside `connect()`. Patch at the import level:
```python
with patch.dict("sys.modules", {
    "deepgram": MagicMock(),
    "deepgram.DeepgramClient": MagicMock(),
    ...
}):
    ...
```
Or more cleanly, patch the `connect()` method's internal import path:
```python
with patch("app.stt_client.settings") as mock_settings, \
     patch("builtins.__import__", side_effect=mock_import):
    ...
```
Simplest approach: inject a mock `_connection` directly after instantiation and set `_connected = True`.

### httpx TTS (tts_client.py)
Patch `httpx.AsyncClient`:
```python
with patch("app.tts_client.httpx.AsyncClient") as MockClient:
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_bytes = AsyncMock(return_value=async_gen([b"chunk1", b"chunk2"]))
    MockClient.return_value.__aenter__.return_value.stream.return_value.__aenter__.return_value = mock_response
    ...
```

### mock_clients.py
No external dependencies — test directly with `asyncio.run` or `@pytest.mark.asyncio`. Check response cycling, WAV header bytes, stream word-by-word delivery.

## Case Study Outline

Key architectural decisions worth documenting:

1. **Why WebSocket over HTTP polling**: Voice AI requires sub-200ms round-trips. HTTP polling adds 200–500ms per cycle. WebSocket keeps a persistent connection and enables streaming in both directions simultaneously.

2. **Why OGG/Opus over WebM**: WebM requires seeking (non-streamable). OGG is a streamable container — FFmpeg can accept partial OGG chunks via stdin pipe without needing to seek. FIX #1 resolved a fundamental reliability issue with the original WebM approach.

3. **Why ONNX Silero VAD over PyTorch**: PyTorch's base image is ~400 MB. On Render free tier (512 MB RAM), loading PyTorch for VAD alone would OOM. ONNX runtime with the Silero model is ~20 MB total. FIX #2 made the free-tier deploy viable.

4. **Why Deepgram over Whisper**: Sub-300ms streaming STT latency. Whisper requires full audio before transcription (batch, not streaming). Deepgram Nova-3 supports real-time streaming via WebSocket with interim results.

5. **Why SQLite over PostgreSQL**: Render's free-tier PostgreSQL databases expire after 30 days (FIX #3). SQLite on a mounted 1 GB disk has no expiry. For a single-process voice bot with moderate traffic, SQLite with aiosqlite provides adequate performance.

6. **Why per-session asyncio.Lock**: The LLM streaming response and TTS pipeline run across multiple awaits. Without a lock, two concurrent voice turns for the same session would interleave. A lock per session (not a global lock) avoids blocking unrelated sessions. FIX #9.

7. **Demo mode philosophy**: The demo activates automatically on missing API keys — no code changes needed. This means the Render deploy works immediately after `git push`, visible to portfolio visitors before API keys are configured.

8. **Sentence buffering for TTS**: LLMs stream tokens, not sentences. TTS APIs work best on complete sentences (prosody, punctuation handling). The pipeline buffers tokens until a sentence boundary, then fires TTS per sentence. FIX #14 adds a 500ms flush timeout so long clauses don't stall the audio.

## Notes

- `app/utils/logging_config.py` is a structlog wrapper — not a testing target, no complex logic
- `app/adapters/` and `app/scripts/` directories exist but were not inventoried; not relevant to this sprint
- The `static/` directory has a complete PWA frontend (`index.html`, `app.js`, `manifest.json`, icons) — no changes needed for this sprint
- `ADMIN_API_KEY`, `OPERATOR_API_KEY`, `VIEWER_API_KEY` need to be added to `.env.example` — currently missing
- Render free tier has a 75-second WebSocket idle timeout; FIX #18 handles this with client-side pings every 30s
- The `data/` directory in the Docker image is created by `RUN mkdir -p data` but the Silero VAD model downloads at runtime on first use — first voice session will have a cold start delay on a fresh deploy
