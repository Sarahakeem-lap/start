"""
محرك قياس جودة OCR — OCR Quality & Correction Engine
======================================================
مصفوفة تشابه الحروف العربية — التصحيح المبني على الثقة — تقييم CAR/WAR

ثلاث طبقات:
1. مصفوفة تشابه الحروف العربية (ArabicLetterConfusion)
2. مصحح يعتمد على الثقة (ConfidenceCorrector)
3. مقيم الجودة المستمر (OCRQualityMetrics)
"""

import re
import json
import math
from typing import Dict, List, Set, Tuple, Optional
from collections import Counter, defaultdict

# استيراد القاموس على مستوى الموديول لتجنب إعادة الاستيراد في كل دالة
try:
    from lexicon_engine import FULL_LEXICON, LEXICON_LOWERCASE, spell_check_word, get_lexicon_stats
    _LEXICON_AVAILABLE = True
except Exception:
    _LEXICON_AVAILABLE = False
    FULL_LEXICON: Set[str] = set()
    LEXICON_LOWERCASE: Dict[str, str] = {}
    def spell_check_word(w): return w
    def get_lexicon_stats(): return {}


# ═══════════════════════════════════════════════════════════════╗
#  الطبقة 1 — مصفوفة تشابه الحروف العربية في OCR              ║
# ═══════════════════════════════════════════════════════════════╝

