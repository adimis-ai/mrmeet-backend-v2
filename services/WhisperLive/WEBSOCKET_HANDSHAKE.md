# WhisperLive WebSocket Handshake & URL

This service exposes a WebSocket endpoint at:

```
ws://<host>:<port>/ws
```

In Docker Compose the `whisperlive` service listens on port `9090` internally. Traefik (if enabled) proxies `/ws` on its own entrypoint to the same internal endpoint. The server also self-registers its effective URL (with a concrete container IP) to Redis/Consul when discovery flags are enabled.

## Required Handshake JSON
On connect the client must immediately send a single JSON object with (minimum) keys:

- uid: unique identifier for this client session
- platform: e.g. `google_meet`, `zoom`, etc.
- meeting_url: canonical meeting URL
- token: authentication / authorization token (placeholder okay in dev)
- meeting_id: internal numeric/string meeting id

Additional optional keys supported: `language`, `task`, `initial_prompt`, `use_vad`, etc.

## Normalization
To ease client integration the server now normalizes common camelCase variants:

- meetingUrl -> meeting_url
- meetingId or nativeMeetingId -> meeting_id
- connectionId -> uid
- botName -> uid (fallback if no uid provided)

If `uid` is still absent a synthetic `anon-<8hex>` value is generated. If `token` is absent a placeholder `NO_TOKEN` is injected (development only; production clients should send a real token).

A failure to include (or normalize to) required keys previously caused an early close (1006 observed by clients). The normalization patch prevents unnecessary reconnect loops due solely to naming differences.

## Troubleshooting 1006 Disconnects
1. Enable debug logs: set `LOG_LEVEL=DEBUG` for WhisperLive and client.
2. Confirm first frame from client is valid JSON (no leading binary audio frames).
3. Check server logs for `Missing required fields` errors.
4. Verify the client uses `/ws` path (Traefik route or direct service URL) and not just the host root.
5. If using Traefik ensure router rule matches `PathPrefix(`/ws`)` and either strips or preserves prefix consistently with client expectations.

## Example Handshake Payload
```json
{
  "uid": "session-1234",
  "platform": "google_meet",
  "meeting_url": "https://meet.google.com/xyz-abcd-efg",
  "token": "bearer-or-placeholder",
  "meeting_id": "42",
  "language": "en",
  "task": "transcribe",
  "use_vad": true
}
```

## Client Reminder
Send the handshake JSON first. Only after receiving an OK / first server response should you start streaming raw float32 PCM frames OR JSON control messages (speaker_activity, session_control, audio_chunk_metadata).
