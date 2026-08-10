from scripts.build_index import normalise_articles
from scripts.structural_chunking import structural_chunk_articles, structural_chunks


def test_structural_chunks_keep_clause_point_and_source_offsets():
    text = "Khoản 1. Nghĩa vụ đầu tiên.\n\nĐiểm a. Chuẩn bị hồ sơ.\n\nĐiểm b. Báo cáo kết quả."
    chunks = structural_chunks(text, max_chars=200)
    assert len(chunks) == 3
    assert chunks[0].clause == "Khoản 1"
    assert chunks[1].point == "Điểm a"
    assert text[chunks[2].source_start : chunks[2].source_end].startswith("Điểm b")


def test_structural_chunks_recognize_numbered_legal_clauses():
    text = "1. Nghĩa vụ thứ nhất.\na) Hồ sơ A.\n2. Nghĩa vụ thứ hai.\na) Hồ sơ B."
    chunks = structural_chunks(text, max_chars=200)
    assert [chunk.clause for chunk in chunks] == ["1.", "1.", "2.", "2."]
    assert [chunk.point for chunk in chunks] == ["", "a)", "", "a)"]


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
    assert articles[0]["Original_Text"] == "Khoản 1. Nội dung."


def test_index_normalization_retains_structure_markers_for_candidate_chunking():
    normalized, _ = normalise_articles(
        [
            {
                "Điều": "Điều 77",
                "Text": "1. Nghĩa vụ bị xuống\ndòng trong PDF.\n2. Nghĩa vụ tiếp theo.\na) Hồ sơ.",
            }
        ]
    )

    chunks, _, _ = structural_chunk_articles(normalized, ["Tóm tắt."])

    assert [chunk["Khoan"] for chunk in chunks] == ["1.", "2.", "2."]
    assert chunks[2]["Diem"] == "a)"
    assert "_Structural_Text" not in chunks[0]
