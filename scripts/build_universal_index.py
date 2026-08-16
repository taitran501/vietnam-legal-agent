import os
import re
import urllib.request
import sqlite3
import pyarrow.parquet as pq

CORPUS_DIR = os.path.join(os.getcwd(), "data", "corpus", "universal_legal")
os.makedirs(CORPUS_DIR, exist_ok=True)

DB_PATH = os.path.join(CORPUS_DIR, "universal_legal.db")

print("=== STEP 1: DOWNLOADING PHAPDIEN (67,000+ ARTICLES) & UTS_VLC ===")

HF_BASE_URL = "https://huggingface.co/datasets/tmquan/phapdien-moj-gov-vn/resolve/main"
article_files = [f"articles-{i:05d}-of-00007.parquet" for i in range(7)]

downloaded_parquets = []
for fname in article_files:
    local_path = os.path.join(CORPUS_DIR, fname)
    if not os.path.exists(local_path):
        url = f"{HF_BASE_URL}/{fname}"
        print(f"Downloading {fname}...")
        urllib.request.urlretrieve(url, local_path)
    downloaded_parquets.append(local_path)

print(f"Downloaded all {len(downloaded_parquets)} article parquets.")

# Connect SQLite
print("\n=== STEP 2: BUILDING SQLITE FTS5 SEARCH INDEX ===")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS legal_articles;")
cursor.execute("DROP TABLE IF EXISTS legal_articles_fts;")

cursor.execute("""
CREATE TABLE legal_articles (
    id TEXT PRIMARY KEY,
    topic TEXT,
    subject TEXT,
    article_title TEXT,
    chapter_title TEXT,
    source_note TEXT,
    source_url TEXT,
    content_text TEXT,
    char_len INTEGER
);
""")

cursor.execute("""
CREATE VIRTUAL TABLE legal_articles_fts USING fts5(
    id,
    topic,
    subject,
    article_title,
    chapter_title,
    source_note,
    content_text,
    tokenize='unicode61 remove_diacritics 0'
);
""")

total_inserted = 0
for ppath in downloaded_parquets:
    table = pq.read_table(ppath)
    pydict = table.to_pydict()
    num_rows = table.num_rows
    
    rows_to_insert = []
    fts_rows = []
    
    for i in range(num_rows):
        rec_id = pydict["record_id"][i]
        topic = pydict["topic_title_vi"][i] or ""
        subject = pydict["subject_title_vi"][i] or ""
        art_title = pydict["article_title"][i] or ""
        chap_title = pydict["chapter_title"][i] or ""
        src_note = pydict["source_note_text"][i] or ""
        
        # Get source url
        src_url = ""
        source_links = pydict["source_links"][i]
        if source_links and len(source_links) > 0 and isinstance(source_links[0], dict):
            src_url = source_links[0].get("href", "")
        if not src_url:
            src_url = pydict["source_url"][i] or ""
            
        content = pydict["content_text"][i] or ""
        char_len = pydict["content_char_len"][i] or len(content)
        
        rows_to_insert.append((rec_id, topic, subject, art_title, chap_title, src_note, src_url, content, char_len))
        fts_rows.append((rec_id, topic, subject, art_title, chap_title, src_note, content))
        
    cursor.executemany("INSERT OR REPLACE INTO legal_articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);", rows_to_insert)
    cursor.executemany("INSERT INTO legal_articles_fts VALUES (?, ?, ?, ?, ?, ?, ?);", fts_rows)
    total_inserted += num_rows
    print(f"Indexed {num_rows} articles from {os.path.basename(ppath)} (Total: {total_inserted:,})")

conn.commit()

# Also index UTS_VLC full laws
uts_parquet = os.path.join(os.getcwd(), "data", "raw_hf", "uts_vlc", "2026_01-00000-of-00001.parquet")
if os.path.exists(uts_parquet):
    print("\n=== STEP 3: INDEXING UTS_VLC NATIONAL CODES (318 LAWS) ===")
    vlc_table = pq.read_table(uts_parquet)
    vlc_dict = vlc_table.to_pydict()
    
    art_split_pattern = re.compile(r"(?=(?:^|\n)(?:###?\s*)?Điều\s+\d+[\w\.]*\.?\s*)", re.MULTILINE)
    uts_rows = []
    uts_fts = []
    
    for i in range(vlc_table.num_rows):
        law_id = vlc_dict["id"][i]
        law_title = vlc_dict["title"][i]
        content = vlc_dict["content"][i]
        
        articles = art_split_pattern.split(content)
        for idx, art in enumerate(articles[1:], 1):
            art_clean = art.strip()
            if not art_clean:
                continue
            first_line = art_clean.splitlines()[0]
            rec_id = f"{law_id}-art-{idx}"
            
            uts_rows.append((rec_id, "Luật Quốc gia", law_title, first_line[:120], "", f"Căn cứ {law_title}", "https://vbpl.vn", art_clean, len(art_clean)))
            uts_fts.append((rec_id, "Luật Quốc gia", law_title, first_line[:120], "", f"Căn cứ {law_title}", art_clean))
            
    cursor.executemany("INSERT OR REPLACE INTO legal_articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);", uts_rows)
    cursor.executemany("INSERT INTO legal_articles_fts VALUES (?, ?, ?, ?, ?, ?, ?);", uts_fts)
    conn.commit()
    print(f"Indexed {len(uts_rows):,} additional articles from 318 National Laws.")

cursor.execute("SELECT COUNT(*) FROM legal_articles;")
final_count = cursor.fetchone()[0]
print(f"\n✅ UNIVERSAL DATABASE BUILD COMPLETED! Total Indexed Articles: {final_count:,}")
conn.close()