class ArabicLetterConfusion:
    """
    مصفوفة تشابه الحروف العربية — تحدد أي الحروف يخطئ OCR بينها.

    كل مدخل: حرف ← قائمة الحروف التي يمكن الخلط بينها
    مع درجة الثقة (0.0 = مختلف تماماً، 1.0 = متطابق)
    """

    # ─── التشابهات الرئيسية في OCR العربي ───

    # حروف متشابهة في الشكل: الفرق بنقط/تشكيل فقط
    HIGH_CONFUSION: Dict[str, List[str]] = {
        # بائية: الفرق بنقطة واحدة
        "ب": ["ت", "ث", "ن", "ي"],
        "ت": ["ب", "ث", "ن", "ي"],
        "ث": ["ب", "ت", "ن", "ي"],
        "ن": ["ب", "ت", "ث", "ي"],
        "ي": ["ب", "ت", "ث", "ن"],

        # جيمية: الفرق بنقطة
        "ج": ["ح", "خ"],
        "ح": ["ج", "خ"],
        "خ": ["ج", "ح"],

        # سينية: تشابه شكل
        "س": ["ش"],
        "ش": ["س"],

        # صادية
        "ص": ["ض"],
        "ض": ["ص"],

        # طائية
        "ط": ["ظ"],
        "ظ": ["ط"],

        # عينية
        "ع": ["غ"],
        "غ": ["ع"],

        # فائية وقافية
        "ف": ["ق", "و"],
        "ق": ["ف"],
        "و": ["ف", "ي"],

        # دالية
        "د": ["ذ"],
        "ذ": ["د"],

        # رائية
        "ر": ["ز"],
        "ز": ["ر"],

        # ألفات
        "ا": ["أ", "إ", "آ", "ى"],
        "أ": ["ا", "إ", "آ"],
        "إ": ["ا", "أ", "آ"],
        "آ": ["ا", "أ", "إ"],
        "ى": ["ا", "ي"],

        # هاء وتاء مربوطة (أكثر خطأ في OCR)
        "ه": ["ة", "ح"],
        "ة": ["ه", "ت"],

        # لام
        "ل": ["لا", "ك"],
        "ك": ["ل", "م"],
        "م": ["ك"],
    }

    # حروف متوسطة التشابه
    MEDIUM_CONFUSION: Dict[str, List[str]] = {
        "ل": ["د", "ن"],
        "ا": ["ل", "ع"],
        "س": ["ص", "ق"],
        "م": ["ن", "و"],
        "ع": ["ا", "د"],
        "ق": ["ف", "و", "د"],
        "ط": ["ص", "ف"],
        "و": ["ي", "ن"],
        "د": ["و", "ر"],
    }

    # حروف لاتينية تشبه عربية (للخلط في OCR)
    LATIN_ARABIC: Dict[str, List[str]] = {
        "A": ["ا", "أ", "د"],
        "B": ["ب", "8"],
        "C": ["ج", "ح", "0"],
        "D": ["د", "0"],
        "E": ["ي", "ع"],
        "F": ["ف", "ق"],
        "G": ["ق", "ج"],
        "H": ["ه", "ح", "8"],
        "I": ["ا", "ل", "1"],
        "J": ["ج", "ح"],
        "K": ["ك", "ل"],
        "L": ["ل", "ا", "1"],
        "M": ["م"],
        "N": ["ن", "م"],
        "O": ["و", "0"],
        "P": ["ب", "ف"],
        "Q": ["ق", "ف"],
        "R": ["ر"],
        "S": ["س", "ص", "5"],
        "T": ["ط", "ت"],
        "U": ["و", "ن"],
        "V": ["ف", "و"],
        "W": ["و", "ن"],
        "X": ["خ"],
        "Y": ["ي", "و"],
        "Z": ["ز", "2"],
        "0": ["و", "ا", "O"],
        "1": ["ل", "ا", "I", "l"],
        "2": ["ز", "Z"],
        "5": ["س", "S"],
        "8": ["ب", "B", "ه", "H"],
    }

    @classmethod
    def get_confusion_score(cls, char1: str, char2: str) -> float:
        """
        درجة احتمال الخلط بين حرفين عربيين في OCR.
        1.0 = يخطئ OCR دائماً بينهما
        0.0 = لا يخطئ OCR بينهما أبداً
        """
        if char1 == char2:
            return 1.0

        # فحص التشابه العالي
        for key, values in cls.HIGH_CONFUSION.items():
            if key == char1 and char2 in values:
                return 0.85
            if key == char2 and char1 in values:
                return 0.85

        # فحص التشابه المتوسط
        for key, values in cls.MEDIUM_CONFUSION.items():
            if key == char1 and char2 in values:
                return 0.55
            if key == char2 and char1 in values:
                return 0.55

        # فحص لاتيني-عربي
        for key, values in cls.LATIN_ARABIC.items():
            if key == char1 and char2 in values:
                return 0.65
            if key == char2 and char1 in values:
                return 0.65

        # حروف مختلفة تماماً
        return 0.0

    @classmethod
    def get_word_confusion_candidates(
        cls, word: str, max_distance: int = 2, min_confidence: float = 0.4
    ) -> List[Tuple[str, float]]:
        """
        توليد كلمات مرشحة بناءً على تشابه الحروف.
        مفيدة للكلمات التي لم توجد في القاموس.
        """
        if not _LEXICON_AVAILABLE or not FULL_LEXICON:
            return []

        candidates = []
        word_clean = re.sub(r"[^\u0600-\u06FFa-zA-Z]", "", word)
        if not word_clean or len(word_clean) < 3:
            return []

        # تحسين الأداء: نرشح lexicon حسب طول الكلمة أولاً
        len_min = len(word_clean) - max_distance
        len_max = len(word_clean) + max_distance

        for lexicon_word in FULL_LEXICON:
            wlen = len(lexicon_word)
            if wlen < len_min or wlen > len_max:
                continue

            # حساب مسافة التحرير مع أوزان التشابه
            distance = cls._weighted_levenshtein(word_clean, lexicon_word)
            max_len = max(len(word_clean), wlen)
            if max_len == 0:
                continue
            similarity = 1.0 - (distance / max_len)

            if similarity >= min_confidence:
                candidates.append((lexicon_word, similarity))

        # ترتيب حسب أعلى تشابه
        candidates.sort(key=lambda x: -x[1])
        return candidates[:10]

    @staticmethod
    def _weighted_levenshtein(s1: str, s2: str) -> float:
        """
        مسافة ليفنشتاين مع أوزان — استبدال حرف متشابه يكلف أقل.
        """
        if not s1 or not s2:
            return max(len(s1), len(s2))

        # مصفوفة ثنائية الأبعاد
        rows, cols = len(s1) + 1, len(s2) + 1
        dp = [[0.0] * cols for _ in range(rows)]
        for i in range(rows):
            dp[i][0] = float(i)
        for j in range(cols):
            dp[0][j] = float(j)

        for i in range(1, rows):
            for j in range(1, cols):
                if s1[i - 1] == s2[j - 1]:
                    cost = 0.0
                else:
                    # استبدال حرف متشابه: تكلفة أقل
                    confusion = ArabicLetterConfusion.get_confusion_score(
                        s1[i - 1], s2[j - 1]
                    )
                    if confusion > 0.5:
                        cost = 0.3  # خطأ OCR محتمل — تكلفة قليلة
                    elif confusion > 0.2:
                        cost = 0.6
                    else:
                        cost = 1.0  # حرف مختلف تماماً

                dp[i][j] = min(
                    dp[i - 1][j] + 0.8,    # حذف
                    dp[i][j - 1] + 0.8,     # إضافة
                    dp[i - 1][j - 1] + cost  # استبدال
                )

        return dp[rows - 1][cols - 1]


