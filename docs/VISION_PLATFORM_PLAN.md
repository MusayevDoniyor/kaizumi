# Kaizumi Vision Platform

## Maqsad

Kaizumi’ni oddiy voice assistant’dan real dunyoni ko‘ra oladigan, kamera va ekran bilan ishlaydigan JARVIS-style vision assistant’ga aylantirish.

Platforma quyidagilarni bajara olishi kerak:

- kameradan real-time video olish;
- odamlar va obyektlarni aniqlash;
- obyektlarni frame’lar bo‘yicha kuzatish;
- qo‘l gesture’lari bilan kompyuterni boshqarish;
- pose/posture tahlili;
- yuzlarni aniqlash va privacy blur qilish;
- OCR orqali ekrandagi yoki hujjatdagi matnni o‘qish;
- QR va barcode skanerlash;
- rasmni tavsiflash va rasm haqida savollarga javob berish;
- segmentation, background removal va anomaly detection;
- aniqlangan hodisalarni dashboard, voice, Telegram va desktop notification orqali yetkazish.

## Hozirgi holat

Loyihada allaqachon quyidagi asos mavjud:

- `actions/vision_gesture.py` — MediaPipe asosidagi vision service;
- gesture detection;
- air mouse;
- volume control;
- posture detection;
- motion detection;
- camera snapshot;
- face count;
- QR reading;
- JARVIS-style Tkinter dashboard;
- Vision Deck va Command Deck;
- voice command dispatch;
- `opencv-python`, `mediapipe`, `pyautogui`, `mss`, `pillow` dependency’lari.

Keyingi ishlar mavjud servisni buzmasdan, uni alohida va kengaytiriladigan Vision Platform’aga aylantirish orqali bajariladi.

## Arxitektura

```text
Camera / Screenshot / Image / Video
                |
                v
        Camera Manager
                |
                v
        Vision Pipeline
       /       |        \
      v        v         v
 Detection   Pose      OCR
 Tracking    Gesture   Barcode
      |        |         |
      +--------+---------+
                |
                v
          Vision Events
                |
       +--------+---------+
       v        v         v
   Dashboard  Voice     Automation
             Reply     Alerts
```

Tavsiya qilinadigan modul tuzilmasi:

```text
vision/
├── __init__.py
├── camera_manager.py
├── vision_pipeline.py
├── vision_events.py
├── model_manager.py
├── object_detector.py
├── object_tracker.py
├── face_tools.py
├── pose_engine.py
├── gesture_engine.py
├── ocr_engine.py
├── barcode_engine.py
├── segmentation.py
├── anomaly_detector.py
└── privacy.py
```

## 1. Vision Core

### 1.1. Camera Manager

`camera_manager.py` kamera bilan bog‘liq barcha ishlarni markazlashtiradi:

- kamera ochish va yopish;
- camera index tanlash;
- resolution sozlash;
- FPS nazorati;
- frame queue;
- kamera band yoki mavjud emasligini aniqlash;
- kamera resursini xavfsiz release qilish;
- bir nechta vision modulining bitta frame’dan foydalanishi.

Kamera boshqaruvi har bir modulda alohida yozilmaydi. Bitta frame pipeline orqali barcha detector’lar bilan bo‘linadi.

### 1.2. Vision Pipeline

Pipeline har bir frame uchun quyidagilarni bajaradi:

1. frame capture;
2. resize va color conversion;
3. kerakli modullarni ishga tushirish;
4. natijalarni birlashtirish;
5. overlay chizish;
6. `VisionEvent` chiqarish;
7. dashboard va assistant’ga yuborish.

Performance uchun barcha modullar har frame’da ishlamasligi mumkin. Masalan, YOLO 10 FPS, pose 20 FPS, OCR esa faqat foydalanuvchi so‘raganda ishlaydi.

### 1.3. VisionEvent

Barcha vision natijalari yagona event formatida bo‘ladi:

```python
{
    "type": "object_detected",
    "timestamp": 0.0,
    "source": "camera_0",
    "label": "person",
    "confidence": 0.94,
    "bbox": [x, y, width, height],
    "track_id": 3,
    "metadata": {}
}
```

Event turlari:

- `object_detected`;
- `object_lost`;
- `person_entered`;
- `person_left`;
- `gesture_detected`;
- `pose_detected`;
- `motion_detected`;
- `face_detected`;
- `unknown_face`;
- `text_detected`;
- `qr_detected`;
- `barcode_detected`;
- `anomaly_detected`;
- `camera_status`.

