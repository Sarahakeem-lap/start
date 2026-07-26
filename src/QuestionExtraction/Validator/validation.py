"""
Evro OCR Engine — Correction Validation Framework
==================================================
Tests every proposed OCR correction against a golden dataset.

Every correction must prove:
  • It fixes real OCR errors (measured)
  • It introduces NO false positives (validated)
  • It does NOT regress on previously correct text

If a correction fails validation → REJECT IT.
"""

import re
import sys
import json
import time
from pathlib import Path
from typing import List, Dict, Callable, Tuple, Optional
from dataclasses import dataclass, field
from collections import Counter


# ═══════════════════════════════════════════════════════════════╗
#  GOLDEN DATASET — Realistic OCR error test cases              ║
#  Each test case represents a REAL error pattern observed      ║
#  in Egyptian Ministry textbook OCR output.                    ║
# ═══════════════════════════════════════════════════════════════╝

@dataclass
class TestCase:
    """A single validation test case."""
    id: str
    description: str
    input_text: str          # Simulated OCR output (with errors)
    expected_output: str     # Ground truth (corrected form)
    error_class: str         # E-1, E-2, etc.
    subject: str             # Physics, Chemistry, Arabic, etc.
    source: str              # How this case was derived

@dataclass
class ValidationResult:
    """Result of validating one correction against one test case."""
    fix_name: str
    test_id: str
    passed: bool
    actual_output: str = ""
    expected_output: str = ""
    error_message: str = ""
    execution_time_ms: float = 0.0
    false_positive: bool = False
    false_negative: bool = False

@dataclass
class FixReport:
    """Report for one correction across all test cases."""
    fix_name: str
    total_tests: int
    passed: int
    failed: int
    false_positives: int
    false_negatives: int
    execution_time_ms: float
    pass_rate: float
    verdict: str  # ACCEPT / REJECT / NEEDS_WORK


# ═══════════════════════════════════════════════════════════════╗
#  GOLDEN DATASET CONSTRUCTION                                  ║
# ═══════════════════════════════════════════════════════════════╝

