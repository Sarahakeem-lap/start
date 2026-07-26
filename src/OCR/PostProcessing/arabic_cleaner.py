"""
تنظيف النصوص العربية - Arabic Text Cleaner
=============================================
إصدار نظيف، مُحَسَّن للإنتاج.
"""

import re
from typing import List

# -------- إصلاحات شائعة عبر Regex --------
COMMON_REGEX_FIXES = [
    # ال التعريف المفصولة (ا لكتاب -> الكتاب)
    (r"\bا\s+ل", "ال"),

    # أحرف العطف المفصولة (و ال -> وال)
    (r"\bو\s+ال", "وال"),
    (r"\bب\s+ال", "بال"),
    (r"\bك\s+ال", "كال"),
    (r"\bل\s+ال", "لل"),
    (r"\bف\s+ال", "ف"),

    # حروف جر شائعة
    (r"\bف\s+ي", "في"),
    (r"\bع\s+ل", "عل"),
    (r"\bإ\s+ل", "إل"),

    # المشكلة 4: إزالة النقاط العشوائية والزخرفية (• • • •)
    (r'(?:•\s*){2,}', ''),
    (r'(?m)^•\s*(?=[ا-ي])', ''),
    (r'\n•\s*\n', '\n'),

    # المشكلة 6: إصلاح الألف المفصولة والمصطلحات الشائعة
    (r'(?<=[ا-ي])\s+ا\s+(?=[لرزودذ])', 'ا'),
    (r'\bمص\s+در\b', 'مصادر'),
    (r'\bمص\s+ادر\b', 'مصادر'),
    (r'\bال\s+ازئر\b', 'الزائر'),
    (r'\bمق\s+ارن\b', 'مقارن'),
    (r'\bمق\s+ارنة\b', 'مقارنة'),
    (r'\bمق\s+ارنه\b', 'مقارنة'),
    (r'\bد\s+ارسة\b', 'دراسة'),
    (r'\bد\s+ارسه\b', 'دراسة'),
]


def fix_ocr_errors(text: str) -> str:
    """تصحيح أخطاء OCR الشائعة مثل انفصال الكلمات."""
    if not text:
        return ""
    for pattern, repl in COMMON_REGEX_FIXES:
        text = re.sub(pattern, repl, text)

    # تصحيح الكلمات المفككة (أحرف متفرقة بمسافة): مثل م ص ر -> مصر
    text = re.sub(
        r"\b([\u0600-\u06FF])\s+([\u0600-\u06FF])\s+([\u0600-\u06FF])(?:\s+([\u0600-\u06FF]))?",
        lambda m: m.group(0).replace(" ", ""),
        text,
    )

    return text


def join_broken_lines(lines: List[str]) -> List[str]:
    """دمج الأسطر المقطوعة في فقرات متصلة."""
    joined = []
    current = ""

    for line in lines:
        line = line.strip()
        if not line:
            if current:
                joined.append(current)
                current = ""
            joined.append("")
            continue

        # أسطر خاصة: تترك كما هي
        if (
            line.startswith("---")
            or line.startswith("📌")
            or "تنويه" in line
            or line.startswith(("#", "-", "*", "("))
            or line.startswith("ا")
        ):
            if current:
                joined.append(current)
                current = ""
            joined.append(line)
            continue

        if not current:
            current = line
        else:
            # إذا انتهى السطر السابق بنقطة/فاصلة، نبدأ سطراً جديداً
            if current.endswith((".", "؟", "!", ":", "؛", '"', "»")):
                joined.append(current)
                current = line
            else:
                current += " " + line

    if current:
        joined.append(current)

    return joined


def _normalize_units_and_blems(text: str) -> str:
    """توحيد ترقيم الإجابات، الكسور والعمليات الكيميائية البسيطة."""
    if not text:
        return ""

    # تصحيح صيغ كيميائية شائعة (H 2 O -> H2O)
    text = re.sub(r"\b([A-Z][a-z]?)\s+(\d+)\b", r"\1\2", text)

    # تصحيح الكسر 1/2 وما شابه
    text = re.sub(r"\b1\s*/\s*2\b", "½", text)
    text = re.sub(r"\b1\s*/\s*4\b", "¼", text)
    text = re.sub(r"\b3\s*/\s*4\b", "¾", text)

    # توحيد خيارات MCQ الشكل (أ) (ب)...
    text = re.sub(r"\(\s*([أبجد])\s*\)", r"(\1)", text)

    return text


def _clean_format_and_spacing(text: str) -> str:
    """تنسيق المسافات وتوحيد الأسطر الفارغة."""
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# تأجيل الاستيراد لتجنب الاستيراد الدائري
def _lazy_advanced_calls(text: str) -> str:
    try:
        from advanced_parser import correct_academic_terms, parse_math_to_latex

        text = correct_academic_terms(text)
        text = parse_math_to_latex(text)
    except Exception:
        pass
    return text


def clean_arabic_text(text: str, strong: bool = True) -> str:
    """الدالة الرئيسية لتنظيف النصوص العربية."""
    if not text:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="ignore")

    # 1. تنظيف رموز اليونيكود الخفية
    text = re.sub(r"[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. تصحيح أخطاء OCR
    text = fix_ocr_errors(text)

    # 3. معالجة الأسطر
    lines = text.split("\n")
    lines = join_broken_lines(lines)

    # 4. توحيد الترقيم والكسور
    lines = [_normalize_units_and_blems(line) for line in lines]
    text = "\n".join(lines)

    # 5. تنظيف نهائي
    text = _clean_format_and_spacing(text)

    # 6. طبقة المعجم الأكاديمي و LaTeX
    text = _lazy_advanced_calls(text)

    return text


def clean_text_basic(text: str) -> str:
    """تنظيف عربي أساسي."""
    return clean_arabic_text(text, strong=False)
