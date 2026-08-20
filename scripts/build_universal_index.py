import argparse
import hashlib
import json
import os
import re
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data" / "universal_corpus_manifest.json"
LOCK = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
CORPUS_DIR = ROOT / "data" / "corpus" / "universal_legal"
DB_PATH = CORPUS_DIR / "universal_legal.db"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_input(spec: dict[str, object]) -> Path:
    path = ROOT / str(spec["path"])
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing universal corpus input: {path}. "
            "Run `python -m scripts.build_universal_index --download`."
        )
    if path.stat().st_size != int(spec["size_bytes"]):
        raise RuntimeError(f"universal_corpus_size_mismatch:{spec['path']}")
    if _sha256(path) != str(spec["sha256"]).lower():
        raise RuntimeError(f"universal_corpus_sha256_mismatch:{spec['path']}")
    return path


def _ensure_inputs(download: bool) -> list[Path]:
    paths: list[Path] = []
    for raw_spec in LOCK["inputs"]:
        spec = dict(raw_spec)
        path = ROOT / str(spec["path"])
        if not path.is_file() and download:
            uri = str(spec.get("download_uri") or "")
            if not uri:
                raise RuntimeError(f"universal_corpus_input_has_no_download_uri:{spec['path']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".download")
            try:
                print(f"Downloading {path.name}...")
                urllib.request.urlretrieve(uri, temporary)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        paths.append(_verify_input(spec))
    return paths


def _verify_database() -> int:
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Missing universal corpus database: {DB_PATH}")
    connection = sqlite3.connect(f"file:{DB_PATH.resolve().as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        expected_tables = set(LOCK["output"]["expected_tables"])
        if not expected_tables.issubset(tables):
            raise RuntimeError("universal_corpus_database_schema_mismatch")
        rows = int(connection.execute("SELECT COUNT(*) FROM legal_articles").fetchone()[0])
        fts_rows = int(connection.execute("SELECT COUNT(*) FROM legal_articles_fts").fetchone()[0])
        expected_rows = int(LOCK["output"]["expected_rows"])
        if rows != expected_rows or fts_rows != expected_rows:
            raise RuntimeError("universal_corpus_database_row_count_mismatch")
        return rows
    finally:
        connection.close()


def _build_database(input_paths: list[Path]) -> int:
    """Build the generated SQLite artifact and replace it only after validation."""
    import pyarrow.parquet as pq

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    temporary_db = DB_PATH.with_name(DB_PATH.name + ".building")
    temporary_db.unlink(missing_ok=True)
    downloaded_parquets = [str(path) for path in input_paths[:-1]]
    print("=== BUILDING CONTENT-LOCKED UNIVERSAL LEGAL INDEX ===")

    print("\n=== STEP 2: BUILDING SQLITE FTS5 SEARCH INDEX ===")
    conn = sqlite3.connect(temporary_db)
    try:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS legal_articles;")
        cursor.execute("DROP TABLE IF EXISTS legal_articles_fts;")

        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
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
            """
        )

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

                src_url = ""
                source_links = pydict["source_links"][i]
                if source_links and len(source_links) > 0 and isinstance(source_links[0], dict):
                    src_url = source_links[0].get("href", "")
                if not src_url:
                    src_url = pydict["source_url"][i] or ""

                content = pydict["content_text"][i] or ""
                char_len = pydict["content_char_len"][i] or len(content)
                rows_to_insert.append(
                    (rec_id, topic, subject, art_title, chap_title, src_note, src_url, content, char_len)
                )
                fts_rows.append((rec_id, topic, subject, art_title, chap_title, src_note, content))

            cursor.executemany("INSERT OR REPLACE INTO legal_articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);", rows_to_insert)
            cursor.executemany("INSERT INTO legal_articles_fts VALUES (?, ?, ?, ?, ?, ?, ?);", fts_rows)
            total_inserted += num_rows
            print(f"Indexed {num_rows} articles from {os.path.basename(ppath)} (Total: {total_inserted:,})")

        # Also index UTS_VLC full laws.
        uts_parquet = str(input_paths[-1])
        print("\n=== STEP 3: INDEXING UTS_VLC NATIONAL CODES (318 LAWS) ===")
        vlc_table = pq.read_table(uts_parquet)
        vlc_dict = vlc_table.to_pydict()
        art_split_pattern = re.compile(
            r"(?=(?:^|\n)(?:###?\s*)?Điều\s+\d+[\w\.]*\.?\s*)", re.MULTILINE
        )
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
                uts_rows.append(
                    (
                        rec_id,
                        "Luật Quốc gia",
                        law_title,
                        first_line[:120],
                        "",
                        f"Căn cứ {law_title}",
                        "https://vbpl.vn",
                        art_clean,
                        len(art_clean),
                    )
                )
                uts_fts.append(
                    (rec_id, "Luật Quốc gia", law_title, first_line[:120], "", f"Căn cứ {law_title}", art_clean)
                )

        cursor.executemany("INSERT OR REPLACE INTO legal_articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);", uts_rows)
        cursor.executemany("INSERT INTO legal_articles_fts VALUES (?, ?, ?, ?, ?, ?, ?);", uts_fts)
        conn.commit()
        print(f"Indexed {len(uts_rows):,} additional articles from 318 National Laws.")

        final_count = int(cursor.execute("SELECT COUNT(*) FROM legal_articles;").fetchone()[0])
        expected_count = int(LOCK["output"]["expected_rows"])
        if final_count != expected_count:
            raise RuntimeError(f"universal_corpus_build_row_count_mismatch:{final_count}:{expected_count}")
        fts_count = int(cursor.execute("SELECT COUNT(*) FROM legal_articles_fts;").fetchone()[0])
        if fts_count != expected_count:
            raise RuntimeError(f"universal_corpus_build_fts_row_count_mismatch:{fts_count}:{expected_count}")
    except Exception:
        conn.rollback()
        temporary_db.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

    temporary_db.replace(DB_PATH)
    print(f"\nUNIVERSAL DATABASE BUILD COMPLETED total_rows={final_count:,} database={DB_PATH}")
    return final_count


def main(argv: list[str] | None = None) -> int:
    """Build or verify the content-locked universal Vietnamese legal index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download missing content-locked inputs")
    parser.add_argument("--rebuild", action="store_true", help="Recreate the generated SQLite database")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify inputs and an existing database without rebuilding",
    )
    args = parser.parse_args(argv)
    input_paths = _ensure_inputs(download=args.download)
    if args.verify_only:
        print(f"universal_corpus_verified rows={_verify_database()} database={DB_PATH}")
        return 0
    if DB_PATH.exists() and not args.rebuild:
        print(f"universal_corpus_reused rows={_verify_database()} database={DB_PATH}")
        return 0
    _build_database(input_paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
