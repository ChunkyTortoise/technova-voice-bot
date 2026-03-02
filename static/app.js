'use strict';

// ── Configuration ──────────────────────────────────────────────────────────
const SESSION_KEY = 'technova_session_id';  // FIX #4: localStorage key
const WS_PING_INTERVAL = 30000;             // FIX #18: 30s keepalive
const WS_MAX_RETRIES = 3;

// ── State ───────────────────────────────────────────────────────────────────
let sessionId = null;
let ws = null;
let wsRetries = 0;
let wsPingTimer = null;
let mediaRecorder = null;
let audioStream = null;
let audioPlayer = null;
let analyserNode = null;
let animFrameId = null;
let isListening = false;

// ── DOM refs ────────────────────────────────────────────────────────────────
const micBtn       = document.getElementById('mic-btn');
const statusText   = document.getElementById('status-text');
const transcriptEl = document.getElementById('transcript');
const connStatus   = document.getElementById('conn-status');
const waveformCanvas = document.getElementById('waveform');
const waveformCtx  = waveformCanvas.getContext('2d');

// ── PCM16 helper ─────────────────────────────────────────────────────────────
function pcm16ToFloat32(buffer) {
  const int16 = new Int16Array(buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768.0;
  }
  return float32;
}

// ── AudioPlayer ──────────────────────────────────────────────────────────────
class AudioPlayer {
  constructor() {
    this.ctx = new AudioContext({ sampleRate: 24000 });
    this.gainNode = this.ctx.createGain();
    this.gainNode.connect(this.ctx.destination);
    this.nextStartTime = 0;
  }

  playChunk(pcm16Buffer) {
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
    const floatData = pcm16ToFloat32(pcm16Buffer);
    const audioBuffer = this.ctx.createBuffer(1, floatData.length, 24000);
    audioBuffer.getChannelData(0).set(floatData);

    const source = this.ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.gainNode);

    const startTime = Math.max(this.ctx.currentTime + 0.01, this.nextStartTime);
    source.start(startTime);
    this.nextStartTime = startTime + audioBuffer.duration;
  }

  // FIX #12: Use gain node to silence in-flight audio (not AudioContext.close())
  interrupt() {
    this.gainNode.gain.cancelScheduledValues(this.ctx.currentTime);
    this.gainNode.gain.setValueAtTime(0, this.ctx.currentTime);
    this.nextStartTime = this.ctx.currentTime + 0.05;
    // Restore gain after brief ramp
    this.gainNode.gain.setValueAtTime(1, this.ctx.currentTime + 0.05);
  }
}

// ── Session management ────────────────────────────────────────────────────────
async function initSession() {
  // FIX #4: Try to restore existing session from localStorage
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) {
    try {
      const res = await fetch(`/api/sessions/${existing}/history`);
      if (res.ok) {
        const data = await res.json();
        if (data.messages && data.messages.length > 0) {
          restoreHistory(data.messages);
          setStatus('Session restored. Click mic to continue.');
          return existing;
        }
      }
    } catch (e) {
      console.warn('Failed to restore session:', e);
    }
  }

  // Create new session
  const res = await fetch('/api/sessions', { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  const data = await res.json();
  // FIX #4: Persist session_id to localStorage
  localStorage.setItem(SESSION_KEY, data.session_id);
  return data.session_id;
}

function restoreHistory(messages) {
  transcriptEl.innerHTML = '';
  for (const msg of messages) {
    addMessage(msg.role === 'user' ? 'user' : 'bot', msg.content);
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connectWebSocket(sid) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${proto}//${location.host}/ws/audio/${sid}`;

  ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    wsRetries = 0;
    connStatus.textContent = 'Connected';
    connStatus.className = 'conn-status connected';
    setStatus('Ready — click the microphone to speak');
    // FIX #18: Start keepalive ping every 30s
    startKeepalive();
  };

  ws.onclose = (evt) => {
    connStatus.textContent = `Disconnected (${evt.code})`;
    connStatus.className = 'conn-status error';
    stopKeepalive();
    if (wsRetries < WS_MAX_RETRIES) {
      wsRetries++;
      setTimeout(() => connectWebSocket(sid), 2000 * wsRetries);
    } else {
      setStatus('Connection lost. Refresh to reconnect.');
    }
  };

  ws.onerror = () => {
    connStatus.textContent = 'Connection error';
    connStatus.className = 'conn-status error';
  };

  ws.onmessage = (evt) => {
    if (evt.data instanceof ArrayBuffer) {
      // Binary = TTS audio PCM16
      if (audioPlayer) {
        audioPlayer.playChunk(evt.data);
      }
    } else {
      // Text = JSON control event
      try {
        const event = JSON.parse(evt.data);
        handleEvent(event);
      } catch (e) {
        console.warn('Invalid event JSON:', evt.data);
      }
    }
  };
}

// FIX #18: WebSocket keepalive ping every 30 seconds
function startKeepalive() {
  stopKeepalive();
  wsPingTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }));
    }
  }, WS_PING_INTERVAL);
}

