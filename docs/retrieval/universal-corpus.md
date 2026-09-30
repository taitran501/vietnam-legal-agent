# Universal corpus build

The multi-domain legal retriever is the primary source for ordinary local
preview chat. Its generated SQLite artifact is not committed to Git because
the current snapshot is approximately 583 MB.
Every input is content-locked in `data/universal_corpus_manifest.json`.

The lock combines the Ministry of Justice codified-law snapshot with the
tracked UTS_VLC input. The public source attribution and license must be
preserved when redistributing the generated artifact.

## Build from a clean checkout

Install the optional builder dependency and download only the locked inputs:

```powershell
python -m pip install -e ".[universal]"
python -m scripts.build_universal_index --download
```

The builder verifies each input size and SHA-256 before indexing. If an
upstream file changes, the build fails; update the lock only after checking the
new source snapshot and its provenance implications.

To verify an existing artifact without rebuilding:

```powershell
python -m scripts.build_universal_index --verify-only
```

Use `--rebuild` only when intentionally regenerating the ignored SQLite
artifact. The runtime resolves the database from the repository root or the
`UNIVERSAL_CORPUS_DB_PATH` environment variable, so service working directories
cannot silently disable universal retrieval.

Docker images intentionally exclude generated `*.db` artifacts. Build and
verify the corpus on the host, then mount it read-only into the backend:

```powershell
python -m scripts.build_universal_index --verify-only
docker compose -f docker-compose.yml -f docker-compose.universal-preview.yml up -d --build
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

Readiness must report `retrieval_sources.universal_legal.status: ready`. If the
artifact is absent or invalid, legal chat is blocked with
`universal_corpus_unavailable`; it must not silently substitute the narrow
legacy index. The preview overlay sets `CORPUS_RUNTIME_MODE=preview`.

To use an artifact at another host path, set `UNIVERSAL_CORPUS_HOST_PATH` in
`.env`. The container path remains `/app/data/corpus/universal_legal/universal_legal.db`.

## Production usage

The generated corpus is not part of an approved production release. The local
preview uses it by default, while production configuration remains blocked
until a domain-neutral legal-review approval and release artifact exist. The
content lock establishes reproducibility, not legal approval.

The universal retriever serves all legal topics. The older Qdrant snapshot is
an optional supplement only when a query explicitly matches its narrow scope.
