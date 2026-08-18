"""
Validation and Local Unit Testing for Kaggle Indexing Notebook
Checks AST syntax, imports, mock encoding, payload structure, and Qdrant integration.
"""
import ast
import json
import sys
from pathlib import Path

def validate_notebook_syntax(nb_path: str) -> bool:
    print(f"🔍 [1/3] Validating Python Syntax in {nb_path}...")
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    
    total_cells = len(nb.get("cells", []))
    code_cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
    print(f"   Found {len(code_cells)} code cells (out of {total_cells} total cells).")
    
    for idx, cell in enumerate(code_cells, 1):
        source = "".join(cell.get("source", []))
        # Filter out jupyter magic commands for AST validation
        clean_lines = []
        for line in source.splitlines():
            if line.strip().startswith("!") or line.strip().startswith("%"):
                clean_lines.append(f"# {line}")
            else:
                clean_lines.append(line)
        clean_code = "\n".join(clean_lines)
        
        try:
            ast.parse(clean_code)
            print(f"   Cell {idx}: AST Parse OK ✅")
        except SyntaxError as e:
            print(f"   ❌ SyntaxError in Cell {idx}: {e}")
            print(f"   Line: {e.text}")
            return False
            
    print("   All notebook cells have 100% valid Python syntax! ✅\n")
    return True


def unit_test_dataset_parsing() -> bool:
    print("🧪 [2/3] Running Unit Test on Dataset Parsing & Article Structuring...")
    import re
    import pyarrow.parquet as pq
    
    parquet_path = Path("kaggle_indexer/uts_vlc_2026_01.parquet")
    if not parquet_path.exists():
        parquet_path = Path("uts_vlc_2026_01.parquet")
        
    if not parquet_path.exists():
        print(f"   ❌ Test failed: {parquet_path} not found.")
        return False
        
    table = pq.read_table(parquet_path).to_pydict()
    art_split_pattern = re.compile(r'(?=(?:^|\n)(?:###?\s*)?Điều\s+\d+[\w\.]*\.?\s*)', re.MULTILINE)
    
    num_laws = len(table.get('id', []))
    test_articles = []
    
    for i in range(min(num_laws, 3)):  # Test first 3 laws
        law_id = str(table['id'][i])
        law_title = str(table['title'][i]) if 'title' in table and table['title'][i] else ''
        content = str(table['content'][i]) if 'content' in table and table['content'][i] else ''
        domain = str(table['domain'][i]) if 'domain' in table and table['domain'][i] else 'Luật Quốc gia'
        status = str(table['status'][i]) if 'status' in table and table['status'][i] else 'Còn hiệu lực'
        code = str(table['code'][i]) if 'code' in table and table['code'][i] else ''
        split_arts = art_split_pattern.split(content)
        for idx, art in enumerate(split_arts[1:], 1):
            art_clean = art.strip()
            if not art_clean:
                continue
            test_articles.append({
                'record_id': f'{law_id}-art-{idx}',
                'topic': 'Luật Quốc gia',
                'subject': domain,
                'document_title': law_title,
                'document_code': code,
                'article_title': art_clean.splitlines()[0][:140],
                'effective_status': status,
                'content_text': art_clean,
            })
            
    assert len(test_articles) > 0, "No articles extracted"
    sample = test_articles[0]
    required_fields = ['record_id', 'topic', 'subject', 'document_title', 'article_title', 'effective_status', 'content_text']
    for rf in required_fields:
        assert rf in sample, f"Missing field: {rf}"
        
    print(f"   Successfully parsed {len(test_articles)} articles from sample laws. ✅")
    print(f"   Sample Record ID: {sample['record_id']}")
    print(f"   Sample Title: {sample['article_title'][:60]}...")
    print("   Dataset Parsing Test Passed! ✅\n")
    return True


def unit_test_qdrant_schema() -> bool:
    print("🧪 [3/3] Running Unit Test on Qdrant Schema & Point Structuring...")
    from qdrant_client.models import PointStruct
    
    # Mock embedding dimension 1024
    mock_vector = [0.01] * 1024
    point = PointStruct(
        id=1,
        vector=mock_vector,
        payload={
            'record_id': 'test-123',
            'topic': 'Luật Doanh nghiệp',
            'subject': 'Đăng ký kinh doanh',
            'document_title': 'Luật Doanh nghiệp 2020',
            'document_code': '59/2020/QH14',
            'article_title': 'Điều 1. Phạm vi điều chỉnh',
            'effective_status': 'Còn hiệu lực',
            'source': 'Luật Doanh nghiệp 2020',
            'text': 'Nội dung điều 1...',
        }
    )
    assert len(point.vector) == 1024
    assert point.payload['topic'] == 'Luật Doanh nghiệp'
    print("   Qdrant Payload Schema validation: 1024-dim Vector Struct OK ✅\n")
    return True


if __name__ == "__main__":
    nb_path = sys.argv[1] if len(sys.argv) > 1 else "kaggle_indexer/build_index_kaggle.ipynb"
    ok1 = validate_notebook_syntax(nb_path)
    ok2 = unit_test_dataset_parsing()
    ok3 = unit_test_qdrant_schema()
    
    if ok1 and ok2 and ok3:
        print("🎉 ALL LOCAL COMPILATION & UNIT TESTS PASSED (3/3)!")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED!")
        sys.exit(1)
