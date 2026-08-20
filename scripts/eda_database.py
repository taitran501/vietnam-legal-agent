"""
Comprehensive Exploratory Data Analysis (EDA) of the Vietnam Legal Vector Database (Qdrant)
"""
import base64
import binascii
import pickle
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np


def run_eda():
    db_sqlite = Path("qdrant_db/collection/vietnam_legal_collection_v1/storage.sqlite")
    if not db_sqlite.exists():
        print(f"Error: {db_sqlite} not found.")
        return
        
    db_size_mb = db_sqlite.stat().st_size / (1024 * 1024)
    
    print("="*70)
    print("📊 VIETNAM LEGAL KNOWLEDGE BASE - EXPLORATORY DATA ANALYSIS (EDA)")
    print("="*70)
    print(f"📁 Database Path: {db_sqlite.resolve()}")
    print(f"💾 Storage Size : {db_size_mb:.2f} MB")
    
    conn = sqlite3.connect(str(db_sqlite))
    cursor = conn.cursor()
    
    cursor.execute("SELECT count(*) FROM points;")
    total_records = cursor.fetchone()[0]
    print(f"📦 Total Vector Records: {total_records:,}")
    
    cursor.execute("SELECT point FROM points;")
    
    topics = Counter()
    subjects = Counter()
    documents = Counter()
    statuses = Counter()
    
    char_lengths = []
    word_lengths = []
    
    missing_fields = {
        'topic': 0,
        'subject': 0,
        'document_title': 0,
        'article_title': 0,
        'text': 0,
        'effective_status': 0
    }
    
    print("⏳ Scanning & aggregating 65,967 payload records...")
    invalid_records = 0
    for row in cursor:
        raw_point = row[0]
        payload = None
        try:
            point = pickle.loads(base64.b64decode(raw_point)) if isinstance(raw_point, str) else pickle.loads(raw_point)
            payload = point.payload or {}
        except (AttributeError, binascii.Error, EOFError, IndexError, pickle.PickleError, TypeError, ValueError):
            invalid_records += 1

        if payload is None:
            continue
            
        topic = payload.get('topic') or 'Chưa phân loại'
        subject = payload.get('subject') or 'Chưa phân loại'
        doc_title = payload.get('document_title') or 'Không rõ nguồn'
        status = payload.get('effective_status') or 'Không xác định'
        text = payload.get('text') or ''
        
        topics[topic] += 1
        subjects[subject] += 1
        documents[doc_title] += 1
        statuses[status] += 1
        
        char_len = len(text)
        word_len = len(text.split())
        char_lengths.append(char_len)
        word_lengths.append(word_len)
        
        for k in missing_fields:
            if not payload.get(k):
                missing_fields[k] += 1
                
    conn.close()
    if invalid_records:
        print(f"⚠️ Skipped {invalid_records:,} invalid payload records.")
    
    char_arr = np.array(char_lengths)
    word_arr = np.array(word_lengths)
    
    print("\n" + "-"*70)
    print("1. 📈 TEXT LENGTH & TOKEN STATISTICS")
    print("-"*70)
    print(f"• Character Length : Min: {char_arr.min():,} | Max: {char_arr.max():,} | Mean: {char_arr.mean():.1f} | Median: {np.median(char_arr):.1f} | Std: {char_arr.std():.1f}")
    print(f"• Percentiles (Chars): 25th: {np.percentile(char_arr, 25):.0f} | 50th: {np.percentile(char_arr, 50):.0f} | 75th: {np.percentile(char_arr, 75):.0f} | 95th: {np.percentile(char_arr, 95):.0f} | 99th: {np.percentile(char_arr, 99):.0f}")
    print(f"• Word Count       : Min: {word_arr.min():,} | Max: {word_arr.max():,} | Mean: {word_arr.mean():.1f} | Median: {np.median(word_arr):.1f}")
    print(f"• Total Words      : {word_arr.sum():,} words (~{int(word_arr.sum()*1.3):,} subword tokens)")
    
    print("\n" + "-"*70)
    print("2. 🏛️ TOP 15 LEGAL DOMAINS / TOPICS (Chủ đề Luật)")
    print("-"*70)
    for idx, (top, cnt) in enumerate(topics.most_common(15), 1):
        pct = (cnt / total_records) * 100
        print(f"  {idx:2d}. {top:<38} : {cnt:>6,} điều ({pct:>5.2f}%)")
        
    print(f"\n  👉 Tổng số Chủ đề lớn (Topics): {len(topics):,}")
    print(f"  👉 Tổng số Đề mục chi tiết (Subjects): {len(subjects):,}")
    print(f"  👉 Tổng số Văn bản quy phạm pháp luật (Documents): {len(documents):,}")
    
    print("\n" + "-"*70)
    print("3. 📜 TOP 10 VĂN BẢN QUY PHẠM PHÁP LUẬT CÓ NHIỀU ĐIỀU NHẤT")
    print("-"*70)
    for idx, (doc, cnt) in enumerate(documents.most_common(10), 1):
        clean_doc = doc.replace("\n", " ").strip()
        if len(clean_doc) > 60:
            clean_doc = clean_doc[:57] + "..."
        print(f"  {idx:2d}. {clean_doc:<60} : {cnt:>4,} điều")
        
    print("\n" + "-"*70)
    print("4. 📋 HIỆU LỰC & CHẤT LƯỢNG DỮ LIỆU (Data Completeness)")
    print("-"*70)
    print("• Trạng thái hiệu lực:")
    for stat, cnt in statuses.most_common():
        pct = (cnt / total_records) * 100
        print(f"    - {stat}: {cnt:,} ({pct:.2f}%)")
        
    print("\n• Tỷ lệ khuyết thiếu trường dữ liệu (Missing rate):")
    for k, v in missing_fields.items():
        pct = (v / total_records) * 100
        print(f"    - Trường `{k}`: {v} missing ({pct:.2f}%)")

if __name__ == "__main__":
    run_eda()
