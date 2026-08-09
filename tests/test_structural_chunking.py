from scripts.structural_chunking import structural_chunk_articles, structural_chunks


def test_structural_chunks_keep_clause_point_and_source_offsets():
    text = "Khoản 1. Nghĩa vụ đầu tiên.\n\nĐiểm a. Chuẩn bị hồ sơ.\n\nĐiểm b. Báo cáo kết quả."
    chunks = structural_chunks(text, max_chars=200)
    assert len(chunks) == 3
    assert chunks[0].clause == "Khoản 1"
    assert chunks[1].point == "Điểm a"
    assert text[chunks[2].source_start : chunks[2].source_end].startswith("Điểm b")


def test_structural_article_chunks_preserve_citation_hierarchy():
    articles, summaries, stats = structural_chunk_articles(
        [{"Điều": "Điều 77", "Chương": "Chương VI", "Mục": "Mục 1", "Text": "Khoản 1. Nội dung."}],
        ["Tóm tắt."],
    )
    assert stats["strategy"] == "legal_structure_v1"
    assert summaries == ["Tóm tắt."]
    assert articles[0]["Parent_Dieu"] == "Điều 77"
    assert "Điều 77" in articles[0]["Hierarchy"]
    assert articles[0]["Source_End"] > articles[0]["Source_Start"]
