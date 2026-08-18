# actions/vision_gesture.py
# Kaizumi — Full-body computer vision service (FREE, local, no AI API)
#
# Uses Google MediaPipe Tasks (free, on-device, accurate) + OpenCV:
#   - HolisticLandmarker: full-body pose (33 pts) + hands (21 pts ×2) + face mesh
#   - FaceDetector: count people
#   - cv2.QRCodeDetector: read QR / barcodes
#
# Modes (continuous, background thread):
#   gesture   — count fingers, detect gestures (peace, thumbs up, point, fist, open hand)
#   air_mouse — index finger moves the cursor, thumb+index pinch = click
#   volume    — thumb–index pinch distance controls system volume
#   motion    — security mode: frame-diff motion detection
#   posture   — full-body posture reporting (arms up/down, lean, sitting/standing)
#   focus     — warns when hand/head leaves the frame
#
# One-shot actions (return a value, no continuous loop):
#   face_count — how many faces/people in frame
#   qr         — read QR / barcode from camera
#   snapshot   — capture one frame & summarize what's on camera

import time
import math
import threading

import cv2
import numpy as np

_MP = None  # None=not checked yet, False=unavailable, tuple=available


def _get_mp():
    """Lazily import mediapipe; returns (mp_python, mp_vision, MPImage, MPImageFormat) or None."""
    global _MP
    if _MP is None:
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision
            from mediapipe import Image as MPImage
            from mediapipe import ImageFormat as MPImageFormat
            _MP = (mp_python, mp_vision, MPImage, MPImageFormat)
        except ImportError:
            _MP = False
    return _MP or None

_PYAUTOGUI = None  # None=not checked yet, False=unavailable, True=available


def _get_pyautogui():
    """Lazily import pyautogui; returns the module or None."""
    global _PYAUTOGUI
    if _PYAUTOGUI is None:
        try:
            import pyautogui
            _PYAUTOGUI = pyautogui
        except ImportError:
            _PYAUTOGUI = False
    return _PYAUTOGUI or None


BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"

MODES = {"gesture", "air_mouse", "volume", "motion", "posture"}

# ── Landmark indices ──────────────────────────────────────────────────────────
HAND_INDEX_TIP  = 8
HAND_THUMB_TIP  = 4
HAND_THUMB_IP   = 3
HAND_WRIST      = 0
HAND_PINKY_PIP  = 18

POS_SHOULDER_L = 11
POS_SHOULDER_R = 12
POS_ELBOW_L    = 13
POS_ELBOW_R    = 14
POS_WRIST_L    = 15
POS_WRIST_R    = 16
POS_HIP_L      = 23
POS_HIP_R      = 24
POS_NOSE       = 0


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _finger_count(hand) -> int:
    """Counts extended fingers for a MediaPipe hand landmark list."""
    if not hand:
        return 0
    tips = [8, 12, 16, 20]
    mcp  = [5, 9, 13, 17]
    count = 0
    for tip, base in zip(tips, mcp):
        if hand[tip].y < hand[base].y:
            count += 1
    # thumb: compare thumb tip x vs pinky MCP x on the same hand
    if hand[4].x < hand[17].x:
        count += 1
    return count


def _gesture_name(fingers: int, pinch: bool, point: bool) -> str:
    if pinch and fingers <= 1:
        return "pinch / grab"
    if fingers == 0:
        return "fist"
    if fingers == 5:
        return "open hand"
    if fingers == 1 and point:
        return "pointing"
    if fingers == 1:
        return "one finger (index)"
    if fingers == 2 and not point:
        return "peace sign"
    if fingers == 2:
        return "two fingers"
    if fingers == 3:
        return "three fingers"
    if fingers == 4:
        return "four fingers"
    return f"{fingers} fingers"


