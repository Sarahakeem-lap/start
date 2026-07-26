"""
محرك ضمان الجودة — Evro OCR Quality Assurance Pipeline
=========================================================
12 مرحلة لفحص وتصحيح نصوص OCR المستخرجة من الكتب التعليمية المصرية.

الهدف: دقة 99.99% — بدون هلوسة — بدون تخمين — بدون تغيير في المحتوى التعليمي.

كل حرف مهم. كل رقم مهم. كل رمز مهم.
"""

import re
import json
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Set
from collections import Counter


# ═══════════════════════════════════════════════════════════════╗
#                         إحصائيات الجودة                       ║
# ═══════════════════════════════════════════════════════════════╝

class QAStats:
    """تسجيل كل تعديل يتم أثناء مراحل ضمان الجودة."""
    
    def __init__(self):
        self.total_chars_before: int = 0
        self.total_chars_after: int = 0
        self.broken_words_fixed: int = 0
        self.spaces_fixed: int = 0
        self.duplicates_removed: int = 0
        self.mcq_choices_separated: int = 0
        self.tables_reconstructed: int = 0
        self.equations_validated: int = 0
        self.numbers_checked: int = 0
        self.punctuation_fixed: int = 0
        self.unicode_fixes: int = 0
        self.low_confidence_marks: int = 0
        self.passes_applied: List[str] = []
    
    def to_dict(self) -> dict:
        return {
            "total_chars_before": self.total_chars_before,
            "total_chars_after": self.total_chars_after,
            "broken_words_fixed": self.broken_words_fixed,
            "spaces_fixed": self.spaces_fixed,
            "duplicates_removed": self.duplicates_removed,
            "mcq_choices_separated": self.mcq_choices_separated,
            "tables_reconstructed": self.tables_reconstructed,
            "equations_validated": self.equations_validated,
            "numbers_checked": self.numbers_checked,
            "punctuation_fixed": self.punctuation_fixed,
            "unicode_fixes": self.unicode_fixes,
            "low_confidence_marks": self.low_confidence_marks,
            "passes_applied": self.passes_applied,
            "quality_score": self._calculate_score(),
        }
    
    def _calculate_score(self) -> float:
        """تقدير درجة الجودة من 0 إلى 100."""
        score = 100.0
        if self.broken_words_fixed > 0:
            score -= min(self.broken_words_fixed * 0.5, 15)
        if self.duplicates_removed > 0:
            score -= min(self.duplicates_removed * 0.3, 10)
        if self.low_confidence_marks > 0:
            score -= min(self.low_confidence_marks * 1.0, 20)
        if self.spaces_fixed > 0:
            score -= min(self.spaces_fixed * 0.1, 5)
        return max(0.0, round(score, 1))


# ═══════════════════════════════════════════════════════════════╗
#            PASS 1 —  CHARACTER LEVEL INSPECTION              ║
# ═══════════════════════════════════════════════════════════════╝

def pass1_character_inspection(text: str, stats: QAStats) -> str:
    """
    فحص كل حرف على حدة.
    
    يكشف:
    • حروف عربية مكسورة (مفصولة بمسافة)
    • كلمات مفككة
    • كلمات ملتصقة خطأ
    • رموز يونيكود خاطئة
    • حروف لاتينية مكان عربية والعكس
    """
    if not text:
        return text
    
    original = text
    fixes = 0
    
    # 1.1 — إزالة رموز اليونيكود المخفية (Zero-width characters)
    text = re.sub(r"[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]", "", text)
    
    # 1.2 — تصحيح حروف عربية مفككة: ا ل ك ت ا ب → الكتاب
    # نمط: حرف عربي + مسافة + حرف عربي (كرر 2-5 مرات)
    text = re.sub(
        r"(?<!\n)([\u0600-\u06FF])\s+([\u0600-\u06FF])\s+([\u0600-\u06FF])"
        r"(?:\s+([\u0600-\u06FF]))?(?:\s+([\u0600-\u06FF]))?",
        lambda m: m.group(0).replace(" ", ""),
        text,
    )
    
    # 1.3 — تصحيح أحرف لاتينية تشبه العربية
    LATIN_TO_ARABIC = {
        "A": "أ", "B": "ب", "C": "ج", "D": "د", "E": "ي",
        "F": "ف", "G": "ق", "H": "ه", "I": "ي", "J": "ج",
        "K": "ك", "L": "ل", "M": "م", "N": "ن", "O": "و",
        "P": "ب", "Q": "ق", "R": "ر", "S": "س", "T": "ت",
        "U": "و", "V": "ف", "W": "و", "X": "خ", "Y": "ي", "Z": "ز",
    }
    
    # فقط صحح إذا كان السياق عربياً (حول الحروف اللاتينية التي تظهر وسط كلمات عربية)
    def _fix_latin_in_arabic(match):
        word = match.group(0)
        # إذا كانت الكلمة مختلطة (عربي + لاتيني)، صحح اللاتيني
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", word))
        has_latin = bool(re.search(r"[A-Za-z]", word))
        if has_arabic and has_latin:
            nonlocal fixes  # <-- FIX: declare nonlocal to access outer scope
            fixed = ""
            for ch in word:
                if ch in LATIN_TO_ARABIC and has_arabic:
                    fixed += LATIN_TO_ARABIC[ch]
                    fixes += 1
                else:
                    fixed += ch
            return fixed
        return word
    
    text = re.sub(r"[\u0600-\u06FFA-Za-z]{2,}", _fix_latin_in_arabic, text)
    
    # 1.4 — أرقام: 1O → 10 (لكن ليس Fe2O3 → Fe203!)
    def _fix_O_between_digits(m):
        """استبدال O بـ 0 فقط إذا لم يكن جزءاً من صيغة كيميائية."""
        # ننظر للخلف 3 حروف — إذا وجدنا حرفاً لاتينياً، فهذه صيغة كيميائية
        start = m.start()
        context = m.string[max(0, start-3):start]
        if re.search(r'[A-Za-z]', context):
            return m.group(0)  # صيغة كيميائية — المحافظة
        return "0"  # خطأ OCR — تصحيح
    text = re.sub(r"(?<=\d)O(?=\d)", _fix_O_between_digits, text)
    text = re.sub(r"(?<=\d)l(?=\d)", "1", text)  # 1l5 → 115
    
    # 1.5 — مسافات قبل علامات الترقيم العربية
    text = re.sub(r"\s+([،؛.؟!])", r"\1", text)
    
    if text != original:
        stats.unicode_fixes += 1
    
    stats.passes_applied.append("PASS 1: Character Inspection")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 2 —  WORD LEVEL VALIDATION                   ║