function stopKeepalive() {
  if (wsPingTimer) {
    clearInterval(wsPingTimer);
    wsPingTimer = null;
  }
}

// ── Event handler ─────────────────────────────────────────────────────────────
function handleEvent(event) {
  switch (event.type) {
    case 'transcript':
      addMessage('user', event.text);
      setStatus('Processing your request...');
      break;
    case 'bot_start':
      setStatus('Speaking...', true);
      break;
    case 'bot_end':
      setStatus('Ready — click the microphone to speak');
      break;
    case 'error':
      setStatus(`Error: ${event.message}`);
      console.error('Server error:', event.message);
      break;
    case 'pong':
      // FIX #18: Keepalive acknowledged
      break;
    default:
      console.debug('Unknown event:', event.type);
  }
}

// ── Microphone & Recording ────────────────────────────────────────────────────
async function startListening() {
  if (!audioPlayer) audioPlayer = new AudioPlayer();

  // FIX #10: Do NOT request sampleRate - Chrome/Firefox ignore it.
  // Resampling happens in FFmpeg on the server side.
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      // No sampleRate constraint (FIX #10)
    },
  });

  audioStream = stream;

  // Set up waveform analyser
  const actx = new AudioContext();
  const source = actx.createMediaStreamSource(stream);
  analyserNode = actx.createAnalyser();
  analyserNode.fftSize = 256;
  source.connect(analyserNode);
  drawWaveform();

  // FIX #1: Use OGG/Opus for reliable pipe streaming (not WebM)
  const mimeType = MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
    ? 'audio/ogg;codecs=opus'
    : 'audio/webm;codecs=opus';  // fallback if OGG not supported

  mediaRecorder = new MediaRecorder(stream, {
    mimeType,
    audioBitsPerSecond: 32000,
  });

  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0 && ws && ws.readyState === WebSocket.OPEN) {
      e.data.arrayBuffer().then((buf) => {
        ws.send(buf);
        // FIX #12: Interrupt any playing bot audio (barge-in)
        if (audioPlayer) audioPlayer.interrupt();
        // Notify server of interrupt
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'interrupt' }));
        }
      });
    }
  };

  mediaRecorder.start(100);  // 100ms chunks
  isListening = true;
  micBtn.className = 'listening';
  setStatus('Listening... click again to stop', true);
}

function stopListening() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (audioStream) {
    audioStream.getTracks().forEach((t) => t.stop());
    audioStream = null;
  }
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
    // Clear waveform
    waveformCtx.clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);
  }
  isListening = false;
  micBtn.className = '';
  setStatus('Processing... please wait');
}

// ── Waveform visualizer ───────────────────────────────────────────────────────
function drawWaveform() {
  if (!analyserNode) return;
  animFrameId = requestAnimationFrame(drawWaveform);

  const bufferLength = analyserNode.frequencyBinCount;
  const data = new Uint8Array(bufferLength);
  analyserNode.getByteFrequencyData(data);

  const W = waveformCanvas.width = waveformCanvas.offsetWidth;
  const H = waveformCanvas.height = 60;
  waveformCtx.clearRect(0, 0, W, H);

  const barW = (W / bufferLength) * 2.5;
  let x = 0;

  for (let i = 0; i < bufferLength; i++) {
    const barH = (data[i] / 255) * H;
    const alpha = 0.4 + (data[i] / 255) * 0.6;
    waveformCtx.fillStyle = `rgba(96, 180, 244, ${alpha})`;
    waveformCtx.fillRect(x, H - barH, barW, barH);
    x += barW + 1;
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function setStatus(text, active = false) {
  statusText.textContent = text;
  statusText.className = active ? 'active' : '';
}

function addMessage(role, text) {
  const emptyState = transcriptEl.querySelector('.empty-state');
  if (emptyState) emptyState.remove();

  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerHTML = `
    <div class="label">${role === 'user' ? 'You' : 'TechNova AI'}</div>
    <div>${escapeHtml(text)}</div>
  `;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Event listeners ───────────────────────────────────────────────────────────
micBtn.addEventListener('click', async () => {
  if (!sessionId) return;
  if (isListening) {
    stopListening();
  } else {
    try {
      micBtn.className = 'disabled';
      await startListening();
    } catch (err) {
      micBtn.className = '';
      setStatus(`Microphone error: ${err.message}`);
      console.error('getUserMedia error:', err);
    }
  }
});

// ── Initialization ────────────────────────────────────────────────────────────
(async () => {
  try {
    setStatus('Initializing...');
    sessionId = await initSession();
    connectWebSocket(sessionId);
  } catch (err) {
    setStatus(`Initialization failed: ${err.message}`);
    connStatus.textContent = 'Failed to connect';
    connStatus.className = 'conn-status error';
    console.error('Init error:', err);
  }
})();