## 2. Object Detection

YOLO yoki ONNX model orqali real-time object detection qo‘shiladi.

### Birinchi model klasslari

- person;
- laptop;
- phone;
- keyboard;
- mouse;
- book;
- cup;
- bottle;
- backpack;
- chair;
- car;
- animal.

### Dashboard funksiyalari

- bounding box;
- object label;
- confidence score;
- detected object count;
- FPS;
- active model;
- minimum confidence slider;
- detection history.

### Voice komandalar

```text
kamerada nechta odam bor?
kamerada nimalar ko‘rinmoqda?
telefonimni top
odam kirsa menga ayt
shu obyektni kuzat
```

### Keyingi kengaytmalar

- custom classes;
- restricted-area detection;
- object counting line;
- object color detection;
- object size estimation;
- object missing alert.

## 3. Object Tracking

Detection obyektni topadi, tracking esa uni ketma-ket frame’larda kuzatadi.

Qo‘shiladigan imkoniyatlar:

- har bir obyektga `track_id` berish;
- odamning kirish/chiqishini aniqlash;
- obyektning frame’da qancha vaqt bo‘lganini hisoblash;
- obyekt yo‘qolganini aniqlash;
- bir nechta odamni alohida kuzatish;
- virtual line crossing;
- zone entry/exit.

Misol eventlar:

```text
Person #01 entered the zone
Phone #02 disappeared
Object stayed in frame for 24 seconds
```

## 4. Gesture va Hands-free Control

Hozirgi MediaPipe gesture service kengaytiriladi.

### Gesture mapping

| Gesture | Action |
|---|---|
| Open hand | Pause/resume |
| Fist | Stop/cancel |
| Thumbs up | Confirm |
| Thumbs down | Reject |
| Two fingers | Next |
| Three fingers | Previous |
| Pinch | Click/grab |
| Swipe left | Previous page |
| Swipe right | Next page |
| Raised hand | Wake Kaizumi |

### Safety qoidalari

- barcha gesture’larda cooldown;
- xavfli komandalar uchun confirmation;
- gesture lock/unlock;
- faqat foydalanuvchi kameraga qaraganida action bajarish;
- noto‘g‘ri aniqlanishga qarshi minimum confidence;
- emergency stop gesture.

## 5. Pose Estimation va Posture

MediaPipe Pose yoki MoveNet orqali body landmarks olinadi.

Aniqlanadigan holatlar:

- yelka, tirsak, bilak;
- tizza va oyoq;
- bosh holati;
- o‘tirish yoki turish;
- egilish;
- qo‘l ko‘tarilishi;
- ekranga qarash;
- noto‘g‘ri posture.

Qo‘llanishlar:

- posture assistant;
- AI fitness trainer;
- rep counter;
- presentation control;
- hands-free slide navigation;
- stretching reminder.

Voice komandalar:

```text
qomatim to‘g‘rimi?
mashqni sanab tur
qo‘limni ko‘tarsam keyingi slaydga o‘t
posture monitoringni yoq
```

## 6. Face Detection, Recognition va Privacy

### Face detection

- frame’dagi yuzlar soni;
- yuz bounding box’lari;
- yuz kameraga qaragan yoki yo‘qligi;
- yuzning ko‘rinish sifati.

### Face recognition

Foydalanuvchi roziligi bilan local profile yaratish:

```text
register face: Doniyor
register face: Akmal
```

Keyin:

```text
Doniyor kamerada
Unknown person detected
```

### Face blur

- barcha yuzlarni blur qilish;
- noma’lum yuzlarni blur qilish;
- screenshot’dan oldin avtomatik blur;
- recording’da privacy mode;
- Telegram’ga yuborishdan oldin yuzlarni yashirish.

Face embedding’lar local va himoyalangan holda saqlanadi. Roziliksiz face recognition ishlatilmaydi.

## 7. OCR va Document Vision

OpenCV preprocessing bilan Tesseract, EasyOCR yoki TrOCR ulanadi.

Funksiyalar:

- ekrandagi matnni o‘qish;
- suratdagi matnni chiqarish;
- o‘zbek, rus va ingliz tillari;
- hujjatni deskew qilish;
- invoice/receipt parsing;
- telefon raqam va email topish;
- sana va summa ajratish;
- license plate recognition;
- real-time screen OCR.

Pipeline:

```text
Image
  ↓
Deskew
  ↓
Denoise
  ↓
Threshold
  ↓
Text Detection
  ↓
OCR
  ↓
Kaizumi Summary
```

Voice komandalar:

```text
ekrandagi matnni o‘qi
bu hujjat nimani aytyapti?
rasmdagi telefon raqamini top
receipt’dan umumiy summani chiqar
```

## 8. QR va Barcode

Mavjud QR reader barcode bilan kengaytiriladi:

- QR code o‘qish;
- barcode o‘qish;
- bir nechta code’ni bitta frame’da topish;
- barcode history;
- product lookup;
- link preview;
- URL xavfsizlik tekshiruvi.

QR link hech qachon avtomatik ochilmaydi. Avval foydalanuvchi tasdig‘i olinadi.

## 9. Segmentation va Background Tools

### Background removal

- odamni fondan ajratish;
- transparent PNG;
- virtual background;
- product photo cleanup;
- video-call background replacement;
- AR overlay uchun subject extraction.

### Segmentation

- semantic segmentation;
- instance segmentation;
- bir xil klassdagi obyektlarni alohida ajratish;
- yo‘l, mashina, odam, stol va devor segmentlari;
- pixel-level mask overlay.

Model variantlari:

- YOLO segmentation;
- U-Net;
- DeepLab;
- Mask R-CNN;
- SegFormer.

## 10. Image Captioning va Visual Q&A

### Image captioning

Kaizumi kamera yoki rasmni tavsiflaydi:

```text
Stol ustida laptop, telefon va bir stakan suv bor.
```

### Visual Question Answering

Foydalanuvchi frame haqida savol beradi:

```text
Stolning chap tomonida nima bor?
Rasmda nechta odam bor?
Qizil obyekt qayerda?
Bu hujjatda sana bormi?
```

Bu modul local multimodal model yoki mavjud vision API bilan ishlashi mumkin. Privacy mode’da rasm tashqi API’ga yuborilmaydi.

## 11. Anomaly va Security Monitoring

Kaizumi odatiy holatni o‘rganib, noodatiy holatlarni bildiradi.

Aniqlanadigan holatlar:

- noma’lum odam paydo bo‘lishi;
- restricted zone’ga kirish;
- kutilmagan motion;
- xona bo‘sh bo‘lishi kerak paytda odam borligi;
- obyektning yo‘qolishi;
- eshik yoki oynaning ochilishi;
- ishlab chiqarishdagi defect;
- kamera zonasidagi unusual activity.

Alert kanallari:

- dashboard;
- ovozli ogohlantirish;
- Telegram;
- desktop notification;
- log;
- screenshot.

Misol:

```text
Unknown person detected at 22:14.
Motion detected in restricted zone.
Phone object disappeared from desk.
```

## 12. Roboflow bilan Custom Model

Roboflow majburiy dependency emas. U custom object yoki domain-specific model kerak bo‘lganda ishlatiladi.

Workflow:

1. Rasm/video dataset yig‘ish.
2. Obyektlarni label qilish.
3. Dataset’ni train/validation/test ga bo‘lish.
4. Augmentation qo‘llash.
5. YOLO modelini train qilish.
6. Modelni ONNX yoki PyTorch formatiga export qilish.
7. Kaizumi local inference’iga ulash.
8. Test video bilan accuracy va latency’ni o‘lchash.

Custom model misollari:

- Kaizumi-specific gesture’lar;
- foydalanuvchining shaxsiy qurilmalari;
- pothole detection;
- construction safety;
- product defect;
- warehouse object detection;
- agriculture pest detection.

Roboflow cloud inference internet, API key va ehtimoliy xarajat talab qilishi mumkin. Local model privacy va latency uchun afzal.

## 13. JARVIS Dashboard

Vision Lab panelida quyidagilar ko‘rsatiladi:

```text
CAMERA STATUS       ONLINE
CURRENT MODE        OBJECT DETECTION
FPS                 28
DETECTED OBJECTS    07
PEOPLE              02
GESTURE             OPEN HAND
POSE                NEUTRAL
OCR                 READY
FACE PRIVACY        ENABLED
ALERTS              00
```

Dashboard komponentlari:

- live camera preview;
- bounding box overlay;
- pose skeleton;
- gesture name;
- OCR overlay;
- confidence slider;
- FPS control;
- model selector;
- privacy toggle;
- event timeline;
- snapshot button;
- recording button;
- “Ask Kaizumi about this frame” button;
- model load/error indicator.

## 14. Development Phases

### Phase 1 — Vision MVP