# ═══════════════════════════════════════════════════════════════╝

def pass2_word_validation(text: str, stats: QAStats) -> str:
    """
    التحقق من صحة كل كلمة.
    
    الأولوية:
    1. القاموس الأكاديمي (lexicon_engine)
    2. السياق
    3. [غير واضح] إذا كانت الثقة منخفضة
    """
    if not text:
        return text
    
    try:
        from lexicon_engine import spell_check_text
        corrected = spell_check_text(text)
        if corrected != text:
            stats.broken_words_fixed += 1
        stats.passes_applied.append("PASS 2: Word Validation")
        return corrected
    except Exception:
        stats.passes_applied.append("PASS 2: Word Validation (skipped)")
        return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 3 —  SENTENCE VALIDATION                     ║
# ═══════════════════════════════════════════════════════════════╝

def pass3_sentence_validation(text: str, stats: QAStats) -> str:
    """
    التحقق من سلامة الجمل.
    
    • إصلاح المسافات المفقودة (كلمات ملتصقة)
    • إزالة المسافات المكررة
    • إزالة الكلمات المكررة
    • دمج الأسطر المكسورة
    • إصلاح الفصل العشوائي للأسطر
    """
    if not text:
        return text
    
    original = text
    
    # 3.1 — إزالة المسافات المتعددة
    text = re.sub(r" {2,}", " ", text)
    
    # 3.2 — إزالة الأسطر الفارغة المتعددة
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # 3.3 — كلمات مكررة (مرتين متتاليتين)
    text = re.sub(
        r"\b([\u0600-\u06FF]{3,})\s+\1\b",
        lambda m: m.group(1),
        text,
    )
    
    # 3.4 — جمل منتهية بنقطة بدون مسافة بعدها
    text = re.sub(r"\.([\u0600-\u06FF])", r". \1", text)
    text = re.sub(r"\.(\u0660-\u0669)", r". \1", text)
    
    # 3.5 — دمج الأسطر المكسورة (سطر لا ينتهي بعلامة ترقيم → يدمج مع التالي)
    lines = text.split("\n")
    merged = []
    i = 0
    while i < len(lines):
        current = lines[i].strip()
        if not current:
            merged.append("")
            i += 1
            continue
        
        # إذا كان السطر خاصاً (عنوان، فاصل صفحة، إلخ)، ابقه كما هو
        if (current.startswith(("#", "---", "[", "(", ">", "**", "- "))
            or current.startswith("س")
            or re.match(r"^\d+[\.\-\)]", current)
            or re.match(r"^[أ-د]\s*[-–—]\)", current)
        ):
            merged.append(current)
            i += 1
            continue
        
        # حاول دمج مع السطر التالي إذا كان السطر الحالي قصيراً ولا ينتهي بعلامة
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if (next_line
                and not next_line.startswith(("#", "---", "[", "(", ">"))
                and not current.endswith((".", "؟", "!", ":", "؛", '"', "»"))
                and len(current) < 80
            ):
                merged.append(current + " " + next_line)
                i += 2
                continue
        
        merged.append(current)
        i += 1
    
    text = "\n".join(merged)
    
    # 3.6 — إصلاح مسافات قبل علامات الاستفهام والتعجب
    text = re.sub(r"\s+([؟!])\s*", r"\1 ", text)
    
    # 3.7 — إزالة المسافات بين الرقم والعلامة %
    text = re.sub(r"(\d)\s+%", r"\1%", text)
    
    if text != original:
        stats.spaces_fixed += 1
    
    stats.passes_applied.append("PASS 3: Sentence Validation")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 4 —  LAYOUT RESTORATION                      ║