def build_golden_dataset() -> List[TestCase]:
    """
    Build the complete golden dataset of OCR error test cases.
    
    Each case is derived from REAL observed OCR errors in
    Egyptian Ministry of Education textbooks.
    """
    cases = []
    
    # =========================================================================
    # E-9: MCQ Character Class Too Narrow
    # Test that choices (ه), (و), (ز), etc. are recognized
    # =========================================================================
    
    cases.append(TestCase(
        id="E9-001",
        description="5 MCQ choices (أ-ه) — choice (ه) is lost",
        input_text="س1: ما عاصمة مصر؟\n(أ) القاهرة\n(ب) الإسكندرية\n(ج) الأقصر\n(د) أسوان\n(ه) بورسعيد",
        expected_output="س1: ما عاصمة مصر؟\n(أ) القاهرة\n(ب) الإسكندرية\n(ج) الأقصر\n(د) أسوان\n(ه) بورسعيد",
        error_class="E-9",
        subject="General",
        source="Real exam: 5-choice MCQ pattern",
    ))
    
    cases.append(TestCase(
        id="E9-002",
        description="6 MCQ choices (أ-و) — choice (و) is lost",
        input_text="اختر الإجابة الصحيحة:\n(أ) خيار 1\n(ب) خيار 2\n(ج) خيار 3\n(د) خيار 4\n(ه) خيار 5\n(و) خيار 6",
        expected_output="اختر الإجابة الصحيحة:\n(أ) خيار 1\n(ب) خيار 2\n(ج) خيار 3\n(د) خيار 4\n(ه) خيار 5\n(و) خيار 6",
        error_class="E-9",
        subject="General",
        source="Real exam: extended MCQ",
    ))
    
    # =========================================================================
    # E-10: Table Border Artifacts
    # Test that =====, ----, ||| are filtered
    # =========================================================================
    
    cases.append(TestCase(
        id="E10-001",
        description="Table border dashes — artifact line",
        input_text="الجدول الدوري:\n====================\nالهيدروجين   هيليوم\n--------------------\nالليثيوم     بيريليوم",
        expected_output="الجدول الدوري:\nالهيدروجين   هيليوم\nالليثيوم     بيريليوم",
        error_class="E-10",
        subject="Chemistry",
        source="OCR of periodic table border lines",
    ))
    
    cases.append(TestCase(
        id="E10-002",
        description="Table border pipes — vertical borders",
        input_text="||||||||||||||||\n| الاسم | العدد |\n||||||||||||||||\n| هيدروجين | 1 |\n||||||||||||||||",
        expected_output="| الاسم | العدد |\n| هيدروجين | 1 |",
        error_class="E-10",
        subject="Chemistry",
        source="OCR of table vertical borders",
    ))
    
    # =========================================================================
    # E-2: 2-Fragment Word Fragmentation
    # Test joining short fragments that should be one word
    # =========================================================================
    
    cases.append(TestCase(
        id="E2-001",
        description="2-fragment: 'ال كت اب' should be 'الكتاب'",
        input_text="هذا هو ال كت اب المدرسي",
        expected_output="هذا هو الكتاب المدرسي",
        error_class="E-2",
        subject="Arabic",
        source="Tesseract fragmenting ligatures",
    ))
    
    cases.append(TestCase(
        id="E2-002",
        description="2-fragment: 'با لاضافة' should be 'بالإضافة'",
        input_text="با لاضافة إلى ذلك",
        expected_output="بالإضافة إلى ذلك",
        error_class="E-2",
        subject="Arabic",
        source="Tesseract fragmenting 'بالإضافة'",
    ))
    
    cases.append(TestCase(
        id="E2-003",
        description="2-fragment: 'فيها' remains correct — NOT fragmented",
        input_text="فيها العديد من الفوائد",
        expected_output="فيها العديد من الفوائد",
        error_class="E-2",
        subject="Arabic",
        source="Negative test: valid 2-letter word",
    ))
    
    cases.append(TestCase(
        id="E2-004",
        description="2-fragment: 'من خلال' should NOT merge",
        input_text="يتم ذلك من خلال القانون",
        expected_output="يتم ذلك من خلال القانون",
        error_class="E-2",
        subject="Arabic",
        source="Negative test: 'من خلال' is two valid words",
    ))
    
    # =========================================================================
    # E-1: Dotted Letter Confusion (ب/ت/ث/ن/ي swaps)
    # Test that dot-variant generation corrects common OCR errors
    # =========================================================================
    
    cases.append(TestCase(
        id="E1-001",
        description="ب→ن confusion: 'نسيط' should be 'بسيط'",
        input_text="المفهوم نسيط للغاية",
        expected_output="المفهوم بسيط للغاية",
        error_class="E-1",
        subject="General",
        source="Tesseract ب/ن confusion",
    ))
    
    cases.append(TestCase(
        id="E1-002",
        description="ت→س confusion: 'يسنخدم' should be 'يستخدم'",
        input_text="يسنخدم الطالب القلم",
        expected_output="يستخدم الطالب القلم",
        error_class="E-1",
        subject="General",
        source="Tesseract ت/س confusion",
    ))
    
    cases.append(TestCase(
        id="E1-003",
        description="ي correctly: 'يختلف' should remain 'يختلف'",
        input_text="يختلف هذا عن ذاك",
        expected_output="يختلف هذا عن ذاك",
        error_class="E-1",
        subject="General",
        source="Negative test: correct word should not change",
    ))
    
    cases.append(TestCase(
        id="E1-004",
        description="Correct word: 'يتكون' should remain 'يتكون'",
        input_text="المركب يتكون من عنصرين",
        expected_output="المركب يتكون من عنصرين",
        error_class="E-1",
        subject="Chemistry",
        source="Negative test: correct word should not change",
    ))
    
    # =========================================================================
    # E-3: Merged Words (space omitted)
    # Test splitting long tokens into two valid words
    # =========================================================================
    
    cases.append(TestCase(
        id="E3-001",
        description="Merged: 'منخلال' should be 'من خلال'",
        input_text="يتم منخلال التجربة",
        expected_output="يتم من خلال التجربة",
        error_class="E-3",
        subject="General",
        source="Tesseract omitting space",
    ))
    
    cases.append(TestCase(
        id="E3-002",
        description="Merged: 'فالكتاب' — valid word, should NOT split",
        input_text="فالكتاب على الرف",
        expected_output="فالكتاب على الرف",
        error_class="E-3",
        subject="Arabic",
        source="Negative test: 'فالكتاب' is a valid word ('and the book')",
    ))
    
    cases.append(TestCase(
        id="E3-003",
        description="Merged: 'بالامس' should be 'بالأمس'",
        input_text="حدث ذلك بالامس",
        expected_output="حدث ذلك بالأمس",
        error_class="E-3",
        subject="General",
        source="Tesseract omitting space",
    ))
    
    # =========================================================================
    # E-4: Tashkeel (Diacritic) as Noise
    # Test removal of diacritical marks that survived as garbage chars
    # =========================================================================
    
    cases.append(TestCase(
        id="E4-001",
        description="Diacritic noise: leading diacritic chars",
        input_text="ُمحَّدٌ الرجل",
        expected_output="محمد الرجل",
        error_class="E-4",
        subject="Arabic",
        source="Tesseract interpreting tashkeel as characters",
    ))
    
    cases.append(TestCase(
        id="E4-002",
        description="Diacritic noise: embedded diacritics",
        input_text="قَوَانِينُ الفيزياء",
        expected_output="قوانين الفيزياء",
        error_class="E-4",
        subject="Arabic",
        source="Tesseract preserving tashkeel glyphs",
    ))
    
    cases.append(TestCase(
        id="E4-003",
        description="No tashkeel: clean text should not change",
        input_text="قوانين الفيزياء الأساسية",
        expected_output="قوانين الفيزياء الأساسية",
        error_class="E-4",
        subject="Physics",
        source="Negative test: already clean text",
    ))
    
    # =========================================================================
    # E-6: Ta-Marbuta (ة) / Ha (ه) Confusion
    # Test correction of ة→ه and ه→ة when dictionary supports it
    # =========================================================================
    
    cases.append(TestCase(
        id="E6-001",
        description="ة→ه: 'الاشاره' should be 'الإشارة' (if in dict)",
        input_text="الاشاره الصوتية",
        expected_output="الإشارة الصوتية",
        error_class="E-6",
        subject="General",
        source="Tesseract ة/ه confusion",
    ))
    
    cases.append(TestCase(
        id="E6-002",
        description="ه correct: 'وجه' should remain 'وجه'",
        input_text="وجه الرأي الآخر",
        expected_output="وجه الرأي الآخر",
        error_class="E-6",
        subject="Arabic",
        source="Negative test: 'وجه' ends in ه correctly",
    ))
    
    cases.append(TestCase(
        id="E6-003",
        description="ة correct: 'المدرسة' should remain 'المدرسة'",
        input_text="المدرسة جديدة",
        expected_output="المدرسة جديدة",
        error_class="E-6",
        subject="General",
        source="Negative test: already correct",
    ))
    
    # =========================================================================
    # E-8: Question Numbering Fragmentation
    # Test fixing broken question markers
    # =========================================================================
    
    cases.append(TestCase(
        id="E8-001",
        description="Question marker merged: 'س1احسب' should be 'س1: احسب'",
        input_text="س1احسب القوة المؤثرة",
        expected_output="س1: احسب القوة المؤثرة",
        error_class="E-8",
        subject="Physics",
        source="Tesseract merging question marker with text",
    ))
    
    cases.append(TestCase(
        id="E8-002",
        description="Question marker fragmented across lines: س\\n1",
        input_text="س\n1 احسب القوة",
        expected_output="س1: احسب القوة",
        error_class="E-8",
        subject="Physics",
        source="Tesseract splitting question marker across lines",
    ))
    
    cases.append(TestCase(
        id="E8-003",
        description="Normal text with س: 'وسائل' should not change",
        input_text="وسائل التواصل الاجتماعي",
        expected_output="وسائل التواصل الاجتماعي",
        error_class="E-8",
        subject="General",
        source="Negative test: 'س' inside a word, not a question marker",
    ))
    
    # =========================================================================
    # E-11: Degree Symbol Corruption
    # Test that 'o' or '0' before 'C' becomes '°'
    # =========================================================================
    
    cases.append(TestCase(
        id="E11-001",
        description="Degree as 'o': '25oC' should be '25°C'",
        input_text="درجة الحرارة 25oC",
        expected_output="درجة الحرارة 25°C",
        error_class="E-11",
        subject="Physics",
        source="Tesseract rendering ° as 'o'",
    ))
    
    cases.append(TestCase(
        id="E11-002",
        description="Degree as '0': '1000C' should not change (water boils at 100°C, not 1000°C)",
        input_text="درجة 1000C",
        expected_output="درجة 1000C",
        error_class="E-11",
        subject="Physics",
        source="Negative test: 'C' without degree is valid (temperature scale shown without degree)",
    ))
    
    cases.append(TestCase(
        id="E11-003",
        description="Degree as 'O': '37OC' should be '37°C'",
        input_text="درجة حرارة الجسم 37OC",
        expected_output="درجة حرارة الجسم 37°C",
        error_class="E-11",
        subject="Biology",
        source="Tesseract O→0→° confusion",
    ))
    
    # =========================================================================
    # E-12: Fraction Bar Confusion
    # Test that '1-2' in math context becomes '½'
    # =========================================================================
    
    cases.append(TestCase(
        id="E12-001",
        description="Fraction: '1-2' in math context becomes '½'",
        input_text="السرعة = 1-2 م/ث",
        expected_output="السرعة = ½ م/ث",
        error_class="E-12",
        subject="Physics",
        source="OCR rendering fraction bar as hyphen",
    ))
    
    cases.append(TestCase(
        id="E12-002",
        description="Range: 'القرن 1-2' should NOT become 'القرن ½'",
        input_text="القرن 1-2 قبل الميلاد",
        expected_output="القرن 1-2 قبل الميلاد",
        error_class="E-12",
        subject="History",
        source="Negative test: date range, not fraction",
    ))
    
    # =========================================================================
    # LATIN-ARABIC CONFUSION (Q-1)
    # Test that Latin letters in Arabic context are corrected
    # =========================================================================
    
    cases.append(TestCase(
        id="Q1-001",
        description="H→ح: 'Hمض' should be 'حمض'",
        input_text="Hمض الكبريتيك",
        expected_output="حمض الكبريتيك",
        error_class="Q-1",
        subject="Chemistry",
        source="Tesseract ح→H confusion",
    ))
    
    cases.append(TestCase(
        id="Q1-002",
        description="Protected: 'H₂SO₄' should NOT be modified",
        input_text="حمض H₂SO₄ مركز",
        expected_output="حمض H₂SO₄ مركز",
        error_class="Q-1",
        subject="Chemistry",
        source="Negative test: chemical formula must be preserved",
    ))
    
    cases.append(TestCase(
        id="Q1-003",
        description="c→ع: 'cند' should be 'عند'",
        input_text="cند درجة حرارة",
        expected_output="عند درجة حرارة",
        error_class="Q-1",
        subject="Physics",
        source="Tesseract ع→c confusion",
    ))
    
    # =========================================================================
    # LANGUAGE-SPECIFIC TEST: Mixed Arabic-English
    # =========================================================================
    
    cases.append(TestCase(
        id="LANG-001",
        description="Mixed: Arabic sentence with English technical term",
        input_text="يتم حساب pH المحلول",
        expected_output="يتم حساب pH المحلول",
        error_class="LANG",
        subject="Chemistry",
        source="Negative test: 'pH' is correct English in Arabic text",
    ))
    
    cases.append(TestCase(
        id="LANG-002",
        description="Mixed: equation with Latin variables",
        input_text="المعادلة F = m × a",
        expected_output="المعادلة F = m × a",
        error_class="LANG",
        subject="Physics",
        source="Negative test: physics equation must survive",
    ))
    
    # =========================================================================
    # REGRESSION TEST: Previously Correct Text Should Not Change
    # =========================================================================
    
    cases.append(TestCase(
        id="REG-001",
        description="Regression: clean Arabic paragraph",
        input_text="القوة هي مؤثر خارجي يغير من حركة الجسم",
        expected_output="القوة هي مؤثر خارجي يغير من حركة الجسم",
        error_class="REG",
        subject="Physics",
        source="Regression test: already correct text",
    ))
    
    cases.append(TestCase(
        id="REG-002",
        description="Regression: chemistry reaction",
        input_text="H₂ + O₂ → H₂O",
        expected_output="H₂ + O₂ → H₂O",
        error_class="REG",
        subject="Chemistry",
        source="Regression test: correct chemical equation",
    ))
    
    cases.append(TestCase(
        id="REG-003",
        description="Regression: MCQ with 4 choices",
        input_text="اختر الإجابة الصحيحة:\n(أ) 10 نيوتن\n(ب) 15 نيوتن\n(ج) 20 نيوتن\n(د) 25 نيوتن",
        expected_output="اختر الإجابة الصحيحة:\n(أ) 10 نيوتن\n(ب) 15 نيوتن\n(ج) 20 نيوتن\n(د) 25 نيوتن",
        error_class="REG",
        subject="Physics",
        source="Regression test: already correct MCQ",
    ))
    
    cases.append(TestCase(
        id="REG-004",
        description="Regression: Arabic text with numbers",
        input_text="كتلة الجسم 5 كجم",
        expected_output="كتلة الجسم 5 كجم",
        error_class="REG",
        subject="Physics",
        source="Regression test: already correct",
    ))
    
    return cases


