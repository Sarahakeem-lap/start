"""
Evro OCR V2 - Domain Knowledge Base Builder
===========================================
Ingests educational TXT files from C:\\Users\\Mahmoud\\Desktop\\New folder
Builds:
1. Unique words & frequency dictionary
2. Frequent phrases (2-grams, 3-grams, 4-grams)
3. Named entities & Subject-specific terminology
4. Searchable phrase index & Context windows
5. SQLite Knowledge Base for validation and decision-making
"""

import os
import re
import sqlite3
import pathlib
from collections import Counter
from typing import List, Dict, Tuple, Any

class OCRKnowledgeBaseBuilder:
    def __init__(self, source_dir: str, db_path: str = "src/data/ocr_knowledge_base.db"):
        self.source_dir = pathlib.Path(source_dir)
        self.db_path = pathlib.Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("DROP TABLE IF EXISTS words")
            self.conn.execute("DROP TABLE IF EXISTS phrases")
            self.conn.execute("DROP TABLE IF EXISTS terms")
            
            self.conn.execute("""
                CREATE TABLE words (
                    word TEXT PRIMARY KEY,
                    frequency INTEGER
                )
            """)
            self.conn.execute("""
                CREATE TABLE phrases (
                    phrase TEXT PRIMARY KEY,
                    ngram_len INTEGER,
                    frequency INTEGER,
                    context_window TEXT
                )
            """)
            self.conn.execute("""
                CREATE TABLE terms (
                    term TEXT PRIMARY KEY,
                    category TEXT,
                    frequency INTEGER
                )
            """)

    def clean_text(self, text: str) -> str:
        text = re.sub(r'[\u064B-\u0652]', '', text) # Remove diacritics
        text = re.sub(r'[^\w\s]', ' ', text) # Remove punctuation
        return re.sub(r'\s+', ' ', text).strip()

    def extract_ngrams(self, words: List[str], n: int) -> List[str]:
        return [" ".join(words[i:i+n]) for i in range(len(words) - n + 1)]

    def process_files(self) -> Dict[str, Any]:
        word_counter = Counter()
        phrase_counter = Counter()
        phrase_contexts = {}
        term_counter = Counter()
        
        txt_files = list(self.source_dir.glob("*.txt"))
        print(f"[INFO] Found {len(txt_files)} TXT files in source directory.")
        
        for file_path in txt_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                print(f"[Warn] Could not read {file_path.name}: {e}")
                continue
                
            lines = content.splitlines()
            for line in lines:
                cleaned_line = self.clean_text(line)
                words = cleaned_line.split()
                if not words:
                    continue
                
                # 1. Word frequency
                word_counter.update(words)
                
                # 2. Phrases (2, 3, 4-grams)
                for n in [2, 3, 4]:
                    ngrams = self.extract_ngrams(words, n)
                    for ng in ngrams:
                        phrase_counter[ng] += 1
                        if ng not in phrase_contexts:
                            phrase_contexts[ng] = line[:120] # Store context window
                            
                # 5. Subject terminology & Named Entities heuristic (capitalized or scientific terms)
                for w in words:
                    if len(w) > 4 and (w.startswith("ال") or w.istitle() or any(term in w for term in ["فيزياء", "كيمياء", "تاريخ", "جغرافيا", "رياضيات", "درجة", "معادلة"])):
                        term_counter[w] += 1

        print("[INFO] Inserting data into Knowledge Base DB...")
        with self.conn:
            # Insert words
            self.conn.executemany(
                "INSERT OR REPLACE INTO words (word, frequency) VALUES (?, ?)",
                [(w, freq) for w, freq in word_counter.items() if freq > 1]
            )
            
            # Insert phrases
            phrase_data = [
                (phrase, len(phrase.split()), freq, phrase_contexts.get(phrase, ""))
                for phrase, freq in phrase_counter.items() if freq > 1
            ]
            self.conn.executemany(
                "INSERT OR REPLACE INTO phrases (phrase, ngram_len, frequency, context_window) VALUES (?, ?, ?, ?)",
                phrase_data
            )
            
            # Insert terms
            term_data = [
                (term, "educational_term", freq)
                for term, freq in term_counter.items() if freq > 1
            ]
            self.conn.executemany(
                "INSERT OR REPLACE INTO terms (term, category, frequency) VALUES (?, ?, ?)",
                term_data
            )

        db_size_mb = round(self.db_path.stat().st_size / (1024 * 1024), 2)
        
        report = {
            "total_unique_words": len(word_counter),
            "total_phrases": len(phrase_counter),
            "total_subject_terms": len(term_counter),
            "total_named_entities": len([t for t in term_counter if t.istitle()]),
            "frequency_statistics": {
                "max_word_freq": word_counter.most_common(1)[0] if word_counter else ("", 0),
                "max_phrase_freq": phrase_counter.most_common(1)[0] if phrase_counter else ("", 0)
            },
            "database_size_mb": db_size_mb,
            "indexing_method": "SQLite3 B-Tree Indexing on Primary Keys (word, phrase, term)"
        }
        
        return report


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        
    source = r"C:\Users\Mahmoud\Desktop\New folder"
    builder = OCRKnowledgeBaseBuilder(source)
    stats = builder.process_files()
    
    print("\n" + "="*50)
    print(" 🧠 OCR KNOWLEDGE BASE GENERATION REPORT")
    print("="*50)
    print(f"• Total Unique Words   : {stats['total_unique_words']:,}")
    print(f"• Total Phrases        : {stats['total_phrases']:,}")
    print(f"• Total Subject Terms  : {stats['total_subject_terms']:,}")
    print(f"• Total Named Entities : {stats['total_named_entities']:,}")
    print(f"• Database Size        : {stats['database_size_mb']} MB")
    print(f"• Indexing Method      : {stats['indexing_method']}")
    print("="*50)
    print("✅ Knowledge Base built successfully. Ready for decision support.")