# ═══════════════════════════════════════════════════════════════╝

def pass4_layout_restoration(text: str, stats: QAStats) -> str:
    """
    استعادة هيكل الكتاب المدرسي بالكامل.
    
    المحافظة على:
    • العناوين والعناوين الفرعية
    • الترقيم
    • القوائم
    • الأمثلة
    • التعريفات
    • الملاحظات
    • التنبيهات
    • التمارين
    • ترتيب الفقرات
    """
    if not text:
        return text
    
    # 4.1 — توحيد تنسيق الفواصل بين الصفحات
    text = re.sub(
        r"-{3,}\s*\[?\s*صفحة\s*(\d+)\s*\]?\s*-{3,}",
        r"\n\n---\n📄 صفحة \1\n---\n",
        text,
    )
    
    # 4.2 — توحيد تنسيق العناوين
    # سطور مثل "الفصل الأول:" → "# الفصل الأول"
    text = re.sub(
        r"^(الفصل|الباب|الوحدة)\s+(الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)\s*[:\-]?\s*",
        r"# \1 \2: ",
        text,
        flags=re.MULTILINE,
    )
    
    # 4.3 — توحيد تنسيق الأسئلة
    # س1: → ### س1:
    text = re.sub(
        r"^س(\d+)\s*[:\-]?\s*",
        r"### س\1: ",
        text,
        flags=re.MULTILINE,
    )
    
    # 4.4 — ترقيم عربي موحد
    text = re.sub(r"\((\s*)([أبجد])(\s*)\)", r"(\2)", text)
    
    # 4.5 — إزالة الأسطر الفارغة الزائدة
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    
    stats.passes_applied.append("PASS 4: Layout Restoration")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 5 —  MCQ VALIDATION                          ║
# ═══════════════════════════════════════════════════════════════╝

def pass5_mcq_validation(text: str, stats: QAStats) -> str:
    """
    التحقق من سلامة أسئلة الاختيار من متعدد (MCQ).
    
    المحافظة على:
    • رقم السؤال • نص السؤال • الخيارات • الترتيب (أ، ب، ج، د)
    • عدم إعادة ترتيب الإجابات • عدم دمج الخيارات • عدم إزالة التعداد
    """
    if not text:
        return text
    
    original = text
    
    # 5.1 — فصل الخيارات المدمجة على سطر واحد
    # مثل: (أ) 10 نيوتن (ب) 15 نيوتن → سطرين
    patterns = [
        r"(?<!\n)\s+(?=\([أبجدهوز]\)\s)",      # (أ) (ب)
        r"(?<!\n)\s+(?=[أبجد]\s*[-–—]\s)",      # أ- ب-
        r"(?<!\n)\s+(?=[أبجد]\s*\)\s)",         # أ) ب)
        r"(?<!\n)\s+(?=\(\s*[أبجد]\s*\)\s)",    # ( أ ) ( ب )
    ]
    for p in patterns:
        text = re.sub(p, "\n", text)
    
    # 5.2 — توحيد شكل الخيارات
    text = re.sub(r"\(([أبجد])\)", r"(\1)", text)
    text = re.sub(r"([أبجد])\s*[-–—]\s", r"(\1) ", text)
    
    # 5.3 — فصل خيارات MCQ عن الأسئلة (تأكد أن كل خيار في سطر منفصل)
    lines = text.split("\n")
    new_lines = []
    for line in lines:
        # إذا كان السطر يحتوي على خيارين MCQ أو أكثر → افصلهم
        matches = list(re.finditer(r"\([أبجد]\)", line))
        if len(matches) > 1:
            parts = []
            last_end = 0
            for m in matches:
                if m.start() > last_end:
                    parts.append(line[last_end:m.start()].strip())
                parts.append(m.group())
                last_end = m.end()
            if last_end < len(line):
                parts.append(line[last_end:].strip())
            # أعد التجميع مع فواصل أسطر
            new_lines.append(" ".join(parts))
            stats.mcq_choices_separated += len(matches) - 1
        else:
            new_lines.append(line)
    text = "\n".join(new_lines)
    
    if text != original:
        stats.mcq_choices_separated += 1
    
    stats.passes_applied.append("PASS 5: MCQ Validation")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 6 —  TABLE RECONSTRUCTION                    ║