# ═══════════════════════════════════════════════════════════════╗
#  الطبقة 2 — التصحيح المبني على الثقة (Confidence Corrector) ║
# ═══════════════════════════════════════════════════════════════╝

class ConfidenceCorrector:
    """
    مصحح OCR يعتمد على الثقة.

    المبدأ:
    - كل كلمة لها درجة ثقة (0.0 - 1.0)
    - الكلمات عالية الثقة (>0.9): لا تدخل التصحيح
    - الكلمات متوسطة الثقة (0.6-0.9): تصحيح سريع بالقواميس
    - الكلمات منخفضة الثقة (<0.6): تصحيح عميق + [تحقق]
    """

    def __init__(self):
        self.confidence_thresholds = {
            "skip": 0.90,        # ثقة عالية — نتجاوز التصحيح
            "quick": 0.70,       # ثقة متوسطة — تصحيح سريع
            "deep": 0.50,        # ثقة منخفضة — تصحيح عميق
        }
        self.corrections_applied = 0
        self.low_confidence_words = []

    def estimate_word_confidence(self, word: str, context_words: List[str] = None) -> float:
        """
        تقدير درجة الثقة في كلمة من OCR.

        العوامل:
        1. طول الكلمة (الكلمات القصيرة أقل ثقة)
        2. وجود حروف غير عربية أو غير لاتينية
        3. وجود حروف متكررة بشكل غير طبيعي
        4. وجود الكلمة في القاموس الأكاديمي
        5. مطابقة الكلمة للسياق (إذا وُجد)
        """
        if not word or len(word) < 1:
            return 0.0

        cleaned = re.sub(r"[^\u0600-\u06FFa-zA-Z]", "", word)
        if not cleaned:
            return 0.0

        score = 1.0

        # 1. طول الكلمة
        if len(cleaned) <= 1:
            score -= 0.5
        elif len(cleaned) == 2:
            score -= 0.2

        # 2. حروف غير متوقعة
        arabic_count = sum(1 for c in cleaned if '\u0600' <= c <= '\u06FF')
        latin_count = sum(1 for c in cleaned if c.isascii() and c.isalpha())
        total_alpha = arabic_count + latin_count

        if total_alpha == 0:
            return 0.3

        # كلمات مختلطة عربي-لاتيني (قد تكون خطأ OCR)
        if arabic_count > 0 and latin_count > 0:
            # إذا كانت الأغلبية عربية، خصم بسيط
            ratio = arabic_count / total_alpha
            if 0.3 < ratio < 0.7:
                score -= 0.3  # مختلط كثيراً
            else:
                score -= 0.1

        # 3. حروف متكررة غير طبيعية
        char_counts = Counter(cleaned)
        max_repeat = max(char_counts.values()) if char_counts else 0
        if max_repeat > len(cleaned) * 0.6:
            score -= 0.3
        if max_repeat > len(cleaned) * 0.8:
            score -= 0.3

        # 4. وجود في القاموس الأكاديمي
        try:
            from lexicon_engine import FULL_LEXICON
            # تطابق تام
            if cleaned in FULL_LEXICON:
                score += 0.15
            # بدون تشكيل
            clean_no_diac = re.sub(r"[\u064B-\u0652]", "", cleaned)
            if clean_no_diac in FULL_LEXICON:
                score += 0.1
            # بدون ال
            if clean_no_diac.startswith("ال") and len(clean_no_diac) > 3:
                if clean_no_diac[2:] in FULL_LEXICON:
                    score += 0.05
        except Exception:
            pass

        # 5. سياق الكلمة — هل الكلمة مألوفة في سياقها؟
        # الكلمات التي تظهر في سياق أكاديمي تحصل على ثقة أعلى
        if context_words and len(context_words) > 1:
            # تحقق من وجود كلمات سياقية مألوفة
            context_str = " ".join(context_words)
            context_keywords = ["القوة", "الطاقة", "الكتلة", "السرعة", "التسارع",
                                "التفاعل", "المعادلة", "الدالة", "الخلية",
                                "الجهاز", "النظام", "المادة", "العنصر"]
            for kw in context_keywords:
                if kw in context_str:
                    score += 0.05
                    break

        return max(0.05, min(1.0, score))

    def correct_with_confidence(
        self, word: str, context_words: List[str] = None
    ) -> Tuple[str, float, str]:
        """
        تصحيح كلمة مع درجة ثقة.

        Returns:
            Tuple[str, float, str]: (الكلمة المصححة, الثقة, نوع التصحيح)
            نوع التصحيح: "exact" | "dictionary" | "confusion" | "low_confidence"
        """
        if not word or len(word) < 2:
            return word, 0.5, "low_confidence"

        cleaned = re.sub(r"[^\u0600-\u06FFa-zA-Z]", "", word)
        if not cleaned:
            return word, 0.5, "low_confidence"

        confidence = self.estimate_word_confidence(cleaned, context_words)

        # ثقة عالية — لا تصحيح
        if confidence >= self.confidence_thresholds["skip"]:
            return word, confidence, "exact"

        # البحث في القاموس (تم استيراد FULL_LEXICON على مستوى الموديول)
        try:
            if not _LEXICON_AVAILABLE:
                raise ImportError("Lexicon not available")

            # تطابق تام في القاموس
            if cleaned in FULL_LEXICON:
                return word, 0.95, "exact"

            # تصحيح سريع بالقواميس
            dict_correction = spell_check_word(cleaned)
            if dict_correction != cleaned:
                # FIX: استخدام replace مع حد 1 لتجنب استبدال كل التكرارات
                corrected_word = word.replace(cleaned, dict_correction, 1)
                return corrected_word, 0.90, "dictionary"

        except Exception:
            pass

        # ثقة متوسطة — تصحيح بمصفوفة التشابه
        if confidence >= self.confidence_thresholds["quick"]:
            candidates = ArabicLetterConfusion.get_word_confusion_candidates(
                cleaned, max_distance=1, min_confidence=0.7
            )
            if candidates:
                best_word, best_score = candidates[0]
                corrected_word = word.replace(cleaned, best_word, 1)
                self.corrections_applied += 1
                return corrected_word, best_score, "confusion"

        # ثقة منخفضة — تصحيح عميق + [تحقق]
        self.low_confidence_words.append((word, confidence))
        self.corrections_applied += 1

        # البحث بقاموس أوسع
        candidates = ArabicLetterConfusion.get_word_confusion_candidates(
            cleaned, max_distance=2, min_confidence=0.3
        )
        if candidates:
            best_word, best_score = candidates[0]
            corrected_word = word.replace(cleaned, best_word, 1)
            if best_score >= 0.5:
                return corrected_word + "[تحقق]", best_score, "low_confidence"

        return word, confidence, "low_confidence"

    def correct_text_with_confidence(self, text: str) -> Tuple[str, dict]:
        """
        تصحيح نص كامل مع تقرير الثقة.

        Returns:
            Tuple[str, dict]: (النص المصحح, إحصائيات التصحيح)
        """
        if not text:
            return text, {}

        self.corrections_applied = 0
        self.low_confidence_words = []
        stats = {
            "exact": 0, "dictionary": 0,
            "confusion": 0, "low_confidence": 0,
            "total_words": 0, "avg_confidence": 0.0,
        }

        words = text.split()
        corrected_words = []
        total_confidence = 0.0

        for i, word in enumerate(words):
            # السياق: 3 كلمات قبل وبعد
            context_start = max(0, i - 3)
            context_end = min(len(words), i + 4)
            context = words[context_start:i] + words[i+1:context_end]

            corrected, conf, corr_type = self.correct_with_confidence(word, context)
            corrected_words.append(corrected)
            stats[corr_type] = stats.get(corr_type, 0) + 1
            total_confidence += conf

        stats["total_words"] = len(words)
        stats["avg_confidence"] = round(
            total_confidence / max(1, len(words)), 3
        )
        stats["corrections_applied"] = self.corrections_applied
        stats["low_confidence_count"] = len(self.low_confidence_words)
        stats["correction_rate"] = round(
            (stats["dictionary"] + stats["confusion"] + stats["low_confidence"])
            / max(1, stats["total_words"]) * 100,
            1
        )

        return " ".join(corrected_words), stats


