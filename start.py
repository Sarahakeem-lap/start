"""
مشغل خادم إيفرو — Evro OCR Server Launcher
=============================================
تشغيل آمن: فحص البيئة → فتح المتصفح → تشغيل السيرفر
أكثر استقراراً من start.bat — يعمل من أي مكان وفي أي بيئة.
"""
import sys
import os
import subprocess
import time
import webbrowser
from pathlib import Path


# ── المسارات ──
ROOT = Path(__file__).resolve().parent
os.chdir(str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "Application"))
sys.path.insert(0, str(ROOT / "src" / "OCR" / "Pipeline"))
sys.path.insert(0, str(ROOT / "src" / "OCR" / "PostProcessing"))
sys.path.insert(0, str(ROOT))


def check_dependencies() -> bool:
    """فحص المكتبات المطلوبة."""
    print("📦 [1/4] فحص البيئة...")
    ok = True

    required = [
        ("fitz", "pymupdf"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pytesseract", "pytesseract"),
        ("multipart", "python-multipart"),
    ]

    for module_name, pip_name in required:
        try:
            __import__(module_name)
            print(f"   ✅ {pip_name}")
        except ImportError:
            print(f"   ❌ {pip_name} غير موجود. شغّل: pip install {pip_name}")
            ok = False

    if ok:
        print("   ✅ جميع المكتبات مثبتة")
    return ok


def kill_old_server():
    """قتل أي سيرفر يعمل على البورت 8000."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = s.connect_ex(("127.0.0.1", 8000))
        s.close()
        if result == 0:
            print("   🔄 البورت 8000 مشغول — جاري إنهاء العملية القديمة...")
            if sys.platform == "win32":
                # ابحث عن عملية Python تستمع على 8000
                try:
                    output = subprocess.check_output(
                        'netstat -ano | findstr ":8000" | findstr "LISTENING"',
                        shell=True, timeout=5, text=True,
                    )
                    for line in output.strip().split("\n"):
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            subprocess.run(
                                ["taskkill", "/F", "/PID", pid],
                                capture_output=True, timeout=5,
                            )
                            print(f"   ✅ تم إنهاء العملية {pid}")
                except subprocess.TimeoutExpired:
                    pass
                except subprocess.CalledProcessError:
                    pass
            time.sleep(1)
            print("   ✅ البورت 8000 متاح الآن")
    except Exception:
        pass


def clean_cache():
    """تنظيف الذاكرة المؤقتة."""
    try:
        import shutil
        count = 0
        for p in Path(".").rglob("__pycache__"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                count += 1
        if count:
            print(f"   🧹 تم تنظيف {count} مجلد __pycache__")
    except Exception:
        pass


def start_server():
    """تشغيل السيرفر وفتح المتصفح."""
    print("\n🚀 [3/4] تشغيل السيرفر...")
    print(f"   📂 المسار: {ROOT}")
    print(f"   🌐 افتح: http://localhost:8000")
    print()

    # فتح المتصفح بعد ثانية (لإعطاء السيرفر وقتاً)
    def _open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:8000")

    import threading
    t = threading.Thread(target=_open_browser, daemon=True)
    t.start()

    # تشغيل السيرفر
    from web_server import app
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


def main():
    """نقطة الدخول الرئيسية."""
    print()
    print("=" * 50)
    print("  📖  Evro OCR Engine — Web Server")
    print("  محرك إيفرو للتعرف الضوئي v3.0")
    print("=" * 50)
    print()

    # الخطوة 1: تنظيف
    print("🧹 [1/4] تنظيف الذاكرة المؤقتة...")
    clean_cache()
    print("   ✅ تم")
    print()

    # الخطوة 2: فحص البيئة
    if not check_dependencies():
        print("\n❌ بعض المكتبات مفقودة. شغّل: pip install -r config/requirements.txt")
        input("\nاضغط Enter للخروج...")
        return 1
    print()

    # الخطوة 2.5: قتل السيرفر القديم
    kill_old_server()
    print()

    # الخطوة 3: تشغيل
    try:
        start_server()
    except KeyboardInterrupt:
        print("\n\n👋 تم إيقاف السيرفر")
    except Exception as e:
        print(f"\n❌ خطأ في تشغيل السيرفر: {e}")
        import traceback
        traceback.print_exc()
        input("\nاضغط Enter للخروج...")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