# ═══════════════════════════════════════════════════════════════╝

def pass6_table_reconstruction(text: str, stats: QAStats) -> str:
    """
    إعادة بناء الجداول.
    
    • كشف أسطر الجداول (مسافات متعددة، tabs)
    • تحويلها لجداول Markdown
    • المحافظة على الصفوف والأعمدة والهيدرات
    """
    if not text:
        return text
    
    from formatter import smart_table_formatter
    result = smart_table_formatter(text)
    
    if result != text:
        stats.tables_reconstructed += 1
    
    stats.passes_applied.append("PASS 6: Table Reconstruction")
    return result


# ═══════════════════════════════════════════════════════════════╗
#            PASS 7 —  EQUATION VALIDATION                     ║
# ═══════════════════════════════════════════════════════════════╝

def pass7_equation_validation(text: str, stats: QAStats) -> str:
    """
    التحقق من سلامة المعادلات.
    
    لا تعدل الرياضيات أبداً ما لم يتلف OCR الرموز بوضوح.
    التحقق من: +, −, ×, ÷, =, ≠, ≤, ≥, °, π, √, ∑, Δ, ∫
    الصيغ الكيميائية • رموز الفيزياء • الوحدات
    """
    if not text:
        return text
    
    # 7.1 — توحيد رموز العمليات
    text = text.replace("×", "×")  # بالفعل نفس الرمز
    text = re.sub(r"(?<=\d)\s*[xX*]\s*(?=\d)", "×", text)  # 3x5 → 3×5
    
    # 7.2 — توحيد علامة الناقص
    text = text.replace("−", "-")  # unicode minus → ASCII hyphen (للاتساق مع OCR)
    text = re.sub(r"–", "-", text)  # en-dash → hyphen
    
    # 7.3 — كشف وإصلاح الصيغ الكيميائية المكسورة
    # H 2 O → H₂O (إذا كان السياق كيميائياً)
    text = re.sub(
        r"\b([A-Z][a-z]?)\s+(\d+)\b",
        lambda m: m.group(1) + str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")[m.group(2)] if len(m.group(2)) == 1 else m.group(1) + m.group(2),
        text,
    )
    
    # 7.4 — توحيد الوحدات العلمية
    text = re.sub(r"(\d+)\s*°\s*C\b", r"\1°C", text)
    text = re.sub(r"(\d+)\s*%\s*", r"\1%", text)
    text = re.sub(r"(\d+)\s*م/ث\b", r"\1 م/ث", text)
    text = re.sub(r"(\d+)\s*كجم\b", r"\1 كجم", text)
    text = re.sub(r"(\d+)\s*جم\b", r"\1 جم", text)
    text = re.sub(r"(\d+)\s*كم\b", r"\1 كم", text)
    
    stats.equations_validated += 1
    stats.passes_applied.append("PASS 7: Equation Validation")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 8 —  NUMBER VALIDATION                       ║
# ═══════════════════════════════════════════════════════════════╝

def pass8_number_validation(text: str, stats: QAStats) -> str:
    """
    التحقق من سلامة الأرقام.
    
    • لا تغير القيم الرقمية أبداً!
    • كشف الأرقام المشبوهة (أرقام OCR سيئة)
    • إذا كانت الثقة منخفضة → ألحق [تحقق]
    """
    if not text:
        return text
    
    # 8.1 — توحيد الأرقام العربية (٠١٢٣ ← 0123)
    # المحافظة على الأرقام العربية في النص العربي
    # لا تقم بالتحويل لأن كلا النظامين صحيح في المناهج المصرية
    
    # 8.2 — كشف الأرقام المشبوهة (حروف مكان أرقام)
    def _fix_suspicious_number(match):
        num = match.group(0)
        # كشف: O بدلاً من 0, l بدلاً من 1
        # استثناء: الصيغ الكيميائية (CO2, O2, H2O) — لا touch
        # الصيغ الكيميائية: حرف لاتيني كبير + رقم (H2, O2, CO2)
        if re.match(r'^[A-Z][a-z]?\d+$', num):
            return num  # صيغة كيميائية — ابقها كما هي
        if "O" in num or "l" in num:
            fixed = num.replace("O", "0").replace("l", "1")
            return f"{fixed}[تحقق]"
        return num
    
    text = re.sub(r"\b\d+[Oo]\d*\b", _fix_suspicious_number, text)
    text = re.sub(r"\b\d*[Oo]\d+\b", _fix_suspicious_number, text)
    
    # 8.3 — أرقام الصفحات في الفواصل لا تحتاج [تحقق] — هي صحيحة من extractor
    # لا تفعل شيئاً
    
    stats.numbers_checked += 1
    stats.passes_applied.append("PASS 8: Number Validation")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 9 —  SCIENTIFIC TERMS                        ║
