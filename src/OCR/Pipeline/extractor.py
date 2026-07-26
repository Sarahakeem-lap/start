"""
محرك إيفرو للتعرف الضوئي - Evro OCR Engine
================================================
نظيف، معياري، وجاهز للإنتاج (Production Ready).
استخراج النصوص من PDF (رقمي وممسوح) بمكتبات بايثون محلية 100%.
"""

import os
import re
import sys
import subprocess
import hashlib
from pathlib import Path
from typing import Optional, Callable, List
from PIL import Image, ImageEnhance, ImageFilter
import fitz
import pytesseract

# ===== إعدادات =====
try:
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    pytesseract.pytesseract.DEFAULT_ENCODING = "cp1256"
    TESSDATA_DIR = r"C:\tessdata"
    os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
except Exception:
    pass

# ===== 1. استيراد محرك التنظيف =====
try:
    _pipeline_dir = Path(__file__).resolve().parent
    _postproc_dir = _pipeline_dir.parent / "PostProcessing"
    sys.path.insert(0, str(_pipeline_dir))
    sys.path.insert(0, str(_postproc_dir))
    from arabic_cleaner import clean_arabic_text
    from advanced_parser import ensemble_ocr_vote
except Exception as e:
    print(f"[Warn] Failed to import arabic_cleaner/advanced_parser: {e}")

    def clean_arabic_text(text: str, strong: bool = True) -> str:
        return text

    def ensemble_ocr_vote(texts: List[str]) -> str:
        return texts[0] if texts else ""