class VisionService:
    """Background-thread camera service with switchable modes."""

    def __init__(self):
        self._lock      = threading.Lock()
        self._running   = False
        self._mode      = "gesture"
        self._thread    = None
        self._cap       = None
        self._player    = None
        self._speak     = None
        self._ts        = 0
        self._last_tell = 0
        self._holistic  = None
        self._faces     = None
        self._prev_gray = None
        self._ready     = threading.Event()

    # ── Setup / control ───────────────────────────────────────────────────────
    def configure(self, player=None, speak=None):
        self._player = player
        self._speak  = speak

    def start(self, mode: str = "gesture") -> str:
        if _get_mp() is None:
            return "MediaPipe is not installed. Run: pip install mediapipe"
        if mode not in MODES:
            return f"Unknown vision mode: {mode}. Use: gesture, air_mouse, volume, motion, posture, focus"
        with self._lock:
            already = self._running
            self._mode = mode
        if not already:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="VisionGestureThread")
            self._thread.start()
            ok = self._ready.wait(timeout=20)
            if not ok:
                return "Camera failed to open, sir."
        return f"Vision mode active: {mode}. Say 'stop vision' when done."

    def stop(self) -> str:
        # Only flag stop; the loop thread owns the capture object and releases
        # it on exit — releasing here races with the loop's read()/release().
        with self._lock:
            self._running = False
        return "Vision stopped, sir."

    @property
    def is_running(self) -> bool:
        return self._running

    def _build_tools(self):
        mp = _get_mp()
        if mp is None:
            return False
        mp_python, mp_vision, MPImage, MPImageFormat = mp
        self._mp_image_factory = MPImage
        self._mp_image_format = MPImageFormat
        base = mp_python.BaseOptions(model_asset_path=str(MODELS_DIR / "holistic_landmarker.task"))
        self._holistic = mp_vision.HolisticLandmarker.create_from_options(
            mp_vision.HolisticLandmarkerOptions(
                base_options=base,
                running_mode=mp_vision.RunningMode.VIDEO,
                min_pose_detection_confidence=0.5,
                min_hand_landmarks_confidence=0.5,
                min_face_landmarks_confidence=0.5,
            )
        )
        self._faces = mp_vision.FaceDetector.create_from_options(
            mp_vision.FaceDetectorOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(MODELS_DIR / "face_detector.tflite")),
                running_mode=mp_vision.RunningMode.VIDEO,
            )
        )

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _loop(self):
        self._cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not self._cap.isOpened():
            print("[VisionGesture] ❌ Camera failed to open")
            with self._lock:
                self._running = False
            self._ready.set()
            return

        try:
            self._build_tools()
        except Exception as e:
            print(f"[VisionGesture] ❌ Model load failed: {e}")
            self._cap.release()
            with self._lock:
                self._running = False
            self._ready.set()
            return

        with self._lock:
            self._running = True
        self._ready.set()
        print("[VisionGesture] ✅ Camera running")

        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            self._ts += 1
            with self._lock:
                mode = self._mode
            try:
                self._process(frame, mode, self._ts)
            except Exception as e:
                print(f"[VisionGesture] ⚠️ {e}")
            time.sleep(0.02)

        self._cap.release()
        self._cap = None
        print("[VisionGesture] 🔴 Camera stopped")

    def _process(self, frame, mode: str, ts: int):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = self._mp_image_factory(image_format=self._mp_image_format.SRGB, data=rgb)

        res = self._holistic.detect_for_video(mp_image, ts * 20)
        pose = res.pose_landmarks if res.pose_landmarks else None
        hands = []
        if res.right_hand_landmarks:
            hands.append(res.right_hand_landmarks)
        if res.left_hand_landmarks:
            hands.append(res.left_hand_landmarks)

        if mode == "gesture":
            self._handle_gesture(hands)
        elif mode == "air_mouse":
            self._handle_air_mouse(hands)
        elif mode == "volume":
            self._handle_volume(hands)
        elif mode == "posture":
            self._handle_posture(pose)
        elif mode == "motion":
            self._handle_motion(frame)

    # ── Mode handlers ─────────────────────────────────────────────────────────
    def _tell(self, text: str, cooldown: float = 1.5):
        now = time.time()
        if now - self._last_tell < cooldown:
            return
        self._last_tell = now
        if self._speak:
            try:
                self._speak(text)
            except Exception:
                pass
        if self._player:
            self._player.write_log(f"Vision: {text}")
        print(f"[VisionGesture] 💬 {text}")

    def _handle_gesture(self, hands):
        if not hands:
            return
        hand = hands[0]
        fingers = _finger_count(hand)
        thumb = hand[HAND_THUMB_TIP]
        idx   = hand[HAND_INDEX_TIP]
        pinch = _dist(thumb, idx) < 0.07
        point = not pinch and fingers == 1 and hand[HAND_INDEX_TIP].y < hand[HAND_WRIST].y
        name  = _gesture_name(fingers, pinch, point)
        self._tell(f"Gesture detected: {name}.", cooldown=2.0)

    def _handle_air_mouse(self, hands):
        pyautogui = _get_pyautogui()
        if not hands or pyautogui is None:
            return
        hand = hands[0]
        idx = hand[HAND_INDEX_TIP]
        scr_w, scr_h = pyautogui.size()
        # Kamera mirror ko'rgani uchun x ni teskari qilish:
        # barmoq chapga yursa kursor ham chapga yurishi kerak.
        x = int((1.0 - idx.x) * scr_w)
        y = int(idx.y * scr_h)
        try:
            pyautogui.moveTo(x, y, duration=0.05)
        except Exception:
            pass
        thumb = hand[HAND_THUMB_TIP]
        if _dist(thumb, idx) < 0.06:
            try:
                pyautogui.click()
            except Exception:
                pass
            self._tell("Click.", cooldown=1.0)

    def _handle_volume(self, hands):
        if not hands:
            return
        hand = hands[0]
        thumb = hand[HAND_THUMB_TIP]
        idx   = hand[HAND_INDEX_TIP]
        d = _dist(thumb, idx)
        pct = int(max(0, min(100, (1 - d / 0.4) * 100)))
        try:
            from actions.computer_settings import volume_set
            volume_set(pct)
        except Exception:
            pass
        self._tell(f"Volume {pct}%.", cooldown=3.0)

    def _handle_posture(self, pose):
        if not pose:
            self._tell("No body detected in frame.", cooldown=5.0)
            return
        nose = pose[POS_NOSE]
        so   = (pose[POS_SHOULDER_L], pose[POS_SHOULDER_R])
        sh_mid = ((so[0].x + so[1].x) / 2, (so[0].y + so[1].y) / 2)
        wrist_top = min(pose[POS_WRIST_L].y, pose[POS_WRIST_R].y)
        shoulder_y = min(so[0].y, so[1].y)

        if wrist_top < shoulder_y - 0.1:
            self._tell("Arms are raised.", cooldown=4.0)
        elif abs(nose.x - sh_mid[0]) > 0.12:
            self._tell("Leaning to the side.", cooldown=4.0)
        else:
            self._tell("Body detected, neutral posture.", cooldown=8.0)

    def _handle_motion(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self._prev_gray is None:
            self._prev_gray = gray
            return
        diff = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray
        thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
        motion_pct = (thresh > 0).mean()
        if motion_pct > 0.15:
            self._tell(f"Motion detected, sir. Coverage {motion_pct * 100:.0f}%.", cooldown=3.0)

    # ── One-shot actions ──────────────────────────────────────────────────────
    def _open_camera(self):
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    def face_count(self) -> str:
        mp = _get_mp()
        if mp is None:
            return "MediaPipe is not installed, sir."
        mp_python, mp_vision, MPImage, MPImageFormat = mp
        try:
            det = mp_vision.FaceDetector.create_from_options(
                mp_vision.FaceDetectorOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=str(MODELS_DIR / "face_detector.tflite")),
                    running_mode=mp_vision.RunningMode.IMAGE,
                )
            )
            cap = self._open_camera()
            n_faces = 0
            for _ in range(8):
                ok, frame = cap.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = MPImage(image_format=MPImageFormat.SRGB, data=rgb)
                res = det.detect(mp_image)
                if res.detections:
                    n_faces = max(n_faces, len(res.detections))
                time.sleep(0.05)
            cap.release()
            return f"I see {n_faces} person(s) in front of the camera, sir."
        except Exception as e:
            return f"Face detection failed: {e}"

    def read_qr(self) -> str:
        try:
            cap = self._open_camera()
            qd = cv2.QRCodeDetector()
            for _ in range(15):
                ok, frame = cap.read()
                if not ok:
                    continue
                data, *_ = qd.detectAndDecode(frame)
                if data:
                    cap.release()
                    return f"QR code read: {data[:150]}"
                time.sleep(0.05)
            cap.release()
            return "I couldn't find a QR code, sir. Make sure it's fully visible."
        except Exception as e:
            return f"QR reading failed: {e}"

    def snapshot(self, question: str = "") -> str:
        mp = _get_mp()
        if mp is None:
            return "MediaPipe is not installed, sir."
        mp_python, mp_vision, MPImage, MPImageFormat = mp
        try:
            det = mp_vision.HolisticLandmarker.create_from_options(
                mp_vision.HolisticLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=str(MODELS_DIR / "holistic_landmarker.task")),
                    running_mode=mp_vision.RunningMode.IMAGE,
                    min_pose_detection_confidence=0.5,
                )
            )
            cap = self._open_camera()
            for _ in range(5):
                cap.read()
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return "Could not capture camera frame, sir."
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = MPImage(image_format=MPImageFormat.SRGB, data=rgb)
            res = det.detect(mp_image)
            pose  = res.pose_landmarks if res.pose_landmarks else None
            hands = []
            if res.right_hand_landmarks:
                hands.append(res.right_hand_landmarks)
            if res.left_hand_landmarks:
                hands.append(res.left_hand_landmarks)
            desc = []
            if pose:
                desc.append("a person is in frame")
            else:
                desc.append("no person detected")
            if hands:
                n_hands = len(hands)
                n_fingers = sum(_finger_count(h) for h in hands)
                desc.append(f"{n_hands} hand(s), {n_fingers} fingers visible")
            return "On camera: " + ", ".join(desc) + "."
        except Exception as e:
            return f"Snapshot failed: {e}"


_service = VisionService()


def vision_gesture(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """Control the full-body vision service.
    action: start | stop | face_count | qr | snapshot | status
    mode (for start): gesture | air_mouse | volume | motion | posture | focus"""
    params     = parameters or {}
    action     = str(params.get("action", "status")).lower().strip()
    mode       = str(params.get("mode", "gesture")).lower().strip()

    _service.configure(player=player, speak=speak)

    if action == "start":
        return _service.start(mode)
    if action == "stop":
        return _service.stop()
    if action == "face_count":
        return _service.face_count()
    if action == "qr":
        return _service.read_qr()
    if action == "snapshot":
        return _service.snapshot(params.get("text", ""))
    if action in ("status", "info"):
        running = _service.is_running
        with _service._lock:
            mode = _service._mode
        return f"Vision service is {'active' if running else 'stopped'} (mode: {mode})."
    return f"Unknown vision action: {action}, sir. Use start | stop | face_count | qr | snapshot | status"