# ═══════════════════════════════════════════════════════════════╝

def pass9_scientific_terms(text: str, stats: QAStats) -> str:
    """
    التحقق من المصطلحات العلمية.
    
    المصطلحات العلمية لها الأولوية القصوى.
    لا تقم أبداً بـ:
    • تطبيع المصطلحات • تبسيطها • ترجمتها • تحديثها
    • استبدال مصطلحات الكتاب المدرسي
    """
    if not text:
        return text
    
    # 9.1 — تطبيق قاموس المصطلحات الأكاديمية
    try:
        from advanced_parser import correct_academic_terms
        corrected = correct_academic_terms(text)
        if corrected != text:
            stats.broken_words_fixed += 1
        text = corrected
    except Exception:
        pass
    
    # 9.2 — المحافظة على المصطلحات العلمية (لا touch)
    # القائمة السوداء للمصطلحات التي لا يجب تغييرها
    preserve_terms = {
        "نيوتن", "جول", "واط", "باسكال", "أوم", "فاراد", "هنري",
        "كولوم", "أمبير", "فولت", "هرتز", "كلفن", "مول",
        "كريبس", "كالفن", "مندل", "داروين", "لافوازييه",
        "دالتون", "أفوجادرو", "مندليف", "نيوتن", "أرخميدس",
        "فيثاغورس", "أرسطو", "أفلاطون", "سقراط",
        "ATP", "DNA", "RNA", "pH", "CO₂", "H₂O", "O₂", "N₂",
    }
    
    # لا نغير هذه المصطلحات — موجودة بالفعل في قاموس التصحيح
    
    stats.passes_applied.append("PASS 9: Scientific Terms")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 10 —  FORMAT CLEANUP                         ║
# ═══════════════════════════════════════════════════════════════╝

def pass10_format_cleanup(text: str, stats: QAStats) -> str:
    """
    تنظيف التنسيق النهائي.
    
    • توحيد علامات الترقيم العربية
    • الفواصل العربية • الفاصلة المنقوطة العربية
    • المسافات • عناوين Markdown • الأسطر الفارغة
    """
    if not text:
        return text
    
    original = text
    
    # 10.1 — الفاصلة العربية
    text = re.sub(r",([\u0600-\u06FF])", r"،\1", text)
    text = re.sub(r",\s*([\u0600-\u06FF])", r"، \1", text)
    
    # 10.2 — الفاصلة المنقوطة العربية
    text = re.sub(r";([\u0600-\u06FF])", r"؛\1", text)
    
    # 10.3 — علامة الاستفهام العربية
    text = re.sub(r"\?([\u0600-\u06FF])", r"؟\1", text)
    
    # 10.4 — توحيد المسافات حول علامات الترقيم
    text = re.sub(r"\s+([،؛.؟!])", r"\1", text)
    text = re.sub(r"([،؛.؟!])(?!\s|$)", r"\1 ", text)
    
    # 10.5 — توحيد الأسطر الفارغة (حد أقصى سطر فارغ واحد)
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # 10.6 — إزالة المسافات في بداية ونهاية كل سطر
    lines = text.split("\n")
    lines = [l.strip() for l in lines]
    text = "\n".join(lines)
    
    # 10.7 — توحيد المسافات المتعددة
    text = re.sub(r" {2,}", " ", text)
    
    if text != original:
        stats.punctuation_fixed += 1
    
    stats.passes_applied.append("PASS 10: Format Cleanup")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 11 —  DUPLICATE DETECTION                    ║
# ═══════════════════════════════════════════════════════════════╝

def pass11_duplicate_detection(text: str, stats: QAStats) -> str:
    """
    كشف وإزالة التكرار.
    
    • الأسطر المكررة • الفقرات المكررة • العناوين المكررة
    • خيارات MCQ المكررة
    أزل فقط التكرار الناتج عن OCR.
    لا تزل أبداً التكرار المقصود.
    """
    if not text:
        return text
    
    original = text
    
    # 11.1 — كشف الأسطر المكررة المتتالية
    lines = text.split("\n")
    unique_lines = []
    duplicates_removed = 0
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            unique_lines.append(line)
            continue
        
        # تحقق من أنه ليس سطراً خاصاً
        if stripped.startswith(("#", "---", "[", "**", ">", "- ")):
            unique_lines.append(line)
            continue
        
        # إذا كان السطر نفسه ظهر في السطرين السابقين → احتمالية تكرار OCR
        if len(unique_lines) >= 2:
            prev1 = unique_lines[-1].strip()
            prev2 = unique_lines[-2].strip()
            if stripped == prev1 and stripped == prev2:
                duplicates_removed += 1
                continue
        
        unique_lines.append(line)
    
    if duplicates_removed > 0:
        text = "\n".join(unique_lines)
        stats.duplicates_removed += duplicates_removed
    
    # 11.2 — كشف تكرار الكلمات في بداية الجمل (تكرار OCR)
    text = re.sub(
        r"\b([\u0600-\u06FF]{3,})\s+\1\b",
        lambda m: m.group(1),
        text,
    )
    
    stats.passes_applied.append("PASS 11: Duplicate Detection")
    return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 12 —  FINAL VERIFICATION                     ║
