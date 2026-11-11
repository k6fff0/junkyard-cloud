# voice-bridge (phone calls with the assistant)

Joins a Twilio call to the OpenAI Realtime API. The voice model chats directly and hands anything that needs
memory or action to the n8n assistant (`ask_assistant`), so "remind me tomorrow at 9" works on a call too.

- `Voice Call (AI)` in n8n places the call with TwiML `<Connect><Stream url="wss://<PUBLIC_HOST>/stream/<secret>">`
  and an optional `context` parameter that the assistant says first ("your backup failed")
- calls to the Twilio number are answered only from `ALLOWED_CALLER`
- noise: phone noise filter, end of turn by meaning (`semantic_vad`), and the assistant is cut off only when the
  caller talks over it for `BARGE_IN_MS`; the model is told how much of its answer was really heard
- the path secret is the protection (Twilio cannot pass Cloudflare Access); the access log is off so the secret
  is never written to logs

Settings: `OPENAI_API_KEY`, `STREAM_SECRET`, `N8N_SECRET`, `N8N_URL`, `PUBLIC_HOST`, `ALLOWED_CALLER`,
`ASSISTANT_NAME`, `OWNER_NAME`, `OWNER_CALL_NAME`, `CALL_LANGUAGE`, `REALTIME_MODEL` (`gpt-realtime-2.1-mini`),
`REALTIME_VOICE`, `MAX_CALL_SECONDS`, `NOISE_REDUCTION`, `VAD_EAGERNESS`, `BARGE_IN_MS`.

`python bridge.py selftest` checks the settings and that audio comes back, without a phone.
Tests: `python -m unittest test_bridge` (a whole call against a fake Realtime server).