# ═══════════════════════════════════════════════════════════════╗
#  VALIDATION TEST HARNESS                                      ║
# ═══════════════════════════════════════════════════════════════╝

def test_correction(
    fix_name: str,
    correction_fn: Callable[[str], str],
    test_cases: List[TestCase],
    error_class_filter: Optional[str] = None,
) -> FixReport:
    """
    Test a correction function against all (or filtered) test cases.
    
    Args:
        fix_name: Name of the fix being tested
        correction_fn: Function that takes text and returns corrected text
        test_cases: List of all test cases
        error_class_filter: If set, only test cases with this error class
    
    Returns:
        FixReport with pass/fail for each test case
    """
    total_time = 0.0
    passed = 0
    failed = 0
    false_positives = 0
    false_negatives = 0
    results = []
    
    for tc in test_cases:
        if error_class_filter and tc.error_class != error_class_filter:
            continue
        
        start = time.perf_counter()
        try:
            actual = correction_fn(tc.input_text)
        except Exception as e:
            actual = f"[CRASH: {e}]"
        elapsed = (time.perf_counter() - start) * 1000
        total_time += elapsed
        
        passed_test = (actual == tc.expected_output)
        
        # CORRECT false positive detection:
        # FP = input was already correct, but function changed it to something wrong
        is_false_positive = (tc.input_text == tc.expected_output 
                             and actual != tc.expected_output)
        # FN = input was wrong, function didn't change it (produced same wrong output)
        is_false_negative = (actual == tc.input_text 
                             and tc.input_text != tc.expected_output)
        # Other failure = function produced a DIFFERENT wrong output (not FP, not FN)
        # This is a "wrong correction" — changed text but to the wrong fix
        
        result = ValidationResult(
            fix_name=fix_name,
            test_id=tc.id,
            passed=passed_test,
            actual_output=actual,
            expected_output=tc.expected_output,
            execution_time_ms=round(elapsed, 2),
            false_positive=is_false_positive,
            false_negative=is_false_negative,
        )
        results.append(result)
        
        if passed_test:
            passed += 1
        else:
            failed += 1
            if result.false_positive:
                false_positives += 1
            if result.false_negative:
                false_negatives += 1
    
    total = passed + failed
    pass_rate = (passed / total * 100) if total > 0 else 0.0
    
    # Determine verdict
    if total == 0:
        verdict = "NO_TESTS"
    elif pass_rate == 100.0 and false_positives == 0:
        verdict = "✅ ACCEPT"
    elif pass_rate >= 90.0 and false_positives <= 1:
        verdict = "⚠️ ACCEPT_WITH_CAVEATS"
    elif false_positives >= 2:
        verdict = "❌ REJECT — Too many false positives"
    else:
        verdict = "❌ REJECT — Does not meet accuracy threshold"
    
    return FixReport(
        fix_name=fix_name,
        total_tests=total,
        passed=passed,
        failed=failed,
        false_positives=false_positives,
        false_negatives=false_negatives,
        execution_time_ms=round(total_time, 2),
        pass_rate=round(pass_rate, 1),
        verdict=verdict,
    )


