"""
محرك تنسيق النصوص العربية — Arabic Text Formatter
===================================================
كشف بنية النص الأكاديمي، تحويله لـ Markdown، تصحيح علامات الترقيم، جداول.
"""

import re
from typing import List, Tuple


# ─────────────────────────────────────────────────────────
# (أ) كشف بنية السطر
# ─────────────────────────────────────────────────────────
def _is_equation(line: str) -> bool:
    """كشف إذا كان السطر معادلة رياضية أو كيميائية."""
    has_equals = "=" in line
    # أسهم (يونيكود + ASCII)
    has_arrow = any(s in line for s in ["→", "⇌", "←", "->", "=>"])
    # صيغة كيميائية: تحتاج سياق (سهم أو معادلة) وليس مجرد وجود H₂O في جملة
    has_chemical_formula = bool(re.search(r'\b[A-Z][a-z]?[₀-₉]+', line))
    has_chemical_context = has_chemical_formula and (has_arrow or has_equals)
    # معادلات رقمية (تحتوي أرقام + عوامل)
    has_math_op = bool(re.search(r'[+\-×÷\*x]\s*[\d\u0660-\u0669a-zA-Z]', line))
    # معادلات رمزية (F = m × a)
    has_math_op_symbolic = bool(re.search(r'[A-Za-z]\s*=\s*[A-Za-z]\s*[×÷+\-\*x]\s*[A-Za-z]', line)) or \
        bool(re.search(r'[A-Za-z]\s*[×÷\*]\s*[A-Za-z]\s*=\s*[A-Za-z]', line))
    has_fraction = bool(re.search(r'[½¼¾⅓⅔]', line))
    # معادلات علمية (رقم × وحدة)
    has_sci_eq = bool(re.search(r'\d+\s*=\s*\d+\s*[×÷\-]\s*\d+', line))
    return has_arrow or has_chemical_context or has_sci_eq or (has_equals and (has_math_op or has_math_op_symbolic or has_fraction))


def detect_structure(line: str) -> str:
    """
    تصنيف السطر حسب نوعه الأكاديمي.
    """
    stripped = line.strip()
    if not stripped:
        return "paragraph"

    # 1. فاصل صفحات — النمط الدقيق الذي يخرجه extractor.py
    if re.match(r'^-{3,}$', stripped) or re.match(r'^\-+\s*\[\s*صفحة\s*\d+\s*\]\s*\-+$', stripped):
        return "page_break"

    # 2. تنويه بصري
    if "تنويه" in stripped or "🖼️" in stripped:
        return "visual_note"

    # 3. سؤال — أنماط موسعة (قبل عنوان فرعي لمن اعتقاد الـ 1-...)
    if (
        re.match(r"^س\d", stripped)
        or re.match(r"^\d+[\.\-\)]\s", stripped)
        or re.match(r"^[١-٩][\.\-\)]\s", stripped)
        or re.match(r"^[\(\[]\d+[\)\]]\s", stripped)
        or re.match(r"^[\(\[][١-٩][\)\]]\s", stripped)
        or re.match(r"^(اذكر|عدد|علل|فسر|قارن|وضح|ناقش|اشرح|استنتج|احسب|جد|برهن|اثبت)", stripped)
        or any(kw in stripped for kw in ["اختر", "احسب", "بين", "علل",
                                          "قارن", "ما المقصود", "استنتج",
                                          "أوجد", "أثبت", "وضح", "اذكر",
                                          "عرف", "اكتب", "أكمل"])
    ):
        return "question"

    # 4. عنوان فصل/باب/وحدة
    if (re.match(r"^(الفصل|الباب|الوحدة|مقدمة|تمهيد|Chapter|Unit)\b", stripped)
        or (stripped.isascii() and stripped.isupper()
            and len(stripped) > 3 and not stripped.isdigit()
            and re.match(r'^[A-Z][A-Z\d\s]{2,}$', stripped))):
        return "chapter_title"

    # 5. عنوان فرعي
    if len(stripped) < 80 and (
        re.match(r"^\d+\s*[-–—]", stripped)
        or stripped.startswith(("أولاً", "ثانياً", "ثالثاً", "رابعاً", "خامساً"))
        or stripped.endswith(":")
    ):
        return "section_title"

    # 5. سؤال — أنماط موسعة
    if (
        re.match(r"^س\d", stripped)
        or re.match(r"^\d+[\.\-\)]\s", stripped)
        or re.match(r"^[١-٩][\.\-\)]\s", stripped)
        or re.match(r"^[\(\[]\d+[\)\]]\s", stripped)
        or re.match(r"^[\(\[][١-٩][\)\]]\s", stripped)
        or re.match(r"^(اذكر|عدد|علل|فسر|قارن|وضح|ناقش|اشرح|استنتج|احسب|جد|برهن|اثبت)", stripped)
        or any(kw in stripped for kw in ["اختر", "احسب", "بين", "علل",
                                          "قارن", "ما المقصود", "استنتج",
                                          "أوجد", "أثبت", "وضح", "اذكر",
                                          "عرف", "اكتب", "أكمل"])
    ):
        return "question"

    # 6. اختيار
    if re.match(r"^\([أ-د]\)", stripped) or re.match(r"^[أ-د]\s*[-–—]", stripped):
        return "choice"

    # 7. معادلة — منطق مضبوط
    if _is_equation(stripped):
        return "equation"

    # 8. جدول
    if stripped.count("\t") >= 2 or "|" in stripped:
        return "table_row"

    # 9. فقرة عادية
    return "paragraph"