# ═══════════════════════════════════════════════════════════════╗
#  الطبقة 3 — مقيم الجودة المستمر (OCR Quality Metrics)       ║
# ═══════════════════════════════════════════════════════════════╝

class OCRQualityMetrics:
    """
    قياس جودة OCR مقابل النص المرجعي.

    المقاييس:
    - CER (Character Error Rate)
    - WER (Word Error Rate)
    - CAR (Character Accuracy Rate)
    - WAR (Word Accuracy Rate)
    - Question/Choice Preservation
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """إعادة تعيين جميع المقاييس."""
        self.total_chars = 0
        self.error_chars = 0
        self.total_words = 0
        self.error_words = 0
        self.total_questions = 0
        self.preserved_questions = 0
        self.total_choices = 0
        self.preserved_choices = 0
        self.subject_domain = "general"
        self.page_results: List[dict] = []

    def set_subject(self, subject: str):
        """تحديد المادة الدراسية لتفعيل القاموس المخصص."""
        self.subject_domain = subject

    def measure_page(
        self, ocr_text: str, reference_text: str, page_num: int = 1
    ) -> dict:
        """
        قياس جودة صفحة واحدة.

        Args:
            ocr_text: النص المستخرج
            reference_text: النص المرجعي (من PyMuPDF للـ PDF الرقمي)
            page_num: رقم الصفحة

        Returns:
            dict: مقاييس الجودة للصفحة
        """
        # CAR: حرف مقابل حرف
        cer = self._compute_cer(ocr_text, reference_text)
        car = 1.0 - cer

        # WAR: كلمة مقابل كلمة
        wer = self._compute_wer(ocr_text, reference_text)
        war = 1.0 - wer

        # أسئلة
        ocr_qs = set(re.findall(r'س\d+', ocr_text) + re.findall(r'\b\d+\s*[.\-)]\s*(?:ما|اذكر|عدد|علل|فسر)', ocr_text))
        ref_qs = set(re.findall(r'س\d+', reference_text) + re.findall(r'\b\d+\s*[.\-)]\s*(?:ما|اذكر|عدد|علل|فسر)', reference_text))
        q_preserved = len(ocr_qs & ref_qs)
        q_total = max(len(ref_qs), 1)

        # خيارات MCQ
        ocr_choices = set(re.findall(r'\([أبجدهوز]\)', ocr_text))
        ref_choices = set(re.findall(r'\([أبجدهوز]\)', reference_text))
        c_preserved = len(ocr_choices & ref_choices)
        c_total = max(len(ref_choices), 1)

        page_result = {
            "page": page_num,
            "cer": round(cer, 4),
            "car": round(car, 4),
            "wer": round(wer, 4),
            "war": round(war, 4),
            "questions": f"{q_preserved}/{q_total}",
            "choices": f"{c_preserved}/{c_total}",
            "chars_ocr": len(ocr_text),
            "chars_ref": len(reference_text),
        }

        self.page_results.append(page_result)

        # تحديث الإجماليات
        ref_chars = len(reference_text)
        ref_words = len(reference_text.split())

        self.total_chars += ref_chars
        self.error_chars += int(cer * ref_chars)
        self.total_words += ref_words
        self.error_words += int(wer * ref_words)
        self.total_questions += q_total
        self.preserved_questions += q_preserved
        self.total_choices += c_total
        self.preserved_choices += c_preserved

        return page_result

    def measure_full_document(
        self, ocr_text: str, reference_text: str
    ) -> dict:
        """
        قياس الجودة لمستند كامل.

        يقسم النص إلى صفحات (حسب page markers) ويقيس كل صفحة على حدة.
        """
        self.reset()

        # تقسيم النصوص إلى صفحات
        ocr_pages = re.split(r'صفحة\s*\d+', ocr_text)
        ref_pages = re.split(r'صفحة\s*\d+', reference_text)

        num_pages = min(len(ocr_pages), len(ref_pages))

        for i in range(num_pages):
            self.measure_page(ocr_pages[i], ref_pages[i], i + 1)

        return self.get_summary()

    def get_summary(self) -> dict:
        """تقرير الجودة الكلي."""
        return {
            "total_chars": self.total_chars,
            "total_words": self.total_words,
            "car": round(1.0 - (self.error_chars / max(1, self.total_chars)), 4),
            "war": round(1.0 - (self.error_words / max(1, self.total_words)), 4),
            "cer": round(self.error_chars / max(1, self.total_chars), 4),
            "wer": round(self.error_words / max(1, self.total_words), 4),
            "question_preservation": f"{self.preserved_questions}/{self.total_questions}",
            "choice_preservation": f"{self.preserved_choices}/{self.total_choices}",
            "question_preservation_pct": round(
                self.preserved_questions / max(1, self.total_questions) * 100, 1
            ),
            "choice_preservation_pct": round(
                self.preserved_choices / max(1, self.total_choices) * 100, 1
            ),
            "overall_score": round(
                (1.0 - (self.error_chars / max(1, self.total_chars))) * 100, 1
            ),
            "pages_analyzed": len(self.page_results),
            "page_results": self.page_results,
        }

    def format_report(self, summary: dict = None) -> str:
        """تنسيق تقرير الجودة كـ Markdown."""
        if summary is None:
            summary = self.get_summary()

        lines = []
        lines.append("## 📊 تقرير جودة OCR")
        lines.append("")
        lines.append("| المقياس | القيمة |")
        lines.append("|---------|--------|")
        lines.append(f"| CAR (Character Accuracy Rate) | {summary['car']*100:.2f}% |")
        lines.append(f"| WAR (Word Accuracy Rate) | {summary['war']*100:.2f}% |")
        lines.append(f"| CER (Character Error Rate) | {summary['cer']*100:.2f}% |")
        lines.append(f"| WER (Word Error Rate) | {summary['wer']*100:.2f}% |")
        lines.append(f"| الحروف الكلية | {summary['total_chars']:,} |")
        lines.append(f"| الكلمات الكلية | {summary['total_words']:,} |")
        lines.append(f"| حفظ الأسئلة | {summary['question_preservation']} ({summary['question_preservation_pct']}%) |")
        lines.append(f"| حفظ الخيارات | {summary['choice_preservation']} ({summary['choice_preservation_pct']}%) |")
        lines.append(f"| الجودة الكلية | {summary['overall_score']}/100 |")
        lines.append("")
        lines.append("### نتائج الصفحات")
        lines.append("")
        lines.append("| صفحة | CAR | WAR | أسئلة | خيارات |")
        lines.append("|------|-----|-----|-------|--------|")
        for pr in summary.get("page_results", []):
            lines.append(
                f"| {pr['page']} | {pr['car']*100:.1f}% | {pr['war']*100:.1f}% | "
                f"{pr['questions']} | {pr['choices']} |"
            )

        return "\n".join(lines)

    @staticmethod
    def _compute_cer(ocr: str, ref: str) -> float:
        """Character Error Rate باستخدام مسافة ليفنشتاين."""
        if not ref:
            return 1.0 if ocr else 0.0
        if not ocr:
            return 1.0

        # مسافة ليفنشتاين بسيطة
        rows, cols = len(ocr) + 1, len(ref) + 1
        dp = [[0] * cols for _ in range(rows)]
        for i in range(rows):
            dp[i][0] = i
        for j in range(cols):
            dp[0][j] = j

        for i in range(1, rows):
            for j in range(1, cols):
                cost = 0 if ocr[i - 1] == ref[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,      # حذف
                    dp[i][j - 1] + 1,       # إضافة
                    dp[i - 1][j - 1] + cost # استبدال
                )

        return dp[rows - 1][cols - 1] / max(1, len(ref))

    @staticmethod
    def _compute_wer(ocr: str, ref: str) -> float:
        """Word Error Rate."""
        ocr_words = ocr.split()
        ref_words = ref.split()

        if not ref_words:
            return 1.0 if ocr_words else 0.0
        if not ocr_words:
            return 1.0

        rows, cols = len(ocr_words) + 1, len(ref_words) + 1
        dp = [[0] * cols for _ in range(rows)]
        for i in range(rows):
            dp[i][0] = i
        for j in range(cols):
            dp[0][j] = j

        for i in range(1, rows):
            for j in range(1, cols):
                cost = 0 if ocr_words[i - 1] == ref_words[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,
                    dp[i][j - 1] + 1,
                    dp[i - 1][j - 1] + cost
                )

        return dp[rows - 1][cols - 1] / max(1, len(ref_words))


# ═══════════════════════════════════════════════════════════════╗
#  دوال مساعدة للتحليل السريع                                 ║
# ═══════════════════════════════════════════════════════════════╝

def analyze_ocr_errors(text: str) -> List[dict]:
    """
    تحليل النص المستخرج واكتشاف أخطاء OCR المحتملة.

    Returns:
        List[dict]: قائمة بالأخطاء المكتشفة مع النوع والموقع
    """
    errors = []
    words = text.split()

    for i, word in enumerate(words):
        cleaned = re.sub(r"[^\u0600-\u06FFa-zA-Z]", "", word)
        if not cleaned or len(cleaned) < 2:
            continue

        issues = []

        # 1. حروف عربية مفككة (مفصولة بمسافة)
        if re.search(r'[\u0600-\u06FF]\s+[\u0600-\u06FF]', word):
            issues.append("broken_arabic")

        # 2. مختلط عربي-لاتيني
        has_arabic = bool(re.search(r'[\u0600-\u06FF]', cleaned))
        has_latin = bool(re.search(r'[A-Za-z]', cleaned))
        if has_arabic and has_latin:
            issues.append("mixed_script")

        # 3. حروف متكررة بشكل مفرط
        char_counts = Counter(cleaned)
        for ch, count in char_counts.items():
            if count > len(cleaned) * 0.5:
                issues.append(f"repeated_char:{ch}")
                break

        # 4. كلمات غير موجودة في القاموس (استخدام المستوى العام)
        if _LEXICON_AVAILABLE:
            clean_no_diac = re.sub(r"[\u064B-\u0652]", "", cleaned)
            if clean_no_diac not in FULL_LEXICON and clean_no_diac.isalpha():
                # قد تكون خطأ OCR
                if len(clean_no_diac) >= 3 and not clean_no_diac.startswith(("ال", "بال", "فال")):
                    issues.append("unknown_word")

        if issues:
            errors.append({
                "position": i,
                "word": word,
                "issues": issues,
                "confidence": ConfidenceCorrector().estimate_word_confidence(cleaned),
                "suggestion": ConfidenceCorrector().correct_with_confidence(word, words[max(0, i-3):i+4]),
            })

    return errors


def verify_quality_improvement(
    text_before: str, text_after: str
) -> dict:
    """
    مقارنة النص قبل وبعد التصحيح لقياس التحسن.

    Returns:
        dict: مقاييس التحسن
    """
    corrector = ConfidenceCorrector()

    # قياس الثقة قبل
    words_before = text_before.split()
    conf_before = [
        corrector.estimate_word_confidence(w) for w in words_before
    ]
    avg_conf_before = sum(conf_before) / max(1, len(conf_before))

    # قياس الثقة بعد
    words_after = text_after.split()
    conf_after = [
        corrector.estimate_word_confidence(w) for w in words_after
    ]
    avg_conf_after = sum(conf_after) / max(1, len(conf_after))

    # كلمات منخفضة الثقة
    low_before = sum(1 for c in conf_before if c < 0.5)
    low_after = sum(1 for c in conf_after if c < 0.5)

    # تغير عدد الكلمات (دمج/فصل)
    word_diff = len(words_after) - len(words_before)

    return {
        "avg_confidence_before": round(avg_conf_before, 3),
        "avg_confidence_after": round(avg_conf_after, 3),
        "confidence_improvement": round(avg_conf_after - avg_conf_before, 3),
        "low_confidence_words_before": low_before,
        "low_confidence_words_after": low_after,
        "word_count_change": word_diff,
        "words_analyzed": len(words_before),
    }


# ═══════════════════════════════════════════════════════════════╗
#  CLI للاختبار                                                ║
# ═══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    print("=" * 55)
    print("📊 Evro OCR — Quality & Correction Engine")
    print("=" * 55)
    print()

    # اختبار مصفوفة التشابه
    print("🔤 اختبار مصفوفة تشابه الحروف:")
    test_pairs = [("ب", "ت"), ("ح", "ج"), ("ا", "أ"), ("ه", "ة"), ("س", "ش")]
    for a, b in test_pairs:
        score = ArabicLetterConfusion.get_confusion_score(a, b)
        print(f"  {a} ↔ {b}: {score:.2f}")

    print()

    # اختبار التصحيح المبني على الثقة
    print("🎯 اختبار Confidence Corrector:")
    corrector = ConfidenceCorrector()
    test_words = ["القوه", "الطاقه", "الماده", "الكتله", "Example", "سرعة"]
    for word in test_words:
        conf = corrector.estimate_word_confidence(word)
        corrected, new_conf, method = corrector.correct_with_confidence(word)
        status = "✅" if new_conf > 0.7 else "⚠️"
        print(f"  {status} {word} → {corrected}  (ثقة: {conf:.2f} → {new_conf:.2f}, طريقة: {method})")

    print()

    # إحصائيات الـ lexicon
    try:
        from lexicon_engine import get_lexicon_stats
        stats = get_lexicon_stats()
        print(f"📚 إحصائيات القاموس الأكاديمي: {stats['total']} مدخل إجمالي")
        for k, v in stats.items():
            if k != "total":
                print(f"  {k}: {v}")
    except Exception as e:
        print(f"  (تعذر تحميل إحصائيات القاموس: {e})")

    print()
    print("=" * 55)
    print("✅ Evro OCR Quality Engine ready")
    print("=" * 55)