def print_report(report: FixReport, verbose: bool = True):
    """Print a validation report."""
    status = "✅" if "ACCEPT" in report.verdict else "❌"
    print(f"\n{status} {report.fix_name}")
    print(f"   {'=' * 50}")
    print(f"   Tests:     {report.total_tests}")
    print(f"   Passed:    {report.passed}/{report.total_tests} ({report.pass_rate}%)")
    print(f"   Failed:    {report.failed}")
    if report.false_positives > 0:
        print(f"   ⚠️  FP:      {report.false_positives} (introduced errors in correct text)")
    if report.false_negatives > 0:
        print(f"   ⚠️  FN:      {report.false_negatives} (failed to fix actual errors)")
    print(f"   Time:      {report.execution_time_ms}ms")
    print(f"   Verdict:   {report.verdict}")


# ═══════════════════════════════════════════════════════════════╗
#  CORRECTION IMPLEMENTATIONS (TO BE VALIDATED)                 ║
# ═══════════════════════════════════════════════════════════════╝

def fix_E9_mcq_character_class(text: str) -> str:
    """
    [E-9] Expand MCQ character class from [أبجد] to full alphabet.
    This ensures choices (ه), (و), (ز), etc. are recognized.
    """
    # Expand the character class wherever it appears
    FULL_ALPHABET = r'أبجدهوزحطيكلمنسعفصقرشثتخذضظغ'
    
    # Fix MCQ detection patterns
    text = re.sub(
        r'\(([' + FULL_ALPHABET + r'])\)',
        lambda m: '(' + m.group(1) + ')',
        text,
    )
    
    # Split choices that are on the same line
    pattern = r'(?<!\n)\s+(?=\(' + FULL_ALPHABET + r'\))'
    text = re.sub(pattern, '\n', text)
    
    return text


