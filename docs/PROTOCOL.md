# Kaizumi Bluetooth Protocol

The Bluetooth transport (`remote/bluetooth_transport.py` on the PC, the
`android/` app on the phone) is the phone control channel — no USB, no ADB, no
website. The PC advertises a BLE GATT peripheral service; the phone connects,
pairs, and exchanges framed JSON messages.

## Link layer

- **Transport:** Bluetooth LE (GATT).
- **Service UUID:** `8f5f4a5a-2f1a-4a9e-9b2a-3a6c9e1d2b4c` — scan name _Kaizumi
  Remote_.
- **Write characteristic** (phone → PC):
  `9f5f4a5a-2f1a-4a9e-9b2a-3a6c9e1d2b4c`
  - Protected with `ENCRYPTION_AND_AUTHENTICATION_REQUIRED`. The phone's first
    write triggers Android/iOS Bluetooth pairing automatically. This is the
    whole security model at the link layer.
- **Notify characteristic** (PC → phone):
  `a5f4a5a0-2f1a-4a9e-9b2a-3a6c9e1d2b4c`

## Framing

Every message is a UTF-8 JSON object, prefixed by a 2-byte big-endian length:

```
[ len_hi ][ len_lo ][ ...len bytes of JSON... ]
```

## Message envelope

```json
{ "version": 1, "type": "auth", "id": "3", "payload": { ... } }
```

- `id` — client-generated request id, echoed back on the matching response.
- `payload` — message-specific object.

## Phone → PC

| type         | payload                       | reply                            |
| ------------ | ----------------------------- | -------------------------------- |
| `auth`       | `{"token": "<bridge token>"}` | `auth_ok` / `auth_fail`          |
| `ping`       | —                             | `pong`                           |
| `status`     | —                             | `response` with `state`, `muted` |
| `mute`       | `{"muted": true               | false}`                          |
| `stop`       | —                             | `response`                       |
| `disconnect` | —                             | `event` (system), then closes    |
| `command`    | `{"text": "play some music"}` | `response` (text reply)          |

`command` text is routed through the **same Gemini Live session** as local
voice and Telegram, so all Kaizumi tools, the safety gate, and memory behave
identically. The Kaizumi reply is delivered as a `response` message with the id
of the command that triggered it.

> Note: v1 is text-only over Bluetooth (BLE data rate makes live PCM voice
> impractical). Real-time voice stays on local mic/speakers.

## PC → Phone

| type                    | payload                                                                    | notes                       |
| ----------------------- | -------------------------------------------------------------------------- | --------------------------- |
| `auth_ok` / `auth_fail` | `{"error": "..."}` (fail only)                                             | auth result                 |
| `pong`                  | —                                                                          | ping reply                  |
| `response`              | `{"text": "...", "state": "...", "muted": ...}`                            | reply to a command / status |
| `event`                 | `{"kind": "system"\|"phase"\|"tool", "text"/"state"/"name"/"status": ...}` | unsolicited events          |

`phase` events mirror the engine's `{"type":"phase"}` broadcasts; `tool` events
mirror `{"type":"tool"}`; `system` events mirror `{"type":"system"}`.

## Auth

- Token comes from `config/bridge_token.txt` (or `KAIZUMI_BRIDGE_TOKEN` env).
- No message is processed before a valid `auth`. A failed auth closes the
  client.
- Comparison uses a constant-time check.

## Reconnect

- The PC keeps advertising, so the phone reconnects freely. On reconnect the
  phone must `auth` again.
- Tracked clients are keyed by the notify characteristic instance; when the
  phone unsubscribes, the client is dropped.
