"""
memory_manager.py — Kaizumi Hafıza Sistemi
============================================
Düzeltmeler:
  - _MEMORY_EVERY_N_TURNS: 3 → 1 (her turda kontrol)
  - Stage 1 YES/NO check daha geniş kriterlere sahip
  - Extraction prompt daha kapsamlı ve agresif
  - Projeleri, favori şeyleri, arkadaşları daha iyi yakalar
"""

import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 400

# Values that look like secrets are never stored — passwords, API keys,
# bearer tokens, credit-card-ish numbers, etc.
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|bearer|authorization|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token|"
    r"AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{16,}|"
    r"xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[0-9A-Za-z]{20,})"
)


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {}
    }


def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()

    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            if isinstance(value, dict) and "value" in value:
                new_val = _truncate_value(str(value["value"]))
            else:
                new_val = _truncate_value(str(value))

            if _SECRET_RE.search(str(key)) or _SECRET_RE.search(str(value)):
                continue

            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    memory = load_memory()
    if _recursive_update(memory, memory_update):
        prune_memory(memory)
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory


def prune_memory(memory: dict, cap: int = 40) -> None:
    """Keep long_term.json from growing unboundedly — cap entries per category,
    keeping the most recently updated ones."""
    if not isinstance(memory, dict):
        return
    for cat_name, cat in memory.items():
        if not isinstance(cat, dict):
            continue
        if len(cat) <= cap:
            continue
        newest = sorted(
            cat.items(),
            key=lambda kv: str(kv[1].get("updated", "")) if isinstance(kv[1], dict) else "",
            reverse=True,
        )[:cap]
        memory[cat_name] = dict(newest)
        print(f"[Memory] ✂️ Pruned {cat_name}: kept {cap} most recent entries")


def should_extract_memory(user_text: str, assistant_text: str, api_key: str) -> bool:
    """
    Stage 1: Hızlı YES/NO kontrolü.
    Öncekinden daha geniş kriterler — favori şeyler, projeler, arkadaşlar da dahil.
    """
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        # Her iki tarafı da gönder — Kaizumi'nin söyledikleri de bilgi içerebilir
        combined = f"User: {user_text[:300]}\nKaizumi: {assistant_text[:200]}"

        prompt = (
            "Does this conversation contain ANY of the following?\n"
            "- Personal facts (name, age, city, job, birthday, nationality)\n"
            "- Preferences or favorites (food, color, music, sport, game, film, book, etc.)\n"
            "- Active projects or goals the user is working on\n"
            "- People in the user's life (friends, family, partner, colleagues)\n"
            "- Things the user wants to do or buy in the future\n"
            "- Any other fact worth remembering long-term\n\n"
            "Reply only YES or NO.\n\nConversation:\n"
            f"{combined}"
        )
        check = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        return "YES" in (check.text or "").upper()
    except Exception as e:
        print(f"[Memory] ⚠️ Stage1 check failed: {e}")
        return False


def extract_memory(user_text: str, assistant_text: str, api_key: str) -> dict:
    """
    Stage 2: Detaylı çıkarım. Her iki tarafı da analiz eder.
    """
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        combined = f"User: {user_text[:500]}\nKaizumi: {assistant_text[:300]}"

        prompt = (
            "Extract ALL memorable personal facts from this conversation. Any language.\n"
            "Return ONLY valid JSON. Use {} if truly nothing is worth saving.\n\n"
            "Category guide:\n"
            "  identity      → name, age, birthday, city, country, job, school, nationality, language\n"
            "  preferences   → ANY favorite or preferred thing:\n"
            "                  favorite_food, favorite_color, favorite_music, favorite_film,\n"
            "                  favorite_game, favorite_sport, favorite_book, favorite_artist,\n"
            "                  favorite_country, hobbies, interests, dislikes, etc.\n"
            "  projects      → projects being built, ongoing work, goals, ideas in progress\n"
            "                  (e.g. kaizumi: 'Building a personal AI assistant')\n"
            "  relationships → people mentioned: friends, family, partner, colleagues\n"
            "                  (e.g. best_friend_ali: 'Best friend, met in university')\n"
            "  wishes        → future plans, things to buy, travel plans, dreams\n"
            "  notes         → anything else worth remembering (habits, schedule, etc.)\n\n"
            "IMPORTANT:\n"
            "- Be LIBERAL: if something MIGHT be worth remembering, include it.\n"
            "- Extract from BOTH user and Kaizumi turns.\n"
            "- Skip: weather, reminders, search results, one-time commands.\n"
            "- Use concise English values regardless of conversation language.\n\n"
            "Format:\n"
            '{"identity":{"name":{"value":"Ali"}},\n'
            ' "preferences":{"favorite_color":{"value":"blue"}, "hobby":{"value":"gaming"}},\n'
            ' "projects":{"kaizumi":{"value":"Personal AI assistant on Windows"}},\n'
            ' "relationships":{"friend_yusuf":{"value":"close friend"}},\n'
            ' "wishes":{"buy_guitar":{"value":"wants an acoustic guitar"}},\n'
            ' "notes":{"works_at_night":{"value":"usually active late at night"}}}\n\n'
            f"Conversation:\n{combined}\n\nJSON:"
        )

        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        raw = (resp.text or "").strip()

        import re
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        if not raw or raw == "{}":
            return {}

        return json.loads(raw)

    except json.JSONDecodeError:
        return {}
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ Extract failed: {e}")
        return {}


def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "…"

    return result + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    if _SECRET_RE.search(key) or _SECRET_RE.search(str(value)):
        return "I can't store that — it looks like a secret (password or key)."
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


def search_memory(query: str, category: str = "") -> str:
    """Search stored long-term facts. Returns a short readable summary.
    `category` optionally narrows to identity|preferences|projects|relationships|wishes|notes."""
    if not query or not query.strip():
        return ""
    q = query.lower().strip()
    memory   = load_memory()
    findings = []

    for cat_name, cat in memory.items():
        if category and cat_name != category:
            continue
        if not isinstance(cat, dict):
            continue
        for key, entry in cat.items():
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val is None:
                continue
            val_s = str(val)
            key_s = str(key).replace("_", " ")
            if q in key_s.lower() or q in val_s.lower():
                findings.append(f"{cat_name}/{key}: {val_s}")

    if not findings:
        return f"I don't have anything saved matching '{query}', sir."
    if len(findings) > 6:
        findings = findings[:6]
    return "I remember: " + "; ".join(findings)


# Alias — eski import'larla uyumluluk için
forget_memory = forget


def clear_memory(category: str = "") -> str:
    """Clear all long-term memory, or just one category.
    Returns a short confirmation string."""
    memory = load_memory()
    cat = category.strip().lower()
    if cat:
        if cat in memory:
            memory[cat] = {}
            save_memory(memory)
            return f"Cleared '{cat}' memory."
        return f"Category '{cat}' not found. Categories: " + ", ".join(memory.keys())
    save_memory(_empty_memory())
    return "All memory cleared."


def memory_stats() -> str:
    """Short summary of how much is stored, per category."""
    memory = load_memory()
    parts = []
    for cat, entries in memory.items():
        if isinstance(entries, dict) and entries:
            parts.append(f"{cat}: {len(entries)}")
    if not parts:
        return "No stored memories yet."
    return "Stored memory — " + ", ".join(parts) + "."