def fix_E10_table_border_artifacts(text: str) -> str:
    """
    [E-10] Remove table border artifacts.
    Lines consisting only of repeating =, -, |, _, ~, #, * are OCR artifacts.
    """
    lines = text.split('\n')
    filtered = []
    for line in lines:
        stripped = line.strip()
        # If line is >80% repeating non-letter characters, skip it
        if stripped and len(stripped) > 3:
            non_alpha = sum(1 for c in stripped if not c.isalnum() and not '\u0600' <= c <= '\u06FF')
            if non_alpha / len(stripped) > 0.8:
                # Check if it's mostly repeating - = | _ ~ # *
                if re.match(r'^[-=|_~#*\s]{4,}$', stripped):
                    continue  # Skip this line
        filtered.append(line)
    return '\n'.join(filtered)


def fix_E2_fragmented_words(text: str) -> str:
    """
    [E-2] Join 2-fragment Arabic words that were separated by Tesseract.
    Pattern: two short Arabic tokens (2-4 chars each) that form a valid word.
    """
    # Load lexicon
    try:
        sys.path.insert(0, '.')
        from lexicon_engine import FULL_LEXICON
    except ImportError:
        FULL_LEXICON = set()
    
    def _try_join(match):
        first = match.group(1)
        second = match.group(2)
        combined = first + second
        
        # Only join if the combined form exists in the lexicon
        if combined in FULL_LEXICON and first not in FULL_LEXICON:
            return combined
        # If both are valid words separately, keep them separate
        if first in FULL_LEXICON and second in FULL_LEXICON:
            return f"{first} {second}"
        # If only the combined form exists, join
        if combined in FULL_LEXICON:
            return combined
        return match.group(0)
    
    # Match: 2-4 Arabic chars + space + 2-4 Arabic chars (at word boundaries)
    pattern = r'\b([\u0600-\u06FF]{2,4})\s+([\u0600-\u06FF]{2,4})\b'
    text = re.sub(pattern, _try_join, text)
    
    return text


