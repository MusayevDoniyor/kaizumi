"""One-shot setup: install dependencies, Playwright browsers, and create config files."""
import shutil
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def create_default_configs() -> None:
    """Copy *.example.json -> *.json so the app runs without manual config editing."""
    cfg_dir = ROOT / "config"
    cfg_dir.mkdir(exist_ok=True)
    for example in sorted(cfg_dir.glob("*.example.json")):
        target = cfg_dir / (example.name.replace(".example.json", ".json"))
        if not target.exists():
            shutil.copyfile(example, target)
            print(f"  created {target.name}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("Installing requirements...")
    subprocess.run([sys.executable, "-m", "pip", "install",
                    "-r", str(ROOT / "requirements.txt")], check=True)

    print("Installing Playwright Chromium browser...")
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    except Exception as e:
        print(f"  Note: Playwright browser install deferred ({e}).")

    print("Creating default config files...")
    create_default_configs()

    print("\nSetup complete! Open config/api_keys.json, add your Gemini API key, and run:")
    print("   python main.py")


if __name__ == "__main__":
    main()
