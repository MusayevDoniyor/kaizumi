# Kaizumi Remote (Android)

Native Android companion for Kaizumi over **Bluetooth LE** — no USB, no ADB,
no Developer Mode, no root.

It connects to the GATT peripheral service advertised by the PC
(`remote/bluetooth_transport.py`) and exchanges framed JSON messages defined
in [`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

## Features (v1)

- Scans for the *Kaizumi Remote* service and connects.
- Auto-pairs via the encrypted write characteristic.
- Authenticates with the bridge token.
- Sends text commands and shows Kaizumi's replies + live events.

## Build

```bash
cd android
# requires JDK 17+ and the Android SDK
./gradlew assembleDebug
```

Open `android/` in Android Studio, let it sync, and run on a phone.

## Permissions

- Android 12+: `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT` (runtime requested).
- Android 11 and older: `ACCESS_FINE_LOCATION` (runtime requested, needed for
  BLE scanning).

## Usage

1. On the PC, run Kaizumi with `--remote` (this starts the Bluetooth peripheral).
2. Copy the bridge token from `config/bridge_token.txt`.
3. On the phone: enable Bluetooth, open the app, enter the token, tap Connect.
   The app finds the PC, pairs (confirm the pairing prompt), authenticates, and
   shows "Authenticated."
4. Type a command and tap Send — Kaizumi answers on the PC.

## Troubleshooting

- **Scan finds nothing:** ensure the PC's Bluetooth radio is on and the PC and
  phone are close together. Some PCs need the device in discoverable mode; the
  peripheral advertising is always discoverable.
- **Pairing prompt doesn't appear:** on Android the first encrypted write
  triggers pairing; if the PC requires "just works" pairing this is automatic.
- **Reply is slow:** BLE default MTU is small; the Android app requests high
  connection priority. Text replies are short, so latency is fine.