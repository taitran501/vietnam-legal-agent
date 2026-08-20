# Universal corpus build

The universal legal retriever is an optional, generated SQLite artifact. It is
not committed to Git because the current snapshot is approximately 556 MB.
Every input is nevertheless content-locked in
`data/universal_corpus_manifest.json`.

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
upstream file changes, the build fails; update the lock only after reviewing
the new source snapshot and its legal/provenance implications.

To verify an existing artifact without rebuilding it:

```powershell
python -m scripts.build_universal_index --verify-only
```

Use `--rebuild` only when intentionally regenerating the ignored SQLite
artifact. The runtime resolves the database from the repository root or the
`UNIVERSAL_CORPUS_DB_PATH` environment variable, so service working directories
cannot silently disable universal retrieval.

The generated corpus is not part of the approved production manifest. Runtime
augmentation is therefore disabled by default and production configuration
rejects `ENABLE_UNIVERSAL_RETRIEVAL=true`. Use it only in an explicitly
isolated preview after setting that flag and documenting the preview source;
the content lock proves reproducibility, not legal approval.