Maqsad: Kaizumi kamerani ko‘radi va asosiy real-time signal beradi.

- camera manager;
- live preview;
- YOLO object detection;
- object count;
- MediaPipe gesture;
- pose skeleton;
- OCR;
- QR/barcode;
- unified vision event;
- dashboard telemetry.

### Phase 2 — Assistant Integration

- voice vision commands;
- detected object haqida javob;
- gesture-to-command mapping;
- screenshot analysis;
- Telegram alert;
- event history;
- action confirmation;
- safety stop.

### Phase 3 — Privacy va Automation

- face blur;
- local face profiles;
- unknown person alert;
- zone monitoring;
- object missing alert;
- privacy mode;
- local encrypted metadata.

### Phase 4 — Advanced Vision

- image captioning;
- Visual Q&A;
- segmentation;
- background removal;
- anomaly detection;
- image colorization;
- super-resolution.

### Phase 5 — Custom Intelligence

- Roboflow dataset;
- custom YOLO training;
- personal gestures;
- Kaizumi-specific object classes;
- domain-specific models;
- GPU/ONNX optimization;
- optional edge deployment.

## 15. Birinchi katta milestone

Birinchi milestone quyidagicha bo‘ladi:

> Kaizumi kamerani ochadi, odamlar va obyektlarni real vaqtda topadi, gesture’ni taniydi, pose skeleton chizadi, OCR orqali matnni o‘qiydi va bularning barchasini JARVIS dashboard’ida ko‘rsatadi.

Implementatsiya tartibi:

1. `camera_manager.py` yaratish.
2. Live preview oynasini qo‘shish.
3. YOLO object detector ulash.
4. MediaPipe pose/gesture overlay qo‘shish.
5. OCR engine qo‘shish.
6. QR/barcode module qo‘shish.
7. Unified `VisionEvent` modelini yaratish.
8. Dashboard telemetry’ni ulash.
9. Voice command integration qilish.
10. Test image va test video bilan tekshirish.

## 16. Performance talablari

MVP uchun minimal maqsadlar:

- kamera resolution: 640x480 yoki 1280x720;
- real-time target: 15–30 FPS;
- detection latency: 100–200 ms;
- OCR faqat so‘ralganda ishlashi;
- model lazy loading;
- GPU bo‘lmasa ONNX/CPU fallback;
- kamera thread’i UI’ni bloklamasligi;
- frame queue haddan tashqari kattalashmasligi;
- vision service to‘xtaganda kamera albatta release qilinishi.

## 17. Test plan

### Unit testlar

- bbox conversion;
- confidence filtering;
- gesture mapping;
- event serialization;
- OCR parsing;
- zone detection;
- privacy blur.

### Integration testlar

- camera start/stop;
- detector pipeline;
- dashboard telemetry;
- voice command dispatch;
- Telegram alert;
- model fallback.

### Manual testlar

- qorong‘i xona;
- kuchli yorug‘lik;
- kamera yo‘q holat;
- kamera boshqa dasturda band holat;
- bir nechta odam;
- tez harakat;
- qo‘l qisman ko‘rinishi;
- OCR uchun burilgan hujjat;
- shubhali QR link;
- past-end CPU.

## 18. Privacy va safety qoidalari

- kamera faqat foydalanuvchi komandasi bilan yoqiladi;
- kamera ishlayotgani dashboard’da aniq ko‘rsatiladi;
- recording uchun alohida confirmation kerak;
- face recognition opt-in bo‘ladi;
- face data local saqlanadi;
- QR URL avtomatik ochilmaydi;
- xavfli desktop action’lar confirmation talab qiladi;
- noma’lum model yoki external API ishlatilsa bu holat ko‘rsatiladi;
- API key va biometric data log’lanmaydi;
- barcha vision servislar uchun emergency stop mavjud bo‘ladi.

## Yakuniy natija

Ushbu plan bajarilgach, Kaizumi quyidagi darajaga chiqadi:

```text
Ko‘radi       → obyekt, odam, yuz, gesture, text
Tushunadi     → rasm, savol, harakat va anomal holat
Gapiradi      → natijani ovoz bilan aytadi
Boshqaradi    → gesture va voice orqali kompyuterga action beradi
Ogohlantiradi → dashboard, Telegram va notification orqali xabar beradi
O‘rganadi     → custom Roboflow dataset va personal models orqali rivojlanadi
```

Asosiy start nuqta: **Phase 1 — Vision MVP**.