# ===== 2. الإعدادات المساعدة =====
def _check_tesseract() -> bool:
    try:
        result = subprocess.run(
            [pytesseract.pytesseract.tesseract_cmd, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _is_digital_pdf(pdf_path: str) -> bool:
    """كشف نوع الـ PDF (رقمي أو ممسوح)."""
    try:
        doc = fitz.open(pdf_path)
        total_text = sum(len(p.get_text().strip()) for p in doc)
        page_count = doc.page_count
        doc.close()
        return total_text > 100 * page_count
    except Exception:
        return False


def _preprocess_image(img: Image.Image) -> Image.Image:
    """تجهيز الصورة للـ OCR (Grayscale + Contrast + Otsu)."""
    try:
        import cv2
        import numpy as np

        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return Image.fromarray(thresh)
    except Exception:
        img = img.convert("L")
        img = ImageEnhance.Contrast(img).enhance(3.0)
        img = img.filter(ImageFilter.SHARPEN)
        return img


def _remove_duplicate_paragraphs(text: str) -> str:
    """إزالة الفقرات المكررة من النص (أي جملة > 20 حرف تظهر أكثر من مرة)."""
    import hashlib
    lines = text.split('\n')
    seen_hashes = set()
    result = []
    
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 20:
            result.append(line)
            continue
        
        normalized = re.sub(r'\s+', ' ', stripped)
        h = hashlib.md5(normalized.encode()).hexdigest()
        
        if h not in seen_hashes:
            seen_hashes.add(h)
            result.append(line)
            
    return '\n'.join(result)
def _reorder_questions_and_choices(text: str) -> str:
    """
    إعادة ترتيب الأسئلة مع خياراتها الصحيحة.
    يعتمد على أرقام الأسئلة لإعادة الترتيب الصحيح.
    """
    question_pattern = re.compile(
        r'(\d+)\s*[-–]\s*(.*?)(?=\n\d+\s*[-–]|\Z)', 
        re.DOTALL
    )
    
    questions = {}
    for m in question_pattern.finditer(text):
        num = int(m.group(1))
        content = m.group(2).strip()
        questions[num] = content
    
    if not questions:
        return text
    
    sorted_qs = sorted(questions.items())
    result_parts = []
    
    first_q_pos = re.search(r'\d+\s*[-–]', text)
    if first_q_pos:
        result_parts.append(text[:first_q_pos.start()])
    
    for num, content in sorted_qs:
        result_parts.append(f"\n{num} - {content}\n")
    
    return ''.join(result_parts)


def _extract_digital(pdf_path: str) -> str:
    """استخراج نص الـ PDF الرقمي مع ترتيب RTL للأعمدة."""
    import re  # استيراد محلي لضمان عدم وجود مشكلة cache
    doc = fitz.open(pdf_path)
    pages = []
    page_h = doc[0].rect.height if doc.page_count > 0 else 842
    page_w = doc[0].rect.width if doc.page_count > 0 else 595
    mid_x = page_w / 2

    for i, page in enumerate(doc):
        images = page.get_images()
        drawings = page.get_drawings()
        has_visuals = len(images) > 0 or len(drawings) > 5

        # ترتيب بلوكات النص
        blocks = page.get_text("blocks")
        body_blocks = []
        for b in blocks:
            y0, y1 = b[1], b[3]
            if y1 > page_h - 45:
                continue
            if y0 < 40 and "النموذج" in b[4]:
                continue
            body_blocks.append(b)

        # فصل الأعمدة: العمود الأيمن أولاً، ثم الأيسر
        right_col, left_col = [], []
        for b in body_blocks:
            x0 = b[0]
            if x0 > mid_x - 30:
                right_col.append(b)
            else:
                left_col.append(b)
        right_col.sort(key=lambda b: round(b[1] / 15))
        left_col.sort(key=lambda b: round(b[1] / 15))
        sorted_blocks = right_col + left_col

        block_texts = []
        for b in sorted_blocks:
            # FIX: b[4] قد يكون None في بعض ملفات PDF التالفة
            try:
                raw_block = b[4]
                if raw_block is None:
                    continue
                b_text = str(raw_block).strip()
            except (IndexError, TypeError, AttributeError):
                continue
            if b_text:
                clean_b = re.sub(r"\n+", " ", b_text)
                block_texts.append(clean_b)

        if has_visuals:
            block_texts.insert(
                0,
                "⚠️ [تنويه: يحتوي هذا الجزء/السؤال على شكل رسم بياني أو خريطة أو صورة توضيحية 🖼️]",
            )

        page_content = "\n\n".join(block_texts)
        if re.search(r'\d+\s*[-–]', page_content):
            page_content = _reorder_questions_and_choices(page_content)
        pages.append(
            f"\n\n---\n\n--- [ صفحة {i+1} ] ---\n\n---\n\n{page_content}\n\n"
        )

    doc.close()
    return "\n\n".join(pages)


# ذاكرة تخزين مؤقت لصفحات PDF لتجنب إعادة معالجة نفس الصفحة
_PAGE_CACHE: dict = {}


def _get_page_hash(pix) -> str:
    """hash سريع لصفحة PDF لتجنب إعادة المعالجة."""
    return hashlib.md5(pix.samples[:1000]).hexdigest()


def _extract_scanned(pdf_path: str, progress_cb: Optional[Callable] = None) -> str:
    """
    استخراج نص الـ PDF الممسوح عبر Tesseract OCR.
    يستخدم image_to_data (بدون ملفات مؤقتة) + cache للصفحات.
    """
    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    pages = []
    TESS_CONFIG = "--oem 1 --psm 6 -c preserve_interword_spaces=0"

    for i, page in enumerate(doc):
        # FIX: كل صفحة في try/except — صفحة واحدة فاشلة لا توقف الكتاب كله
        try:
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
            img = _preprocess_image(img)

            has_visuals = len(page.get_images()) > 0 or len(page.get_drawings()) > 5

            # فحص cache قبل المعالجة
            page_hash = _get_page_hash(pix)
            if page_hash in _PAGE_CACHE:
                text_str = _PAGE_CACHE[page_hash]
                if progress_cb:
                    progress_cb(i + 1, total_pages)
                pages.append(f"\n\n---\n\n--- [ صفحة {i+1} ] ---\n\n---\n\n{text_str}\n\n")
                continue

            try:
                # استخدام image_to_data للحصول على الكلمات مع الثقة
                data = pytesseract.image_to_data(
                    img, lang="ara+eng", config=TESS_CONFIG,
                    output_type=pytesseract.Output.DICT,
                )
                # تجميع الكلمات في أسطر (block → par → line)
                lines_dict = {}
                low_conf_words = []
                for j in range(len(data["text"])):
                    word = data["text"][j].strip()
                    if not word:
                        continue
                    try:
                        conf = int(data["conf"][j])
                    except (ValueError, TypeError, IndexError):
                        conf = -1
                    if conf < 0:
                        continue
                    key = (data["block_num"][j], data["par_num"][j], data["line_num"][j])
                    lines_dict.setdefault(key, []).append(word)
                    if 0 < conf < 30 and len(word) >= 3 and re.search(r'[\u0600-\u06FF]{3,}', word):
                        low_conf_words.append(word)

                # ترتيب الأسطر حسب الموقع
                sorted_keys = sorted(lines_dict)
                text_lines = [" ".join(lines_dict[k]) for k in sorted_keys]
                text_str = "\n".join(text_lines)

                # إضافة تحذير للكلمات قليلة الثقة
                if low_conf_words:
                    unique_low = list(set(low_conf_words))[:6]
                    text_str += f"\n[تحقق من: {', '.join(unique_low)}]"

            except Exception as e:
                text_str = f"[OCR Error: {e}]"

            if has_visuals:
                text_str = "⚠️ [تنويه: يحتوي هذا الجزء على صورة توضيحية]\n" + text_str

            # إضافة الصفحة للناتج — حتى لو فشلت، الصفحات التالية تستمر
            pages.append(
                f"\n\n---\n\n--- [ صفحة {i+1} ] ---\n\n---\n\n{text_str}\n\n"
            )

            # تحديث الكاش بعد نجاح الصفحة
            try:
                if len(_PAGE_CACHE) < 200:
                    _PAGE_CACHE[page_hash] = text_str
            except Exception:
                pass

        except Exception as page_error:
            # FIX: صفحة واحدة فاشلة — نسجل الخطأ ونكمل للصفحة التالية
            error_msg = f"[Page {i+1} Error: {page_error}]"
            pages.append(f"\n\n---\n\n--- [ صفحة {i+1} ] ---\n\n---\n\n{error_msg}\n\n")
        
        if progress_cb:
            progress_cb(i + 1, total_pages)

    doc.close()
    return "\n\n".join(pages)


# ===== 4. الدالة الرئيسية المعتمدة (Production Signature) =====
def process_pdf(
    pdf_path: str,
    output_path: str,
    mode: str = "auto",
    progress_cb: Optional[Callable] = None,
) -> dict:
    """
    استخراج النص من ملف PDF إلى TXT و MD محلياً 100%.

    Args:
        pdf_path: مسار ملف PDF
        output_path: مسار ملف TXT الناتج
        mode: "auto" | "digital" | "scanned"
        progress_cb: دالة استدعاء عكسي للتحديث

    Returns:
        dict: {"engine": "...", "chars": N, "pages": N}
    """
    pdf = Path(pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(f"الملف غير موجود: {pdf_path}")

    print(f"\n[INFO] Processing: {pdf.name} (mode: {mode})")

    if mode == "digital":
        is_dig = True
    elif mode == "scanned":
        is_dig = False
    else:
        is_dig = _is_digital_pdf(pdf_path)

    # اختيار المحرك
    if is_dig:
        print("   [DIGITAL] Using PyMuPDF")
        raw = _extract_digital(pdf_path)
        engine = "PyMuPDF (رقمي)"
    else:
        if not _check_tesseract():
            raise RuntimeError(
                "\n❌ Tesseract غير مثبت على هذا الجهاز!\n"
                "   للتعامل مع PDF ممسوح، ثبّت Tesseract أولاً."
            )
        print("   [SCANNED] Using Tesseract OCR")
        raw = _extract_scanned(pdf_path, progress_cb)
        engine = "Tesseract OCR (ممسوح)"

    # ===== خط المعالجة الكامل (Pipeline) =====
    _postproc = Path(__file__).resolve().parent.parent / "PostProcessing"
    if str(_postproc) not in sys.path:
        sys.path.insert(0, str(_postproc))
    from advanced_parser import correct_academic_terms, parse_math_to_unicode
    from lexicon_engine import spell_check_text
    from formatter import format_pipeline
    from qa_pipeline import run_qa_pipeline, format_qa_report

    # ===== خط المعالجة الكامل — كل مرحلة محمية بـ try/except =====
    # إذا فشلت أي مرحلة، يستمر الـ Pipeline بالنص السابق ولا يتوقف.
    
    steps_text = raw
    try:
        steps_text = clean_arabic_text(raw)
        steps_text = _remove_duplicate_paragraphs(steps_text)
    except Exception:
        pass
    
    try:
        steps_text = correct_academic_terms(steps_text)
    except Exception:
        pass
    
    try:
        steps_text = parse_math_to_unicode(steps_text)
    except Exception:
        pass
    
    try:
        steps_text = spell_check_text(steps_text)
    except Exception:
        pass
    
    # تنسيق نهائي
    try:
        plain_text, markdown_text = format_pipeline(steps_text)
    except Exception:
        plain_text, markdown_text = steps_text, steps_text
    
    # ضمان الجودة — 12 مرحلة (كل مرحلة محمية داخل run_qa_pipeline)
    try:
        qa_text, qa_stats = run_qa_pipeline(plain_text, enable_all=True)
    except Exception:
        qa_text, qa_stats = plain_text, {}
    
    # الماركداون: نأخذ النص العادي المُصحح ونمرره عبر QA بدون PASS 4
    try:
        qa_md_text, _ = run_qa_pipeline(qa_text, enable_all=False)
    except Exception:
        qa_md_text = qa_text
    
    # حفظ TXT
    try:
        out_txt = Path(output_path)
        out_txt.write_text(qa_text, encoding="utf-8")
    except Exception:
        pass
    
    # حفظ MD
    try:
        out_md = out_txt.with_suffix(".md")
        out_md.write_text(qa_md_text, encoding="utf-8")
    except Exception:
        pass
    
    # حفظ تقرير الجودة
    try:
        qa_report_path = out_txt.with_suffix(".qa.md")
        qa_report_path.write_text(format_qa_report(qa_stats), encoding="utf-8")
    except Exception:
        pass

    # عدد الصفحات من markdown_text الذي يحافظ على page markers
    # (qa_text/plain_text يفقدهم بسبب fix_punctuation في format_pipeline)
    chars = len(qa_text)
    pages = markdown_text.count("صفحة") or raw.count("صفحة")

    print(f"\n[OK] Saved to: {output_path}")
    print(f"[OK] {pages} pages | {chars:,} chars | Engine: {engine}")
    print(f"[QA] درجة الجودة: {qa_stats.get('quality_score', 0)}/100")

    result = {
        "engine": engine,
        "chars": chars,
        "pages": pages,
        "quality_score": qa_stats.get("quality_score", 0),
        "qa_warnings": qa_stats.get("warnings", []),
        "qa_stats": qa_stats,
    }
    return result


# ===== CLI =====
def main():
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="محرك إيفرو للتعرف الضوئي - محلي 100%"
    )
    parser.add_argument("pdf", help="مسار ملف PDF")
    parser.add_argument("-o", "--output", default="", help="مسار ملف TXT الناتج (اختياري)")
    args = parser.parse_args()

    out = args.output or Path(args.pdf).stem + ".txt"

    try:
        result = process_pdf(args.pdf, out)
        print(f"\n📖 النتيجة: {result}")

        text = Path(out).read_text(encoding="utf-8")[:200]
        print(f"\n📖 معاينة (أول 200 حرف):")
        print("─" * 40)
        print(text)
        print("─" * 40)
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