# ─────────────────────────────────────────────────────────
# (ب) تقسيم خيارات MCQ
# ─────────────────────────────────────────────────────────
def _split_mcq_choices(text: str) -> str:
    """تقسيم خيارات MCQ المتراصة على سطر واحد إلى أسطر منفصلة."""
    patterns = [
        r'(?<!\n)\s+(?=\([أبجد]\))',           # (أ) (ب)
        r'(?<!\n)\s+(?=[أبجد]\s*[-–]\s)',       # أ- ب-
        r'(?<!\n)\s+(?=[أبجد]\s*\))',           # أ) ب)
        r'(?<!\n)\s+(?=\(\s*[أبجد]\s*\))',      # ( أ ) ( ب )
    ]
    for p in patterns:
        text = re.sub(p, '\n', text)
    return text


# ─────────────────────────────────────────────────────────
# (ج) تنسيق لـ Markdown
# ─────────────────────────────────────────────────────────
def format_as_markdown(raw_text: str) -> str:
    """
    تحويل النص الخام إلى Markdown منظم.
    """
    if not raw_text:
        return ""

    # تقسيم الخيارات أولاً
    raw_text = _split_mcq_choices(raw_text)

    lines = raw_text.split("\n")
    output: List[str] = []
    i = 0
    prev_type = "paragraph"
    consecutive_blank = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            consecutive_blank += 1
            if consecutive_blank <= 2:
                output.append("")
            i += 1
            continue

        consecutive_blank = 0
        line_type = detect_structure(stripped)

        if line_type == "page_break":
            page_match = re.search(r'صفحة\s*(\d+)', line)
            if page_match:
                output.append(f"\n\n---\n**📄 صفحة {page_match.group(1)}**\n---\n")
            else:
                output.append("\n---\n")

        elif line_type == "visual_note":
            output.append(f"> ⚠️ {stripped}\n")

        elif line_type == "chapter_title":
            if output and output[-1] != "":
                output.append("")
            output.append(f"\n# {stripped}\n")

        elif line_type == "section_title":
            if prev_type != "section_title":
                output.append("\n")
            output.append(f"## {stripped}\n")

        elif line_type == "question":
            output.append(f"\n### {stripped}\n")

        elif line_type == "choice":
            output.append(f"- {stripped}")

        elif line_type == "equation":
            output.append(f"\n> 📐 {stripped}\n")

        elif line_type == "table_row":
            output.append(stripped)

        else:  # paragraph
            if (
                prev_type == "paragraph"
                and output
                and not output[-1].endswith((".", "؟", "!", ":", "؛"))
            ):
                output[-1] = output[-1].rstrip("\n") + " " + stripped + "\n"
            else:
                output.append(f"{stripped}\n")

        prev_type = line_type
        i += 1

    result = "\n".join(output)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ─────────────────────────────────────────────────────────
