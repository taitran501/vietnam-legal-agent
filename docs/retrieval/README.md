# Retrieval

The agent uses the content-locked, multi-domain corpus in
data/universal_corpus_manifest.json. Input files and the corpus build are
verified by SHA-256 hashes and the expected row count.

Build and verify the local SQLite search index with:

    python -m pip install -e ".[universal]"
    python -m scripts.build_universal_index --download --rebuild
    python -m scripts.build_universal_index --verify-only

The backend uses this corpus for ordinary legal questions across topics. Exact
instrument and article references are preserved through retrieval and citation
checks. Missing or irrelevant evidence returns a source-aware limitation.

The optional Qdrant adapter is disabled by default. It is not required to build,
run CI, or execute the live-agent evaluation. See
universal-corpus.md for input sources and lock details.