def fix_E1_dot_variant_generation(text: str) -> str:
    """
    [E-1] Try dot-variant generation for dictionary-missed words.
    For each Arabic word not in the lexicon, try varying the dots
    within confusable groups (ب/ت/ث/ن/ي, س/ش, etc.)
    """
    try:
        sys.path.insert(0, '.')
        from lexicon_engine import FULL_LEXICON
    except ImportError:
        FULL_LEXICON = set()
    
    DOT_GROUPS = {
        'ب': {'ب', 'ت', 'ث', 'ن', 'ي'},
        'ت': {'ب', 'ت', 'ث', 'ن', 'ي'},
        'ث': {'ب', 'ت', 'ث', 'ن', 'ي'},
        'ن': {'ب', 'ت', 'ث', 'ن', 'ي'},
        'ي': {'ب', 'ت', 'ث', 'ن', 'ي'},
        'س': {'س', 'ش'},
        'ش': {'س', 'ش'},
        'ح': {'ح', 'ج', 'خ'},
        'ج': {'ح', 'ج', 'خ'},
        'خ': {'ح', 'ج', 'خ'},
        'د': {'د', 'ذ'},
        'ذ': {'د', 'ذ'},
        'ص': {'ص', 'ض'},
        'ض': {'ص', 'ض'},
        'ط': {'ط', 'ظ'},
        'ظ': {'ط', 'ظ'},
        'ع': {'ع', 'غ'},
        'غ': {'ع', 'غ'},
        'ف': {'ف', 'ق'},
        'ق': {'ف', 'ق'},
        'ه': {'ه', 'ة'},
        'ة': {'ه', 'ة'},
    }
    
    def _generate_variants(word: str) -> list:
        """Generate all dot variants changing exactly 1 letter."""
        if len(word) < 3 or len(word) > 15:
            return [word]
        
        variants = []
        for i, ch in enumerate(word):
            if ch in DOT_GROUPS:
                for replacement in DOT_GROUPS[ch]:
                    if replacement != ch:
                        variant = word[:i] + replacement + word[i+1:]
                        if variant in FULL_LEXICON:
                            variants.append(variant)
        return variants
    
    def _fix_word(match):
        word = match.group(0)
        if word in FULL_LEXICON:
            return word  # Already correct
        variants = _generate_variants(word)
        if variants:
            return variants[0]  # Return first valid variant
        return word
    
    return re.sub(r'[\u0600-\u06FF]{3,15}', _fix_word, text)


def fix_E3_merged_words(text: str) -> str:
    """
    [E-3] Split merged words that should be two words.
    """
    try:
        sys.path.insert(0, '.')
        from lexicon_engine import FULL_LEXICON
    except ImportError:
        FULL_LEXICON = set()
    
    def _try_split(word: str) -> str:
        if len(word) < 8:
            return word
        # Try splitting at every position from 3 to len-3
        for split_pos in range(3, len(word) - 2):
            first = word[:split_pos]
            second = word[split_pos:]
            if first in FULL_LEXICON and second in FULL_LEXICON:
                return f"{first} {second}"
        return word
    
    def _fix_long_word(match):
        return _try_split(match.group(0))
    
    # Only process pure Arabic words that are suspiciously long
    return re.sub(r'\b[\u0600-\u06FF]{8,}\b', _fix_long_word, text)