# (د) تصحيح علامات الترقيم
# ─────────────────────────────────────────────────────────
def fix_punctuation(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"([\u0600-\u06FF]),([\u0600-\u06FF])", r"\1،\2", text)
    text = re.sub(r"\s+([،؛.؟!])", r"\1", text)
    text = re.sub(r"([،؛.؟!])(\S)", r"\1 \2", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"،{2,}", "،", text)
    text = re.sub(r"؟{2,}", "؟", text)
    text = re.sub(r"!{2,}", "!", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r'"\s+', '"', text)
    text = re.sub(r'\s+"', '"', text)
    text = re.sub(r"([^\n.!؟\n])\n(?!\n)", r"\1.\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ─────────────────────────────────────────────────────────
# (هـ) تنسيق الجداول الذكي
# ─────────────────────────────────────────────────────────
def smart_table_formatter(text: str) -> str:
    """
    كشف الجداول في النص وتحويلها لجداول Markdown.
    """
    lines = text.split('\n')
    result = []
    table_buffer = []
    in_table = False

    def _looks_like_table_row(line: str) -> bool:
        has_tabs = line.count('\t') >= 2
        has_multi_spaces = len(re.findall(r'\s{3,}', line)) >= 2
        has_pipe = '|' in line
        return has_tabs or has_multi_spaces or has_pipe

    def _parse_table_row(line: str) -> list:
        if '|' in line:
            return [c.strip() for c in line.split('|') if c.strip()]
        if '\t' in line:
            return [c.strip() for c in line.split('\t') if c.strip()]
        return [c.strip() for c in re.split(r'\s{3,}', line) if c.strip()]

    def _render_markdown_table(rows: list) -> str:
        if not rows:
            return ""
        # تحويل كل عنصر لـ str لضمان عدم وجود TypeError في join
        def _ensure_str_list(lst: list) -> List[str]:
            return [str(item) for item in lst]
        max_cols = max(len(r) for r in rows)
        normalized = [_ensure_str_list(r) + [''] * (max_cols - len(r)) for r in rows]
        md = '| ' + ' | '.join(normalized[0]) + ' |\n'
        md += '| ' + ' | '.join(['---'] * max_cols) + ' |\n'
        for row in normalized[1:]:
            md += '| ' + ' | '.join(row) + ' |\n'
        return md

    for line in lines:
        if _looks_like_table_row(line):
            table_buffer.append(_parse_table_row(line))
            in_table = True
        else:
            if in_table and len(table_buffer) >= 2:
                result.append(_render_markdown_table(table_buffer))
                table_buffer = []
                in_table = False
            elif in_table:
                # سطر واحد فقط — مش جدول، نرجعه كنص (وليس كقائمة لمنع خطأ join)
                result.extend(['\t'.join(row) for row in table_buffer])
                table_buffer = []
                in_table = False
            result.append(line)

    if in_table and len(table_buffer) >= 2:
        result.append(_render_markdown_table(table_buffer))

    return '\n'.join(result)


# ─────────────────────────────────────────────────────────
# (و) خط التنسيق الكامل
# ─────────────────────────────────────────────────────────
def format_pipeline(raw_text: str) -> Tuple[str, str]:
    if not raw_text:
        return ("", "")

    plain = fix_punctuation(raw_text)
    markdown = format_as_markdown(plain)
    markdown = smart_table_formatter(markdown)

    plain_text = re.sub(r"^#+\s*", "", markdown, flags=re.MULTILINE)
    plain_text = re.sub(r"^-+\s*", "• ", plain_text, flags=re.MULTILINE)
    plain_text = re.sub(r"> 📐 ", "", plain_text)
    plain_text = re.sub(r"> ⚠️ ", "⚠️ ", plain_text)
    plain_text = re.sub(r"\n---\n", "\n\n", plain_text)
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text)
    plain_text = re.sub(r"\*\*📄 صفحة \d+\*\*", "", plain_text)

    return (plain_text.strip(), markdown.strip())


# ─────────────────────────────────────────────────────────
# CLI للاختبار
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("📝 formatter.py — اختبار")
    sample = """
--- [ صفحة 1 ] ---

الفصل الأول: القوى والحركة

1- ما المقصود بالقوة؟

(أ) كتلة الجسم
(ب) مقدار سرعة الجسم
(ج) مؤثر يغير حركة الجسم
(د) وزن الجسم

القوة هي مؤثر خارجي يغير من حركة الجسم

F = m × a

2- احسب القوة المؤثرة
    """
    plain, md = format_pipeline(sample)
    print("✅ TEST OK")
    print(md[:200])
