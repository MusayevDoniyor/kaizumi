package com.kaizumi.remote

import android.Manifest
import android.bluetooth.*
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import android.view.inputmethod.EditorInfo
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "KaizumiRemote"
        private val SERVICE_UUID = UUID.fromString("8f5f4a5a-2f1a-4a9e-9b2a-3a6c9e1d2b4c")
        private val WRITE_UUID = UUID.fromString("9f5f4a5a-2f1a-4a9e-9b2a-3a6c9e1d2b4c")
        private val NOTIFY_UUID = UUID.fromString("a5f4a5a0-2f1a-4a9e-9b2a-3a6c9e1d2b4c")
        private const val PROTOCOL_VERSION = 1
        private const val REQ_PERMS = 1001
    }

    private var bluetoothManager: BluetoothManager? = null
    private var adapter: BluetoothAdapter? = null
    private var scanner: BluetoothLeScanner? = null
    private var gatt: BluetoothGatt? = null
    private var notifyChar: BluetoothGattCharacteristic? = null
    private var writeChar: BluetoothGattCharacteristic? = null
    private var authenticated = false
    private val mainHandler = Handler(Looper.getMainLooper())
    private val msgCounter = AtomicInteger(0)
    private var scanning = false

    private lateinit var logView: TextView
    private lateinit var statusView: TextView
    private lateinit var tokenInput: EditText
    private lateinit var commandInput: EditText
    private lateinit var connectBtn: Button
    private lateinit var sendBtn: Button
    private lateinit var clearBtn: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        logView = findViewById(R.id.logView)
        statusView = findViewById(R.id.statusView)
        tokenInput = findViewById(R.id.tokenInput)
        commandInput = findViewById(R.id.commandInput)
        connectBtn = findViewById(R.id.connectBtn)
        sendBtn = findViewById(R.id.sendBtn)
        clearBtn = findViewById(R.id.clearBtn)

        bluetoothManager = getSystemService(BLUETOOTH_SERVICE) as BluetoothManager
        adapter = bluetoothManager?.adapter

        connectBtn.setOnClickListener { onConnectPressed() }
        sendBtn.setOnClickListener { sendCommand() }
        commandInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendCommand()
                true
            } else false
        }
        clearBtn.setOnClickListener {
            logView.text = ""
            setStatus("Idle")
        }

        if (!supportAdapter()) return
        requestPermissionsIfNeeded()
    }

    private fun supportAdapter(): Boolean {
        if (adapter == null) {
            setStatus("No Bluetooth adapter on this device.")
            return false
        }
        if (!adapter!!.isEnabled) {
            setStatus("Bluetooth is off. Turn it on first.")
            return false
        }
        return true
    }

    private fun requestPermissionsIfNeeded() {
        val needed = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 31) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT)
                != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.BLUETOOTH_CONNECT)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_SCAN)
                != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.BLUETOOTH_SCAN)
        } else {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.ACCESS_FINE_LOCATION)
        }
        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), REQ_PERMS)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_PERMS) {
            setStatus("Permissions granted.")
        }
    }

    private fun onConnectPressed() {
        if (gatt != null) {
            disconnect()
            return
        }
        if (!supportAdapter()) return
        startScan()
    }

    private fun startScan() {
        scanner = adapter!!.bluetoothLeScanner
        setStatus("Scanning for 'Kaizumi Remote'…")
        log("Scanning for Kaizumi Remote…")
        scanning = true
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        try {
            scanner!!.startScan(null, settings, scanCallback)
        } catch (e: SecurityException) {
            setStatus("Bluetooth permission denied.")
        }
        mainHandler.postDelayed({ if (scanning) stopScan() }, 15000)
    }

    private fun stopScan() {
        if (!scanning) return
        scanning = false
        try { scanner?.stopScan(scanCallback) } catch (_: Exception) {}
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val name = result.device.name ?: ""
            if (result.scanRecord?.serviceUuids?.contains(SERVICE_UUID) == true ||
                name.contains("Kaizumi", ignoreCase = true)) {
                stopScan()
                log("Found: ${result.device.address} ($name)")
                connectTo(result.device)
            }
        }
    }

    private fun connectTo(device: BluetoothDevice) {
        setStatus("Connecting to ${device.address}…")
        if (Build.VERSION.SDK_INT >= 31 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT)
            != PackageManager.PERMISSION_GRANTED) {
            setStatus("BLUETOOTH_CONNECT permission missing.")
            return
        }
        // autoConnect=false, high connection priority for low latency.
        gatt = device.connectGatt(this, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        gatt?.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
    }

    private fun disconnect() {
        try {
            gatt?.disconnect()
            gatt?.close()
        } catch (_: Exception) {}
        gatt = null
        notifyChar = null
        writeChar = null
        authenticated = false
        connectBtn.text = "Connect"
        setStatus("Disconnected.")
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                mainHandler.post {
                    setStatus("Connected. Discovering services…")
                    gatt?.discoverServices()
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                mainHandler.post {
                    setStatus("Disconnected.")
                    log("Disconnected.")
                    gatt?.close()
                    gatt = null
                    notifyChar = null
                    writeChar = null
                    authenticated = false
                    connectBtn.text = "Connect"
                }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                mainHandler.post { setStatus("Service discovery failed ($status).") }
                return
            }
            val svc = g.getService(SERVICE_UUID) ?: run {
                mainHandler.post { setStatus("Service not found on device.") }
                return
            }
            writeChar = svc.getCharacteristic(WRITE_UUID)
            notifyChar = svc.getCharacteristic(NOTIFY_UUID)
            mainHandler.post {
                setStatus("Ready. Enter token and send.")
                connectBtn.text = "Disconnect"
            }
            if (notifyChar != null) {
                try {
                    g.setCharacteristicNotification(notifyChar, true)
                    val cccd = notifyChar?.getDescriptor(
                        UUID.fromString("00002902-0000-1000-8000-00805f9b34fb"))
                    cccd?.let { d ->
                        d.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                        g.writeDescriptor(d)
                    }
                } catch (e: Exception) {
                    mainHandler.post { log("Notify setup: ${e.message}") }
                }
            }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            val data = if (Build.VERSION.SDK_INT >= 33) characteristic.value else @Suppress("DEPRECATION") characteristic.value
            mainHandler.post { onIncoming(data) }
        }

        override fun onDescriptorWrite(g: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
            // CCCD configured; we can now auto-send auth if token is present.
            val token = tokenInput.text.toString().trim()
            if (token.isNotEmpty()) mainHandler.post { sendAuth(token) }
        }
    }

    private fun onIncoming(data: ByteArray?) {
        if (data == null || data.size < 2) return
        val bodyLen = ((data[0].toInt() and 0xFF) shl 8) or (data[1].toInt() and 0xFF)
        if (data.size < 2 + bodyLen) return
        val body = String(data, 2, bodyLen, StandardCharsets.UTF_8)
        try {
            val msg = org.json.JSONObject(body)
            when (msg.optString("type")) {
                "auth_ok" -> {
                    authenticated = true
                    setStatus("Authenticated. Connected to Kaizumi.")
                    log("🔑 Authenticated.")
                }
                "auth_fail" -> {
                    authenticated = false
                    setStatus("Auth failed: ${msg.optJSONObject("payload")?.optString("error")}")
                    log("⛔ ${msg.optJSONObject("payload")?.optString("error")}")
                }
                "response" -> {
                    val p = msg.optJSONObject("payload")
                    val text = p?.optString("text") ?: "(no text)"
                    log("Kaizumi: $text")
                    setStatus("Reply received.")
                }
                "event" -> {
                    val p = msg.optJSONObject("payload")
                    val kind = p?.optString("kind") ?: ""
                    val text = p?.optString("text") ?: ""
                    when (kind) {
                        "phase" -> log("Phase: ${p?.optString("state")}")
                        "tool" -> log("Tool ${p?.optString("name")} ${p?.optString("status")}")
                        else -> log("[$kind] $text")
                    }
                }
                "pong" -> log("Pong.")
            }
        } catch (e: Exception) {
            log("Malformed reply: $body")
        }
    }

    private fun sendAuth(token: String) {
        send(envelope("auth", mapOf("token" to token)))
    }

    private fun sendCommand() {
        if (!authenticated) {
            val token = tokenInput.text.toString().trim()
            if (token.isNotEmpty()) sendAuth(token)
            else { setStatus("Authenticate first."); return }
        }
        val text = commandInput.text.toString().trim()
        if (text.isEmpty()) return
        send(envelope("command", mapOf("text" to text)))
        log("You: $text")
        commandInput.text.clear()
    }

    private fun envelope(type: String, payload: Map<String, Any?>): ByteArray {
        val id = msgCounter.incrementAndGet().toString()
        val msg = org.json.JSONObject()
            .put("version", PROTOCOL_VERSION)
            .put("type", type)
            .put("id", id)
            .put("payload", org.json.JSONObject(payload))
        val body = msg.toString().toByteArray(StandardCharsets.UTF_8)
        val frame = ByteArray(2 + body.size)
        frame[0] = ((body.size shr 8) and 0xFF).toByte()
        frame[1] = (body.size and 0xFF).toByte()
        System.arraycopy(body, 0, frame, 2, body.size)
        return frame
    }

    private fun send(data: ByteArray) {
        val c = writeChar ?: run { setStatus("Not connected."); return }
        try {
            gatt?.writeCharacteristic(c, data, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
        } catch (e: Exception) {
            setStatus("Send failed: ${e.message}")
        }
    }

    private fun log(s: String) {
        logView.append("$s\n")
        // keep last ~200 lines
        val lines = logView.text.toString().lines()
        if (lines.size > 200) {
            logView.text = lines.takeLast(200).joinToString("\n") + "\n"
        }
    }

    private fun setStatus(s: String) {
        statusView.text = s
    }

    override fun onDestroy() {
        super.onDestroy()
        disconnect()
    }
}