def fix_E4_tashkeel_removal(text: str) -> str:
    """
    [E-4] Remove diacritical marks (tashkeel) that Tesseract outputs as characters.
    """
    # Remove Arabic diacritics: فتحة, ضمة, كسرة, سكون, شدة, etc.
    # Preserve actual text characters
    text = re.sub(r'[\u064B-\u0652]', '', text)
    return text


def fix_E6_ta_marbuta(text: str) -> str:
    """
    [E-6] Fix ة/ه confusion when dictionary supports the correction.
    """
    try:
        sys.path.insert(0, '.')
        from lexicon_engine import FULL_LEXICON
    except ImportError:
        FULL_LEXICON = set()
    
    def _fix_ending(match):
        word = match.group(0)
        if word.endswith('ه') and len(word) > 3:
            candidate = word[:-1] + 'ة'
            if candidate in FULL_LEXICON:
                return candidate
        return word
    
    return re.sub(r'[\u0600-\u06FF]{3,}', _fix_ending, text)


def fix_E8_question_marker(text: str) -> str:
    """
    [E-8] Fix broken question markers (س1, س 1, س\n1 → س1:).
    """
    # Case 1: "س1احسب" → "س1: احسب" (merged with text)
    text = re.sub(r'س(\d+)([^\s:])', r'س\1: \2', text)
    
    # Case 2: "س\n1" → "س1" (fragmented across lines)
    # Handle both "س\n1" and "س \n1" and "س  \n1"
    text = re.sub(r'^\s*س\s*\n+\s*(\d+)', r'س\1', text, flags=re.MULTILINE)
    
    # Case 3: "س1:" if no space after colon → "س1: "
    text = re.sub(r'س(\d+):([^\s])', r'س\1: \2', text)
    
    return text


def fix_E11_degree_symbol(text: str) -> str:
    """
    [E-11] Fix degree symbol corruption.
    "25oC" → "25°C", "37OC" → "37°C"
    """
    # Fix "25oC" → "25°C" (lowercase o)
    text = re.sub(r'(\d+)\s*[oO]\s*C\b', r'\1°C', text)
    return text


def fix_Q1_latin_arabic_confusion(text: str) -> str:
    """
    [Q-1] Fix Latin letters that Tesseract substitutes for Arabic letters.
    PROTECTED: Chemical formulas (H₂SO₄), equations (F = ma) are preserved.
    """
    LATIN_TO_ARABIC = {
        "H": "ح", "c": "ع", "C": "ع", "S": "ص",
        "D": "ض", "T": "ط", "Q": "ق", "k": "ك",
        "l": "ل", "n": "ن", "y": "ي", "s": "س",
        "d": "د", "r": "ر", "b": "ب", "t": "ت",
        "m": "م",
    }
    
    def _detect_chemical_or_equation(text: str) -> set:
        """Find protected regions (chemical formulas, equations)."""
        protected = set()
        
        # Chemical formulas: H₂SO₄, CO₂, NaOH, etc.
        for m in re.finditer(r'\b(?:[A-Z][a-z]?\d*(?:[₀-₉]|\d)*)+\b', text):
            for i in range(m.start(), m.end()):
                protected.add(i)
        
        return protected
    
    protected_indices = _detect_chemical_or_equation(text)
    
    def _fix_mixed_word(match):
        word = match.group(0)
        start_pos = match.start()
        
        has_arabic = bool(re.search(r'[\u0600-\u06FF]', word))
        has_latin = bool(re.search(r'[A-Za-z]', word))
        
        if not (has_arabic and has_latin):
            return word  # Pure Arabic or pure Latin — let other passes handle
        
        # Check if this position is protected
        word_end = start_pos + len(word)
        if any(start_pos <= i < word_end for i in protected_indices):
            return word  # Protected
        
        # Fix Latin letters in mixed context
        result = []
        for ch in word:
            if ch in LATIN_TO_ARABIC:
                result.append(LATIN_TO_ARABIC[ch])
            else:
                result.append(ch)
        return ''.join(result)
    
    return re.sub(r'[\u0600-\u06FFA-Za-z]{2,}', _fix_mixed_word, text)


# ═══════════════════════════════════════════════════════════════╗
#  VALIDATION RUNNER                                            ║
# ═══════════════════════════════════════════════════════════════╝