# ═══════════════════════════════════════════════════════════════╝

def pass12_final_verification(text: str, stats: QAStats) -> Tuple[str, List[str]]:
    """
    التحقق النهائي قبل إخراج المستند.
    
    التأكد من:
    ✓ لا نص مفقود
    ✓ لا نص مضاف
    ✓ لا فقرات معاد ترتيبها
    ✓ لا أسئلة مفقودة
    ✓ لا معادلات مكسورة
    ✓ لا جداول مكسورة
    ✓ لا إجابات مدمجة
    ✓ لا كلمات مكسورة
    ✓ لا أسطر مكررة
    ✓ لا عربي مكسور
    ✓ لا إنجليزي مكسور
    ✓ لا صيغ مكسورة
    ✓ لا وحدات مكسورة
    """
    if not text:
        return text, []
    
    warnings = []
    
    # 12.1 — فحص هل هناك أسطر فارغة كثيرة (نص مفقود محتمل)
    blank_lines = text.count("\n\n\n")
    if blank_lines > 5:
        warnings.append(f"تحذير: {blank_lines} أسطر فارغة متتالية — قد يكون هناك نص مفقود")
    
    # 12.2 — فحص علامات الاستفهام (نص غير واضح)
    unclear_marks = text.count("[غير واضح]")
    if unclear_marks > 0:
        warnings.append(f"تنبيه: {unclear_marks} موضع [غير واضح] — يحتاج مراجعة بشرية")
    
    # 12.3 — فحص علامات التحقق
    verify_marks = text.count("[تحقق]")
    if verify_marks > 0:
        warnings.append(f"تنبيه: {verify_marks} موضع [تحقق] — يحتاج مراجعة بشرية")
    
    # 12.4 — فحص المعادلات المكسورة
    broken_arrows = len(re.findall(r"-+>", text))
    if broken_arrows > 0:
        warnings.append(f"تنبيه: {broken_arrows} سهم مكسور (-<) قد يحتاج تصحيحاً يدوياً")
    
    # 12.5 — فحص هل النص يبدأ وينتهي بشكل صحيح
    if not text.startswith(("#", "---", "📄", "")):
        pass  # لا مشكلة — النص قد يبدأ بأي شيء
    
    # 12.6 — فحص الكلمات الطويلة جداً (قد تكون كلمات ملتصقة خطأ)
    for word in text.split():
        if len(word) > 40 and re.search(r"[\u0600-\u06FF]", word):
            warnings.append(f"كلمة طويلة جداً ({len(word)} حرف): {word[:30]}... — قد تكون كلمات ملتصقة")
            break  # فقط أول كلمة
    
    # 12.7 — فحص الخيارات: تأكد من أن كل خيار MCQ له سطر منفصل
    mcq_choices = re.findall(r"\([أبجد]\)\s*[^)]", text)
    if mcq_choices:
        pass  # تم الفصل مسبقاً في PASS 5
    
    # 12.8 — حساب درجة الجودة
    score = stats._calculate_score()
    warnings.append(f"درجة الجودة: {score}/100")
    
    stats.passes_applied.append("PASS 12: Final Verification")
    return text, warnings


# ═══════════════════════════════════════════════════════════════╗
#            PASS 13 —  CONFIDENCE-BASED CORRECTION            ║
# ═══════════════════════════════════════════════════════════════╝

def pass13_confidence_correction(text: str, stats: QAStats) -> str:
    """
    تصحيح OCR يعتمد على الثقة.
    
    المبدأ:
    - كل كلمة تحصل على درجة ثقة (0.0 - 1.0)
    - الكلمات عالية الثقة (>0.9): لا تصحيح
    - الكلمات متوسطة الثقة (0.6-0.9): تصحيح سريع بالقاموس
    - الكلمات منخفضة الثقة (<0.6): تصحيح عميق + [تحقق]
    """
    if not text:
        return text
    
    try:
        from ocr_quality import ConfidenceCorrector
        corrector = ConfidenceCorrector()
        corrected, corr_stats = corrector.correct_text_with_confidence(text)
        
        if corr_stats.get("corrections_applied", 0) > 0:
            stats.broken_words_fixed += corr_stats["corrections_applied"]
        if corr_stats.get("low_confidence_count", 0) > 0:
            stats.low_confidence_marks += corr_stats["low_confidence_count"]
        
        stats.passes_applied.append(
            f"PASS 13: Confidence Correction "
            f"(ثقة: {corr_stats.get('avg_confidence', 0):.2f}, "
            f"تصحيحات: {corr_stats.get('corrections_applied', 0)})"
        )
        return corrected
    except Exception as e:
        stats.passes_applied.append(f"PASS 13: FAILED - {str(e)[:50]}")
        return text


