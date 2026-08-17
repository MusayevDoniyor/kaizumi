# Kaizumi Remote (Android)

Native Android companion for **Kaizumi** over **Bluetooth LE** — no USB, no
ADB, no Developer Mode, no root.

It connects to the GATT peripheral service advertised by the PC
(`remote/bluetooth_transport.py`) and exchanges framed JSON messages defined in
[`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

> 👤 Part of the Kaizumi project by **Musayev Doniyor** (nick **Kaizo**).

## Features (v1)

- Scans for the *Kaizumi Remote* BLE service and connects.
- Auto-pairs via the encrypted + authenticated write characteristic
  (`ENCRYPTION_AND_AUTHENTICATION_REQUIRED`).
- Authenticates with the bridge token (constant-time comparison on the PC).
- Sends text commands to the PC's Gemini Live session.
- Shows Kaizumi's text replies and live events (tool status, phase changes,
  system alerts).
- Requests high connection priority for lower latency.

## How it works

```
PC (BLE GATT peripheral)  ⇄  Phone (Android app)
  • Advertises "Kaizumi Remote"
  • WRITE  char 9f5f4a5a-…  ← phone sends commands (encrypted+auth)
  • NOTIFY char a5f4a5a0-…  → phone receives replies/events
  • Token gate: no command is processed before a valid auth
```

The wire protocol (framing, envelope, message types, auth, reconnect) is fully
documented in [`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

## Requirements

- **JDK 17+** and the **Android SDK**
- A phone running **Android 8.0+ (API 26+)** with Bluetooth
- On the PC: `winrt-Windows.Devices.Bluetooth*` packages installed
  (see `requirements.txt`) and the PC's Bluetooth adapter that supports BLE
  peripheral mode

## Build

```bash
cd android
./gradlew assembleDebug
```

Or open `android/` in **Android Studio**, let it sync, and run on a phone
(Gradle 8.7 / AGP 8.5.2 / Kotlin 2.0.20).

## Permissions

- **Android 12+:** `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT` (runtime requested).
- **Android 11 and older:** `ACCESS_FINE_LOCATION` (runtime requested, needed
  for BLE scanning).

## Usage

1. On the PC, run Kaizumi with Bluetooth enabled:
   ```bash
   python main.py --remote
   ```
   The BLE peripheral starts (advertising as **"Kaizumi Remote"**) and the
   bridge token is auto-generated at `config/bridge_token.txt` (or use the
   `KAIZUMI_BRIDGE_TOKEN` env var, min 16 chars).
2. Copy the bridge token from `config/bridge_token.txt`.
3. On the phone: enable Bluetooth, open the app, enter the token, tap
   **Connect**. The app finds the PC, pairs (confirm the pairing prompt),
   authenticates, and shows *Authenticated*.
4. Type a command and tap **Send** — Kaizumi answers on the PC and streams
   live events to the phone.

> 🔐 The bridge token is your only credential for the phone. Keep it private —
> it unlocks full control of your assistant.

## Troubleshooting

- **Scan finds nothing:** ensure the PC's Bluetooth radio is on and the PC and
  phone are close together. Some PCs need the device in discoverable mode; the
  peripheral advertising is always discoverable.
- **Pairing prompt doesn't appear:** on Android the first encrypted write
  triggers pairing; if the PC requires "just works" pairing this is automatic.
- **Reply is slow:** BLE default MTU is small; the Android app requests high
  connection priority. Text replies are short, so latency is fine.
- **`[Bluetooth] ⛔ No bridge token`:** run `--remote` once to auto-generate
  `config/bridge_token.txt`, or set `KAIZUMI_BRIDGE_TOKEN`.

## Protocol

See [`docs/PROTOCOL.md`](../docs/PROTOCOL.md) for the complete wire spec:
service/characteristic UUIDs, length-prefixed framing, the JSON envelope,
auth flow, and reconnect behavior.