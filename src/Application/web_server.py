"""
خادم ويب - Evro OCR Web Server
================================
نظام بسيط: رفع PDF → استخراج → تحميل TXT
"""
import os, sys, json, time, threading, uuid, re
from pathlib import Path
from typing import Optional
import fitz

# مسار المشروع
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# إضافة مسارات الملفات الجديدة (بعد إعادة الهيكلة)
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "OCR" / "Pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "OCR" / "PostProcessing"))
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# استيراد المحرك
import extractor
from api_key_manager import APIKeyManager, KeyStoreError

# التحقق من وجود Tesseract
TESSERACT_AVAILABLE = os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

UPLOAD_DIR = PROJECT_ROOT / "uploads"
OUTPUT_DIR = PROJECT_ROOT / "output"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
key_manager = APIKeyManager(PROJECT_ROOT / "config" / "api_keys.dat")

app = FastAPI(title="Evro OCR Engine", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

# حالة المهام (بسيط)
tasks: dict = {}


class APIKeyCreate(BaseModel):
    name: str
    key: str
    enabled: bool = True


class APIKeyUpdate(BaseModel):
    name: Optional[str] = None
    key: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None

# قاعدة بيانات العمليات السابقة (محفوظة في ملف JSON)
HISTORY_FILE = PROJECT_ROOT / "history.json"
def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return []
def save_history(entry: dict):
    h = load_history()
    h.insert(0, entry)
    if len(h) > 50:
        h = h[:50]
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")

def _progress_cb_factory(task_id: str):
    """إنشاء callback لتحديث تقدم المهمة بمعلومات إضافية."""
    start = time.time()
    def cb(current: int, total: int):
        task = tasks.get(task_id)
        if task:
            pct = int((current / max(total, 1)) * 100)
            task["progress"] = pct
            task["pages"] = current
            task["total_pages"] = total
            task["elapsed"] = int(time.time() - start)
            task["message"] = f"صفحة {current} / {total}"
    return cb

@app.post("/api/extract")
async def extract_pdf(
    file: UploadFile = File(...),
    mode: str = Form("auto"),
):
    """رفع PDF وبدء الاستخراج فوراً بمكتبات بايثون 100%."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "يرجى رفع ملف PDF فقط")

    task_id = uuid.uuid4().hex[:8]
    filename = re.sub(r'[\\/*?:"<>|]', "_", file.filename)
    pdf_path = UPLOAD_DIR / f"{task_id}_{filename}"

    content = await file.read()
    pdf_path.write_bytes(content)
    size_mb = round(len(content) / (1024 * 1024), 2)

    # معالجة في الخلفية
    task_start_time = time.time()
    result = {
        "status": "processing",
        "progress": 0,
        "pages": 0,
        "total_pages": 0,
        "chars": 0,
        "elapsed": 0,
        "started_at": task_start_time,
        "message": "بدء المعالجة...",
        "file_name": filename,
    }
    tasks[task_id] = result

    def process():
        try:
            result["message"] = "جاري استخراج النصوص..."
            output_name = Path(filename).stem + ".txt"
            output_path = OUTPUT_DIR / output_name

            # احسب صفحات الـ PDF لتعزيز عرض الإحصائيات الحية
            try:
                doc = fitz.open(str(pdf_path))
                result["total_pages"] = doc.page_count
                doc.close()
            except Exception:
                pass

            def live_progress_cb(cur, total):
                pct = int((cur / max(total, 1)) * 100)
                result["progress"] = pct
                result["pages"] = cur
                result["total_pages"] = total
                result["elapsed"] = int(time.time() - task_start_time)
                result["message"] = f"صفحة {cur} / {total}"

            data = extractor.process_pdf(
                str(pdf_path),
                str(output_path),
                mode=mode,
                progress_cb=live_progress_cb,
            )

            result["status"] = "completed"
            result["progress"] = 100
            result["message"] = "اكتمل الاستخراج!"
            result["file_name"] = output_name
            result["pages"] = data.get("pages", 0)
            result["chars"] = data.get("chars", 0)
            result["engine"] = data.get("engine", "Unknown")
            result["quality_score"] = data.get("quality_score", 0)
            result["qa_warnings"] = data.get("qa_warnings", [])
            result["qa_stats"] = data.get("qa_stats", {})

            # معاينة أول 500 حرف
            txt = output_path.read_text(encoding="utf-8")
            result["preview"] = txt[:500]

            # حفظ في السجل
            save_history({
                "filename": filename,
                "pages": data.get("pages", 0),
                "chars": data.get("chars", 0),
                "engine": data.get("engine", "Unknown"),
                "quality_score": data.get("quality_score", 0),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "completed",
            })
        except Exception as e:
            result["status"] = "failed"
            result["message"] = str(e)
            save_history({
                "filename": filename,
                "error": str(e),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "failed",
            })

    thread = threading.Thread(target=process, daemon=True)
    thread.start()

    return {
        "task_id": task_id,
        "filename": filename,
        "file_name": filename,
        "size_mb": size_mb,
        "mode": mode,
    }


@app.get("/api/task/{task_id}")
async def get_task(task_id: str):
    """الحصول على حالة المهمة."""
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "المهمة غير موجودة")
    return task


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """تحميل ملف TXT أو MD الناتج من أي مكان في المشروع."""
    for f in PROJECT_ROOT.rglob(filename):
        if f.exists():
            import urllib.parse
            quoted = urllib.parse.quote(filename)
            media_type = "text/markdown; charset=utf-8" if filename.endswith(".md") else "text/plain; charset=utf-8"
            return FileResponse(
                str(f),
                media_type=media_type,
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
            )
            
    # Fallback إذا طلب .md ولم يوجد، ابحث عن .txt في كل المشروع واصنعه
    if filename.endswith(".md"):
        txt_name = filename.replace(".md", ".txt")
        for f in PROJECT_ROOT.rglob(txt_name):
            if f.exists():
                md_path = f.with_suffix(".md")
                md_path.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                import urllib.parse
                quoted = urllib.parse.quote(filename)
                return FileResponse(
                    str(md_path),
                    media_type="text/markdown; charset=utf-8",
                    filename=filename,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
                )

    raise HTTPException(404, "الملف غير موجود")


@app.get("/api/history")
async def get_history():
    """سجل العمليات السابقة."""
    return load_history()


@app.get("/api/books")
async def get_books():
    """قائمة الكتب (ملفات TXT) في مجلد الإخراج."""
    books = []
    for f in sorted(OUTPUT_DIR.glob("*.txt"), key=os.path.getmtime, reverse=True)[:20]:
        books.append({
            "name": f.name,
            "stem": f.stem,
            "size": f.stat().st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)),
        })
    return books


@app.get("/api/stats")
async def get_stats():
    """إحصائيات المعالجة."""
    books = list(OUTPUT_DIR.glob("*.txt"))
    return {
        "total_books": len(books),
        "total_chars": sum(f.stat().st_size for f in books),
        "tesseract": TESSERACT_AVAILABLE,
    }


@app.get("/api/keys")
async def get_api_keys():
    """قائمة مفاتيح Google المقنعة؛ الكشف عن القيمة يتطلب إجراءً صريحًا."""
    try:
        return {"keys": key_manager.list_keys(reveal=False), "max_keys": 5}
    except KeyStoreError as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/keys", status_code=201)
async def add_api_key(payload: APIKeyCreate):
    try:
        item = key_manager.add_key(payload.name, payload.key, payload.enabled)
        item.pop("key", None)
        return item
    except KeyStoreError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/keys/{key_id}")
async def update_api_key(key_id: str, payload: APIKeyUpdate):
    try:
        item = key_manager.update_key(
            key_id,
            name=payload.name,
            key=payload.key,
            enabled=payload.enabled,
            priority=payload.priority,
        )
        item.pop("key", None)
        return item
    except KeyError as exc:
        raise HTTPException(404, "المفتاح غير موجود") from exc
    except KeyStoreError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/keys/{key_id}", status_code=204)
async def delete_api_key(key_id: str):
    try:
        key_manager.delete_key(key_id)
    except KeyError as exc:
        raise HTTPException(404, "المفتاح غير موجود") from exc


@app.post("/api/keys/{key_id}/test")
async def test_api_key(key_id: str):
    try:
        result = await key_manager.test_key(key_id)
    except KeyError as exc:
        raise HTTPException(404, "المفتاح غير موجود") from exc
    if not result["valid"]:
        raise HTTPException(result["status"] or 503, result["message"])
    return result


@app.get("/api/keys/{key_id}/reveal")
async def reveal_api_key(key_id: str):
    try:
        item = next(key for key in key_manager.list_keys() if key["id"] == key_id)
    except StopIteration as exc:
        raise HTTPException(404, "المفتاح غير موجود") from exc
    return JSONResponse({"key": item["key"]}, headers={"Cache-Control": "no-store"})


@app.post("/api/keys/test-all")
async def test_all_api_keys():
    return {"results": await key_manager.test_all()}


@app.get("/", response_class=HTMLResponse)
async def index():
    """الصفحة الرئيسية."""
    # البحث عن index.html في كل المواضع المحتملة
    candidates = [
        PROJECT_ROOT / "src" / "Application" / "templates" / "index.html",
        PROJECT_ROOT / "src" / "templates" / "index.html",
    ]
    for candidate in candidates:
        if candidate.exists():
            html = candidate.read_text(encoding="utf-8")
            return HTMLResponse(html)
    raise HTTPException(404, "ملف index.html غير موجود")


if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("Evro OCR Engine — Web Server")
    print(f"افتح: http://localhost:8000")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