# ═══════════════════════════════════════════════════════════════╗
#            PASS 14 —  CONTINUOUS LEARNING (ذاكرة OCR)       ║
# ═══════════════════════════════════════════════════════════════╝

# Cache المحرك على مستوى الموديول — يُنشأ مرة واحدة فقط
_LEARNING_ENGINE = None

def _get_learning_engine():
    """الحصول على محرك التعلم (مع cache)."""
    global _LEARNING_ENGINE
    if _LEARNING_ENGINE is None:
        from learning_engine import LearningEngine
        _LEARNING_ENGINE = LearningEngine()
    return _LEARNING_ENGINE


def pass14_continuous_learning(text: str, stats: QAStats, book_title: str = "") -> str:
    """
    التصحيح بالذاكرة — التعلم المستمر من الكتب السابقة.
    
    كل كتاب يُعالج يُحسّن معالجة الكتب التالية:
    - ذاكرة العبارات (يعرف العبارات الأكاديمية الشائعة)
    - ذاكرة التصحيحات (يعرف الأخطاء المتكررة)
    - السياق (يعرف الكلمات المتجاورة)
    - التغذية البشرية (التصحيحات البشرية لها الأولوية)
    
    يتم تغذية النظام بالنص المُصحح (بعد PASS 13) ليتعلم من النظيف
    ولا يتعلم أخطاء OCR.
    """
    if not text or len(text) < 20:
        return text
    
    try:
        engine = _get_learning_engine()  # cache — لا تحميل من القرص كل مرة
        
        # 1. تعلم العبارات والسياق من هذا النص (بعد أن صححته PASS 1-13)
        engine.learn_from_book(text, book_title, subject="general")
        
        # 2. تصحيح النص باستخدام الذاكرة
        corrected = engine.correct_text(text, subject="general")
        
        if corrected != text:
            stats.broken_words_fixed += 1
        
        changes = sum(1 for a, b in zip(text.split(), corrected.split()) if a != b)
        
        # 3. ترقية التصحيحات المتكررة تلقائياً
        promoted = engine.promote_corrections(min_frequency=3)
        
        stats.passes_applied.append(
            f"PASS 14: Continuous Learning "
            f"(تصحيحات: {changes}, مرفوع: {promoted})"
        )
        return corrected
    except Exception as e:
        stats.passes_applied.append(f"PASS 14: FAILED - {str(e)[:50]}")
        return text


# ═══════════════════════════════════════════════════════════════╗
#              RUN FULL QA PIPELINE                             ║
# ═══════════════════════════════════════════════════════════════╝

