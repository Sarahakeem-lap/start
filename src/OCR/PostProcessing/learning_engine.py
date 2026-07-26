"""
محرك التعلم المستمر — Evro OCR Continuous Learning Engine
============================================================
قاعدة بيانات OCR ذاكرة — ذاكرة العبارات — النموذج السياقي — التغذية البشرية
تحويل OCR من نظام ثابت إلى نظام يتعلم من كل كتاب يُعالج.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict


# ═══════════════════════════════════════════════════════════════╗
#  الإعدادات — مسارات قواعد البيانات                            ║
# ═══════════════════════════════════════════════════════════════╝

LEARNING_DIR = Path(__file__).resolve().parent / "learning_data"
LEARNING_DIR.mkdir(exist_ok=True)

SUBJECTS = [
    "general", "arabic", "english", "mathematics",
    "physics", "chemistry", "biology",
    "history", "geography", "statistics",
]

# ═══════════════════════════════════════════════════════════════╗
#  السجل الواحد — يمثل تصحيحاً أو معلومة تعلمها النظام        ║
# ═══════════════════════════════════════════════════════════════╝

@dataclass
class CorrectionEntry:
    """سجل تصحيح واحد — ما الذي تم تصحيحه وكيف."""
    original: str           # النص الأصلي (الخاطئ)
    corrected: str          # النص المصحح
    confidence: float = 0.0 # ثقة الـ OCR في النص الأصلي
    frequency: int = 1      # كم مرة تم هذا التصحيح
    subject: str = "general" # المادة الدراسية
    source: str = "auto"    # auto | human | validation
    book_title: str = ""    # اسم الكتاب
    pages: List[int] = field(default_factory=list)  # الصفحات التي ظهر فيها
    first_seen: float = 0.0 # أول مرة
    last_seen: float = 0.0  # آخر مرة

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "CorrectionEntry":
        return CorrectionEntry(**d)


@dataclass
class PhraseEntry:
    """سجل عبارة تعلمها النظام — مجموعة كلمات متكررة."""
    phrase: str             # العبارة كاملة
    words: List[str]        # الكلمات المكونة
    frequency: int = 1      # كم مرة ظهرت
    subject: str = "general"
    confidence: float = 1.0 # الثقة في هذه العبارة
    sources: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "PhraseEntry":
        return PhraseEntry(**d)


# ═══════════════════════════════════════════════════════════════╗
#  قاعدة بيانات التعلم — LearningMemory                       ║
# ═══════════════════════════════════════════════════════════════╝

class LearningMemory:
    """
    قاعدة بيانات OCR الذاكرة المستمرة.
    
    تخزين:
    - كل تصحيح تم (original → corrected)
    - عدد مرات التكرار
    - المادة الدراسية
    - مصدر التصحيح (تلقائي/بشري)
    
    المبدأ: لا يوجد تصحيح يُنسى. كلما تكرر التصحيح، زادت ثقته.
    """

    def __init__(self, subject: str = "general"):
        if subject not in SUBJECTS:
            subject = "general"
        self.subject = subject
        self.db_path = LEARNING_DIR / f"corrections_{subject}.json"
        self.phrases_path = LEARNING_DIR / f"phrases_{subject}.json"
        self.context_path = LEARNING_DIR / f"context_{subject}.json"

        # تحميل البيانات
        self.corrections: Dict[str, CorrectionEntry] = {}  # original → entry
        self.phrases: Dict[str, PhraseEntry] = {}           # phrase → entry
        self.word_context: Dict[str, Counter] = defaultdict(Counter)  # word → {neighbor: count}
        self.total_processed: int = 0
        self.books_processed: Set[str] = set()

        self._load()

    def _load(self):
        """تحميل قاعدة البيانات من القرص."""
        try:
            if self.db_path.exists():
                data = json.loads(self.db_path.read_text(encoding="utf-8"))
                self.corrections = {
                    k: CorrectionEntry.from_dict(v) for k, v in data.get("corrections", {}).items()
                }
                self.total_processed = data.get("total_processed", 0)
                self.books_processed = set(data.get("books_processed", []))
        except Exception:
            self.corrections = {}

        try:
            if self.phrases_path.exists():
                data = json.loads(self.phrases_path.read_text(encoding="utf-8"))
                self.phrases = {
                    k: PhraseEntry.from_dict(v) for k, v in data.get("phrases", {}).items()
                }
        except Exception:
            self.phrases = {}

        try:
            if self.context_path.exists():
                data = json.loads(self.context_path.read_text(encoding="utf-8"))
                self.word_context = defaultdict(Counter, {
                    k: Counter(v) for k, v in data.items()
                })
        except Exception:
            self.word_context = defaultdict(Counter)

    def _save(self):
        """حفظ قاعدة البيانات على القرص."""
        try:
            data = {
                "corrections": {k: v.to_dict() for k, v in self.corrections.items()},
                "total_processed": self.total_processed,
                "books_processed": list(self.books_processed),
                "updated_at": time.time(),
            }
            self.db_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[LearningMemory] Save error: {e}")

        try:
            phrases_data = {
                "phrases": {k: v.to_dict() for k, v in self.phrases.items()},
                "updated_at": time.time(),
            }
            self.phrases_path.write_text(
                json.dumps(phrases_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

        try:
            context_data = {
                k: dict(v) for k, v in self.word_context.items()
            }
            self.context_path.write_text(
                json.dumps(context_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ─── تسجيل التصحيحات ───

    def record_correction(
        self, original: str, corrected: str,
        confidence: float = 0.0, source: str = "auto",
        book_title: str = "", page: int = 0,
    ):
        """تسجيل تصحيح جديد أو تحديث تصحيح موجود."""
        if original == corrected or not original or not corrected:
            return
        if len(original) < 2 or len(corrected) < 2:
            return

        now = time.time()

        if original in self.corrections:
            entry = self.corrections[original]
            entry.frequency += 1
            entry.last_seen = now
            if page and page not in entry.pages:
                entry.pages.append(page)
            # البشر لهم الأولوية
            if source == "human":
                entry.source = "human"
                entry.corrected = corrected
        else:
            self.corrections[original] = CorrectionEntry(
                original=original,
                corrected=corrected,
                confidence=confidence,
                frequency=1,
                subject=self.subject,
                source=source,
                book_title=book_title,
                pages=[page] if page else [],
                first_seen=now,
                last_seen=now,
            )

    def get_correction(self, original: str) -> Optional[str]:
        """الحصول على التصحيح المخزن لكلمة."""
        if original in self.corrections:
            entry = self.corrections[original]
            # فقط إذا كان التصحيح موثوقاً (تكرر كفاية أو مصدره بشري)
            if entry.frequency >= 2 or entry.source == "human":
                return entry.corrected
        return None

    def is_known_error(self, word: str) -> bool:
        """هل هذه الكلمة خطأ OCR معروف؟"""
        if word in self.corrections:
            entry = self.corrections[word]
            return entry.frequency >= 2 or entry.source == "human"
        return False

    # ─── تسجيل العبارات ───

    def learn_phrase(self, phrase: str, source: str = "auto"):
        """تسجيل عبارة جديدة أو تحديث تكرار عبارة موجودة."""
        if not phrase or len(phrase) < 4:
            return
        words = phrase.split()
        if len(words) < 2:
            return

        key = phrase.strip()
        if key in self.phrases:
            self.phrases[key].frequency += 1
            if source not in self.phrases[key].sources:
                self.phrases[key].sources.append(source)
        else:
            self.phrases[key] = PhraseEntry(
                phrase=key,
                words=words,
                frequency=1,
                subject=self.subject,
                sources=[source],
            )

    def extract_phrases_from_text(self, text: str, min_freq: int = 1):
        """استخراج العبارات المتكررة من النص وتعلمها."""
        # 2-grams, 3-grams, 4-grams
        words = text.split()
        if len(words) < 2:
            return

        for n in [2, 3, 4]:
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i:i + n])
                # تجاهل العبارات التي تبدأ/تنتهي بكلمات شائعة غير مفيدة
                if self._is_phrase_useful(phrase):
                    self.learn_phrase(phrase, source="auto_extract")

    def _is_phrase_useful(self, phrase: str) -> bool:
        """هل العبارة مفيدة للتعلم أم مجرد كلمات عشوائية؟"""
        stop_start = {"في", "من", "إلى", "عن", "على", "مع", "كان", "هذا", "هذه", "ذلك", "تلك"}
        words = phrase.split()
        if not words:
            return False
        if words[0] in stop_start and len(words) <= 2:
            return False
        # يجب أن تحتوي على الأقل كلمة أكاديمية واحدة
        academic_chars = sum(1 for w in words for c in w if '\u0600' <= c <= '\u06FF')
        if academic_chars < 4:
            return False
        return len(phrase) >= 6

    def match_phrase(self, text: str) -> List[Tuple[str, int]]:
        """البحث عن العبارات المعروفة في النص."""
        matches = []
        for phrase, entry in sorted(self.phrases.items(), key=lambda x: -len(x[0])):
            if phrase in text and entry.frequency >= 2:
                matches.append((phrase, entry.frequency))
        return matches

    # ─── السياق (Context Learning) ───

    def learn_context(self, words: List[str]):
        """تعلم الكلمات التي تظهر معاً في نفس السياق."""
        for i, word in enumerate(words):
            if len(word) < 2:
                continue
            # 3 كلمات قبل وبعد
            start = max(0, i - 3)
            end = min(len(words), i + 4)
            for j in range(start, end):
                if i != j and len(words[j]) >= 2:
                    self.word_context[word][words[j]] += 1

    def get_context_suggestions(self, word: str, top_k: int = 5) -> List[Tuple[str, int]]:
        """الحصول على الكلمات الأكثر شيوعاً بجانب كلمة معينة."""
        if word in self.word_context:
            return self.word_context[word].most_common(top_k)
        return []

    # ─── التغذية البشرية (Human Feedback) ───

    def human_correction(self, original: str, corrected: str, book_title: str = "", page: int = 0):
        """تسجيل تصحيح بشري — له الأولوية القصوى."""
        self.record_correction(original, corrected, confidence=1.0, source="human",
                                book_title=book_title, page=page)

    def detect_human_edits(self, original_text: str, human_edited_text: str, book_title: str = ""):
        """كشف كل التغييرات التي أجراها الإنسان على النص."""
        orig_words = original_text.split()
        edit_words = human_edited_text.split()

        if len(orig_words) != len(edit_words):
            # نصوص ذات أطوال مختلفة — نقارن كلمة بكلمة
            for i in range(min(len(orig_words), len(edit_words))):
                if orig_words[i] != edit_words[i]:
                    self.human_correction(orig_words[i], edit_words[i], book_title)
            return

        for orig, edit in zip(orig_words, edit_words):
            if orig != edit:
                self.human_correction(orig, edit, book_title)

    # ─── تعزيز التصحيحات (Confidence Learning) ───

    def promote_corrections(self, min_frequency: int = 3):
        """ترقية التصحيحات المتكررة إلى قواعد دائمة."""
        promoted = []
        for original, entry in self.corrections.items():
            if entry.frequency >= min_frequency and entry.source != "human":
                entry.source = "auto_promoted"
                promoted.append(original)
        if promoted:
            self._save()
        return promoted

    # ─── إحصائيات التعلم ───

    def get_stats(self) -> dict:
        """إحصائيات قاعدة بيانات التعلم."""
        return {
            "subject": self.subject,
            "total_corrections": len(self.corrections),
            "total_phrases": len(self.phrases),
            "total_context_entries": sum(len(v) for v in self.word_context.values()),
            "total_processed": self.total_processed,
            "books_processed": len(self.books_processed),
            "auto_corrections": sum(1 for e in self.corrections.values() if e.source == "auto"),
            "human_corrections": sum(1 for e in self.corrections.values() if e.source == "human"),
            "promoted_corrections": sum(1 for e in self.corrections.values() if e.source == "auto_promoted"),
            "high_frequency": sum(1 for e in self.corrections.values() if e.frequency >= 5),
            "top_corrections": sorted(
                [(k, v.frequency) for k, v in self.corrections.items()],
                key=lambda x: -x[1]
            )[:20],
        }

    def save(self):
        """حفظ فوري."""
        self._save()

    def process_book(self, text: str, book_title: str = ""):
        """معالجة كتاب كامل — تعلم العبارات والسياق منه."""
        self.total_processed += 1
        if book_title:
            self.books_processed.add(book_title)

        # تعلم العبارات
        self.extract_phrases_from_text(text)

        # تعلم السياق
        words = [w.strip() for w in text.split() if len(w.strip()) >= 2]
        self.learn_context(words)

        # حفظ بعد كل كتاب
        self._save()


# ═══════════════════════════════════════════════════════════════╗
#  مدير قواعد البيانات — SubjectMemoryManager                 ║
# ═══════════════════════════════════════════════════════════════╝

class SubjectMemoryManager:
    """
    مدير قواعد التعلم — يحتفظ بقاعدة منفصلة لكل مادة.
    never mixing correction statistics between unrelated subjects.
    """

    def __init__(self):
        self.databases: Dict[str, LearningMemory] = {}
        self._current_subject = "general"

    def get_db(self, subject: str = "general") -> LearningMemory:
        """الحصول على قاعدة بيانات لمادة معينة (مع التخزين المؤقت)."""
        if subject not in SUBJECTS:
            subject = "general"
        if subject not in self.databases:
            self.databases[subject] = LearningMemory(subject)
        return self.databases[subject]

    def detect_subject(self, text: str) -> str:
        """كشف المادة الدراسية من النص (بسيط — بالغردات المفتاحية)."""
        keywords = {
            "physics": ["قوة", "طاقة", "سرعة", "تسارع", "كتلة", "ضغط", "شغل", "تيار", "جهد", "مقاومة"],
            "chemistry": ["تفاعل", "عنصر", "مركب", "حمض", "قاعدة", "أكسدة", "رابطة", "ذرة", "جزيء", "محلول"],
            "biology": ["خلية", "نواة", "غشاء", "جين", "إنزيم", "هرمون", "جهاز", "عضلة", "عصب", "دم"],
            "mathematics": ["معادلة", "دالة", "مشتقة", "تكامل", "مصفوفة", "متجه", "احتمال", "هندسة", "مثلث", "لوغاريتم"],
            "history": ["تاريخ", "حضارة", "دولة", "إمبراطورية", "حرب", "ثورة", "عصر", "قديم", "حديث", "معاصر"],
            "geography": ["خريطة", "مناخ", "تضاريس", "سكان", "نهر", "جبل", "بحر", "محافظة", "عاصمة", "حدود"],
            "arabic": ["نحو", "صرف", "بلاغة", "أدب", "شعر", "نثر", "قصة", "فعل", "اسم", "حرف"],
            "english": ["grammar", "vocabulary", "reading", "writing", "noun", "verb", "tense", "paragraph"],
            "statistics": ["احتمال", "متوسط", "تباين", "انحراف", "توزيع", "بيانات", "عينة", "مخطط"],
        }

        text_lower = text.lower()
        scores = {}
        for subject, words in keywords.items():
            score = sum(1 for w in words if w in text_lower)
            if score > 0:
                scores[subject] = score

        if not scores:
            return "general"
        return max(scores, key=scores.get)

    def record_correction(
        self, original: str, corrected: str,
        confidence: float = 0.0, source: str = "auto",
        book_title: str = "", page: int = 0, subject: str = None,
    ):
        """تسجيل تصحيح في قاعدة البيانات المناسبة."""
        if subject is None:
            subject = self._current_subject
        db = self.get_db(subject)
        db.record_correction(original, corrected, confidence, source, book_title, page)

    def get_correction(self, original: str, subject: str = None) -> Optional[str]:
        """البحث عن تصحيح في قاعدة البيانات المناسبة."""
        if subject is None:
            subject = self._current_subject
        db = self.get_db(subject)
        return db.get_correction(original)

    def learn_from_book(self, text: str, book_title: str = "", subject: str = None):
        """تعلم من كتاب كامل."""
        if subject is None:
            subject = self.detect_subject(text)
        self._current_subject = subject
        db = self.get_db(subject)
        db.process_book(text, book_title)

    def detect_human_edits(self, original: str, edited: str, book_title: str = "", subject: str = None):
        """كشف التعديلات البشرية وتعلمها."""
        if subject is None:
            subject = self._current_subject
        db = self.get_db(subject)
        db.detect_human_edits(original, edited, book_title)

    def get_global_stats(self) -> dict:
        """إحصائيات جميع قواعد البيانات."""
        stats = {}
        for subject in SUBJECTS:
            db = self.get_db(subject)
            stats[subject] = db.get_stats()
        return stats

    def promote_all(self, min_frequency: int = 3) -> int:
        """ترقية كل التصحيحات المتكررة عبر كل المواد."""
        total = 0
        for subject in SUBJECTS:
            db = self.get_db(subject)
            total += len(db.promote_corrections(min_frequency))
        return total

    def save_all(self):
        """حفظ جميع قواعد البيانات."""
        for db in self.databases.values():
            db.save()

    def correct_text(self, text: str, subject: str = None) -> str:
        """
        تصحيح نص باستخدام قاعدة التعلم — يبحث عن العبارات أولاً ثم الكلمات المفردة.
        هذا هو الربط الأساسي مع QC Pipeline.
        """
        if not text:
            return text

        if subject is None:
            subject = self.detect_subject(text)
        self._current_subject = subject
        db = self.get_db(subject)

        # 1. حماية العبارات المعروفة — نحميها من التغيير الخطأ
        protected_regions = []
        for phrase, entry in sorted(db.phrases.items(), key=lambda x: -len(x[0])):
            if entry.frequency >= 2:  # فقط العبارات الموثوقة
                # نحمي العبارة بوضع علامات مؤقتة
                placeholder = f"__{phrase.replace(' ', '_')}__"
                text = text.replace(phrase, placeholder)
                protected_regions.append((placeholder, phrase))

        # 2. تصحيح الكلمات المفردة
        words = text.split()
        corrected_words = []
        for word in words:
            # هل هذه الكلمة في منطقة محمية؟
            is_protected = any(word.startswith('__') and word.endswith('__') for _ in [1])
            if is_protected:
                # نسترجع العبارة الأصلية كما هي
                for placeholder, original_phrase in protected_regions:
                    if word == placeholder:
                        corrected_words.append(original_phrase)
                        break
            else:
                # هل هذه الكلمة خطأ معروف؟
                correction = db.get_correction(word)
                if correction:
                    corrected_words.append(correction)
                else:
                    corrected_words.append(word)

        result = " ".join(corrected_words)

        # استعادة أي placeholders متبقية
        for placeholder, original_phrase in protected_regions:
            result = result.replace(placeholder, original_phrase)

        return result


# ═══════════════════════════════════════════════════════════════╗
#  تقرير التحسن المستمر — ContinuousImprovementReport          ║
# ═══════════════════════════════════════════════════════════════╝

class ContinuousImprovementReport:
    """
    تقرير التعلم المستمر — يصدر بعد كل كتاب ويظهر كيف تحسن النظام.
    """

    def __init__(self, manager: SubjectMemoryManager):
        self.manager = manager

    def generate(self, book_title: str = "", subject: str = "") -> str:
        """توليد تقرير التعلم المستمر."""
        stats = self.manager.get_global_stats() if not subject else {
            subject: self.manager.get_db(subject).get_stats()
        }

        report = []
        report.append(f"## 📈 تقرير التعلم المستمر — {book_title or 'النظام الكلي'}")
        report.append("")
        report.append("| المادة | التصحيحات | العبارات | التلقائية | البشرية | المرفوعة |")
        report.append("|--------|-----------|----------|-----------|---------|----------|")

        total_corrections = 0
        total_phrases = 0
        total_human = 0
        total_promoted = 0

        for subject_name, s in stats.items():
            if s["total_corrections"] == 0 and s["total_phrases"] == 0:
                continue
            report.append(
                f"| {subject_name} | {s['total_corrections']} | {s['total_phrases']} | "
                f"{s['auto_corrections']} | {s['human_corrections']} | {s['promoted_corrections']} |"
            )
            total_corrections += s["total_corrections"]
            total_phrases += s["total_phrases"]
            total_human += s["human_corrections"]
            total_promoted += s["promoted_corrections"]

        report.append("")
        report.append(f"**الإجمالي:** {total_corrections} تصحيح، {total_phrases} عبارة، {total_human} تصحيح بشري، {total_promoted} قاعدة مرفوعة")
        report.append("")

        # أهم التصحيحات
        report.append("### 🔝 أهم التصحيحات المتكررة")
        report.append("")
        report.append("| الكلمة الأصلية | التصحيح | التكرار | المادة | المصدر |")
        report.append("|----------------|---------|---------|--------|--------|")

        all_corrections = []
        for subject_name, s in stats.items():
            for word, freq in s.get("top_corrections", []):
                entry = self.manager.get_db(subject_name).corrections.get(word)
                if entry:
                    all_corrections.append((entry, freq))

        all_corrections.sort(key=lambda x: -x[1])
        for entry, freq in all_corrections[:20]:
            report.append(
                f"| {entry.original} → {entry.corrected} | {freq} | "
                f"{entry.subject} | {entry.source} |"
            )

        progress = self._calculate_progress(stats)
        report.append("")
        report.append(f"### 📊 مؤشرات التقدم")
        report.append(f"- إجمالي الكتب المعالجة: {progress['books']}")
        report.append(f"- إجمالي التصحيحات: {progress['corrections']}")
        report.append(f"- متوسط التصحيحات لكل كتاب: {progress['per_book']:.1f}")
        report.append(f"- تصحيحات بشرية: {progress['human_pct']:.1f}%")
        report.append(f"- قواعد مرفوعة (تلقائية): {progress['promoted']}")
        report.append(f"- العبارات المتعلمة: {progress['phrases']}")
        report.append("")
        report.append("---")
        report.append(f"_التقرير مولّد تلقائياً — Evro OCR Learning Engine_")

        return "\n".join(report)

    def _calculate_progress(self, stats: dict) -> dict:
        total_corrections = sum(s["total_corrections"] for s in stats.values())
        total_phrases = sum(s["total_phrases"] for s in stats.values())
        total_human = sum(s["human_corrections"] for s in stats.values())
        total_promoted = sum(s["promoted_corrections"] for s in stats.values())
        total_books = max(sum(s["books_processed"] for s in stats.values()), 1)

        return {
            "books": total_books,
            "corrections": total_corrections,
            "phrases": total_phrases,
            "human_pct": round(total_human / max(1, total_corrections) * 100, 1),
            "promoted": total_promoted,
            "per_book": round(total_corrections / total_books, 1),
        }


# ═══════════════════════════════════════════════════════════════╗
#  نقطة الدخول الوحيدة — LearningEngine                        ║
# ═══════════════════════════════════════════════════════════════╝

class LearningEngine:
    """
    محرك التعلم المستمر — نقطة الدخول الوحيدة لبقية الـ Pipeline.
    
    الاستخدام:
        engine = LearningEngine()
        engine.learn_from_book(text, "كتاب الفيزياء", "physics")
        corrected = engine.correct_text(ocr_text)  # تصحيح باستخدام الذاكرة
        report = engine.generate_report("كتاب الفيزياء")
    """

    def __init__(self):
        self.manager = SubjectMemoryManager()
        self.reporter = ContinuousImprovementReport(self.manager)

    def learn_from_book(self, text: str, book_title: str = "", subject: str = None):
        """تعلم من كتاب كامل."""
        self.manager.learn_from_book(text, book_title, subject)
        self.manager.save_all()

    def correct_text(self, text: str, subject: str = None) -> str:
        """تصحيح نص باستخدام قاعدة التعلم."""
        return self.manager.correct_text(text, subject)

    def record_human_feedback(self, original: str, edited: str, book_title: str = "", subject: str = None):
        """تسجيل تعديل بشري."""
        self.manager.detect_human_edits(original, edited, book_title, subject)
        self.manager.save_all()

    def generate_report(self, book_title: str = "") -> str:
        """توليد تقرير التعلم المستمر."""
        return self.reporter.generate(book_title)

    def get_stats(self) -> dict:
        """إحصائيات التعلم الكلية."""
        return self.manager.get_global_stats()

    def promote_corrections(self, min_frequency: int = 3) -> int:
        """ترقية التصحيحات المتكررة إلى قواعد."""
        return self.manager.promote_all(min_frequency)

    def save(self):
        """حفظ جميع قواعد البيانات على القرص."""
        self.manager.save_all()


# ═══════════════════════════════════════════════════════════════╗
#  CLI للاختبار                                                ║
# ═══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    print("=" * 55)
    print("🧠 Evro OCR — Continuous Learning Engine")
    print("=" * 55)
    print()

    # إنشاء المحرك
    engine = LearningEngine()

    # محاكاة تعلم من كتاب فيزياء
    print("📚 محاكاة تعلم من كتاب فيزياء...")
    physics_text = """
    القوة هي مؤثر خارجي يغير من حالة الجسم
    قانون نيوتن الثاني: القوة = الكتلة × التسارع
    الطاقة الحركية = ½ × الكتلة × مربع السرعة
    الشغل المبذول = القوة × المسافة
    القدرة = الشغل ÷ الزمن
    """
    engine.learn_from_book(physics_text, "كتاب الفيزياء للصف الثالث", "physics")

    # محاكاة تعلم من كتاب كيمياء
    print("📚 محاكاة تعلم من كتاب كيمياء...")
    chemistry_text = """
    التفاعلات الكيميائية تشمل تكسير الروابط وتكوين روابط جديدة
    حمض الهيدروكلوريك HCl وقاعدة هيدروكسيد الصوديوم NaOH
    سرعة التفاعل تعتمد على طبيعة المواد المتفاعلة وتركيزها
    """
    engine.learn_from_book(chemistry_text, "كتاب الكيمياء للصف الثالث", "chemistry")

    # محاكاة تصحيح بشري
    print("👤 محاكاة تصحيح بشري...")
    engine.record_human_feedback(
        "القوه", "القوة",
        "كتاب الفيزياء", "physics"
    )
    engine.record_human_feedback(
        "الطاقه", "الطاقة",
        "كتاب الفيزياء", "physics"
    )

    # تصحيح نص باستخدام الذاكرة
    print("🎯 اختبار تصحيح النص بالذاكرة...")
    test_text = "القوه والطاقه في التفاعلات الكيميائيه"
    corrected = engine.correct_text(test_text, "physics")
    print(f"  قبل: {test_text}")
    print(f"  بعد: {corrected}")

    # ترقية التصحيحات
    print()
    print("⬆️ ترقية التصحيحات المتكررة...")
    promoted = engine.promote_corrections(min_frequency=1)
    print(f"  تمت ترقية {promoted} قاعدة")

    # التقرير
    print()
    print("📊 تقرير التعلم المستمر:")
    report = engine.generate_report("محاكاة التعلم")
    print(report)

    print()
    print("=" * 55)
    print("✅ Learning Engine ready")
    print("=" * 55)