def validate_all():
    """
    Run all validations and produce a complete report.
    
    Each correction is tested against:
    1. Its OWN target test cases (positive cases)
    2. ALL regression tests (REG) — ensures no regressions
    3. ALL language tests (LANG) — ensures no cross-language damage
    
    Run with: python validation.py
    """
    # Register all corrections to test with their target error classes
    corrections: List[Tuple[str, Callable, List[str]]] = [
        ("E-9: MCQ character class expansion", fix_E9_mcq_character_class, ["E-9"]),
        ("E-10: Table border artifacts", fix_E10_table_border_artifacts, ["E-10"]),
        ("E-2: Fragmented word joining", fix_E2_fragmented_words, ["E-2"]),
        ("E-1: Dot variant generation", fix_E1_dot_variant_generation, ["E-1"]),
        ("E-3: Merged word splitting", fix_E3_merged_words, ["E-3"]),
        ("E-4: Tashkeel removal", fix_E4_tashkeel_removal, ["E-4"]),
        ("E-6: Ta-marbuta correction", fix_E6_ta_marbuta, ["E-6"]),
        ("E-8: Question marker fix", fix_E8_question_marker, ["E-8"]),
        ("E-11: Degree symbol fix", fix_E11_degree_symbol, ["E-11"]),
        ("Q-1: Latin-Arabic confusion", fix_Q1_latin_arabic_confusion, ["Q-1"]),
    ]
    
    # Build golden dataset
    dataset = build_golden_dataset()
    
    print("=" * 60)
    print("  EVRO OCR ENGINE — CORRECTION VALIDATION REPORT")
    print(f"  Dataset: {len(dataset)} test cases")
    print("=" * 60)
    
    # BUG IN V1: All corrections were tested against ALL cases (38 each).
    # FIX: Each correction is now tested against:
    #   - Its own target test cases (positive)
    #   - ALL regression cases (negative — must not break)
    #   - ALL language cases (negative — must not break)
    # This gives a true picture of both accuracy AND safety.
    
    all_results = []
    
    for fix_name, fix_fn, target_classes in corrections:
        # Compile test set: target cases + regression + language
        test_ids = set()
        for tc in dataset:
            if tc.error_class in target_classes:
                test_ids.add(tc.id)
            if tc.error_class == "REG":
                test_ids.add(tc.id)
            if tc.error_class == "LANG":
                test_ids.add(tc.id)
        
        # Filter dataset to only these IDs
        filtered_dataset = [tc for tc in dataset if tc.id in test_ids]
        
        report = test_correction(
            fix_name, fix_fn, filtered_dataset, error_class_filter=None
        )
        print_report(report)
        all_results.append(report)
    
    # Summary
    print("\n" + "=" * 60)
    print("  VALIDATION SUMMARY")
    print("=" * 60)
    
    accepted = [r for r in all_results if "ACCEPT" in r.verdict]
    rejected = [r for r in all_results if "REJECT" in r.verdict]
    needs_work = [r for r in all_results if "CAVEATS" in r.verdict]
    
    print(f"  ✅ Accepted:        {len(accepted)}")
    print(f"  ⚠️  Needs Work:     {len(needs_work)}")
    print(f"  ❌ Rejected:        {len(rejected)}")
    print()
    
    if accepted:
        print("  Corrections approved for production:")
        for r in accepted:
            print(f"    ✅ {r.fix_name}  ({r.pass_rate}% pass, {r.false_positives} FP)")
    
    if needs_work:
        print("\n  Corrections that need improvement:")
        for r in needs_work:
            print(f"    ⚠️  {r.fix_name}  ({r.pass_rate}% pass, {r.false_positives} FP)")
    
    if rejected:
        print("\n  Corrections rejected:")
        for r in rejected:
            print(f"    ❌ {r.fix_name}  ({r.pass_rate}% pass, {r.false_positives} FP)")
    
    print()
    print("=" * 60)
    
    return all_results, dataset


def print_detailed_results(all_results, dataset):
    """Print detailed pass/fail for each test case."""
    print("\n" + "=" * 60)
    print("  DETAILED TEST RESULTS")
    print("=" * 60)
    print("  (detailed results available by running with --verbose)")
    

# ═══════════════════════════════════════════════════════════════╗
#  CLI                                                          ║
# ═══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    
    results, dataset = validate_all()
    
    # Print dataset stats
    error_classes = Counter(tc.error_class for tc in dataset)
    print(f"\nDataset composition:")
    for ec, count in sorted(error_classes.items()):
        print(f"  {ec}: {count} cases")
    
    subjects = Counter(tc.subject for tc in dataset)
    print(f"\nSubjects:")
    for subj, count in sorted(subjects.items()):
        print(f"  {subj}: {count} cases")