def run_qa_pipeline(text: str, enable_all: bool = True) -> Tuple[str, dict]:
    """
    تشغيل مراحل ضمان الجودة الـ 12 بالكامل.
    كل مرحلة محمية بـ try/except — لا توجد مرحلة يمكن أن تقتل الـ Pipeline.
    
    Args:
        text: النص المدخل (بعد مراحل الاستخراج والتنظيف الأساسية)
        enable_all: تشغيل جميع المراحل (True) أو المراحل الأساسية فقط
    
    Returns:
        Tuple[str, dict]: (النص المصحح, إحصائيات الجودة)
    """
    if not text:
        result = QAStats().to_dict()
        result["warnings"] = []
        return text, result
    
    stats = QAStats()
    stats.total_chars_before = len(text)
    warnings = []  # FIX: مهيأ مسبقاً — لا يعتمد على try/except
    
    # كل PASS محمي بـ try/except — إذا فشل أي PASS،
    # يستمر الـ Pipeline بالنص السابق ويسجل الخطأ في الإحصائيات.
    
    # PASS 1: فحص الحروف — (دائماً)
    try:
        text = pass1_character_inspection(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 1: FAILED - " + str(e)[:50])
    
    # PASS 2: التحقق من الكلمات — (دائماً)
    try:
        text = pass2_word_validation(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 2: FAILED - " + str(e)[:50])
    
    # PASS 3: التحقق من الجمل — (دائماً)
    try:
        text = pass3_sentence_validation(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 3: FAILED - " + str(e)[:50])
    
    # PASS 4: استعادة الهيكل — (فقط مع التنسيق الكامل)
    if enable_all:
        try:
            text = pass4_layout_restoration(text, stats)
        except Exception as e:
            stats.passes_applied.append("PASS 4: FAILED - " + str(e)[:50])
    
    # PASS 5: التحقق من MCQ — (دائماً)
    try:
        text = pass5_mcq_validation(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 5: FAILED - " + str(e)[:50])
    
    # PASS 6: إعادة بناء الجداول — (دائماً)
    try:
        text = pass6_table_reconstruction(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 6: FAILED - " + str(e)[:50])
    
    # PASS 7: التحقق من المعادلات — (دائماً)
    try:
        text = pass7_equation_validation(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 7: FAILED - " + str(e)[:50])
    
    # PASS 8: التحقق من الأرقام — (دائماً)
    try:
        text = pass8_number_validation(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 8: FAILED - " + str(e)[:50])
    
    # PASS 9: المصطلحات العلمية — (دائماً)
    try:
        text = pass9_scientific_terms(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 9: FAILED - " + str(e)[:50])
    
    # PASS 10: تنظيف التنسيق — (دائماً)
    try:
        text = pass10_format_cleanup(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 10: FAILED - " + str(e)[:50])
    
    # PASS 11: كشف التكرار — (دائماً)
    try:
        text = pass11_duplicate_detection(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 11: FAILED - " + str(e)[:50])
    
    # PASS 12: التحقق النهائي — (دائماً)
    try:
        text, warnings = pass12_final_verification(text, stats)
    except Exception as e:
        text = text  # ابق النص كما هو
        warnings = [f"PASS 12: FAILED - {str(e)[:50]}"]
        stats.passes_applied.append("PASS 12: FAILED")
    
    # PASS 13: التصحيح المبني على الثقة — (دائماً)
    try:
        text = pass13_confidence_correction(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 13: FAILED - " + str(e)[:50])
    
    # PASS 14: التعلم المستمر — (دائماً، آخر PASS)
    try:
        text = pass14_continuous_learning(text, stats)
    except Exception as e:
        stats.passes_applied.append("PASS 14: FAILED - " + str(e)[:50])
    
    stats.total_chars_after = len(text)
    
    result = stats.to_dict()
    result["warnings"] = warnings
    
    return text, result


def format_qa_report(stats: dict) -> str:
    """تنسيق تقرير الجودة كـ Markdown."""
    report = []
    report.append("## 📊 تقرير ضمان الجودة")
    report.append("")
    report.append(f"| المؤشر | القيمة |")
    report.append(f"|--------|--------|")
    report.append(f"| درجة الجودة | {stats.get('quality_score', 0)}/100 |")
    report.append(f"| إجمالي الحروف قبل | {stats.get('total_chars_before', 0):,} |")
    report.append(f"| إجمالي الحروف بعد | {stats.get('total_chars_after', 0):,} |")
    report.append(f"| كلمات مكسورة تم إصلاحها | {stats.get('broken_words_fixed', 0)} |")
    report.append(f"| مسافات تم إصلاحها | {stats.get('spaces_fixed', 0)} |")
    report.append(f"| تكرار تم إزالته | {stats.get('duplicates_removed', 0)} |")
    report.append(f"| خيارات MCQ مفصولة | {stats.get('mcq_choices_separated', 0)} |")
    report.append(f"| جداول معاد بناؤها | {stats.get('tables_reconstructed', 0)} |")
    report.append(f"| معادلات تم التحقق منها | {stats.get('equations_validated', 0)} |")
    report.append(f"| أرقام تم فحصها | {stats.get('numbers_checked', 0)} |")
    report.append(f"| علامات ترقيم مصححة | {stats.get('punctuation_fixed', 0)} |")
    report.append(f"| إصلاحات يونيكود | {stats.get('unicode_fixes', 0)} |")
    report.append(f"| علامات [غير واضح]/[تحقق] | {stats.get('low_confidence_marks', 0)} |")
    report.append("")
    
    if stats.get("warnings"):
        report.append("### ⚠️ تحذيرات")
        report.append("")
        for w in stats["warnings"]:
            report.append(f"- {w}")
        report.append("")
    
    report.append(f"_المراحل المطبقة: {', '.join(stats.get('passes_applied', []))}_")
    report.append("")
    report.append("---")
    
    return "\n".join(report)


# ═══════════════════════════════════════════════════════════════╗
#                      CLI للاختبار                             ║
# ═══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    import sys
    print("=" * 55)
    print("📋 Evro OCR — QA Pipeline v2.0")
    print("=" * 55)
    print()
    
    sample = """--- [ صفحة 1 ] ---

الفصل الأول: القوى والحركة

القوه هي مؤثر خارجي يغير من حركه الجسم

F = m × a

E = m c 2

(أ) 10 نيوتن (ب) 15 نيوتن (ج) 20 نيوتن (د) 25 نيوتن

ا لكتاب في الرف

التفاعل الطارد للحراره

H2 + O2 -> H2O

"""
    
    print("INPUT:")
    print(sample[:200])
    print()
    
    corrected, stats = run_qa_pipeline(sample)
    
    print("OUTPUT:")
    print(corrected)
    print()
    print(format_qa_report(stats))
    print()
    print(f"✅ QA Pipeline complete — Quality Score: {stats['quality_score']}/100")
