# Official law delta preview

This preview demonstrates a narrow, provenance-first update path for a newly
published national law without replacing or overriding the selected multi-domain
legal corpus. It currently
contains the official portal metadata and the effective-date clause for
`08/2026/QH16`.

## Refresh and validate

Run the ingestion job outside the request path:

```powershell
.venv_acceptance\Scripts\python.exe -m scripts.ingest_official_delta --sync
.venv_acceptance\Scripts\python.exe -m scripts.ingest_official_delta --check
```

The job only accepts the official government hosts
`vanban.chinhphu.vn` and `datafiles.chinhphu.vn`, verifies the exact instrument
number, stores the PDF locally, and records its SHA-256 and provenance in
`data/corpus/official_delta/manifest.json`. It does not crawl or download data
while the API is serving a request.

The checked-in snapshot was retrieved from the [official law record](https://vanban.chinhphu.vn/?classid=1&docid=218101&pageid=27160&typegroupid=3)
and its [signed PDF](https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/5/08-qh.signed.pdf).

## Run the preview locally

```powershell
$env:CORPUS_RUNTIME_MODE = "preview"
$env:ENABLE_OFFICIAL_DELTA_RETRIEVAL = "true"
$env:OFFICIAL_DELTA_MANIFEST_PATH = "data/corpus/official_delta/manifest.json"
```

Only queries that name the exact instrument and ask for supported metadata (for
example, its issue or effective date) or the indexed effective-date clause are
served by this delta. An unrelated instrument, a broad year query, or a
substantive question not covered by the snapshot returns a safe-stop instead of
borrowing a nearby provision from an unrelated source.

The production configuration validator rejects this flag. The delta is a
preview experiment, not a complete legal-text mirror; the current PDF is
image-based and the manifest explicitly records that only the effective clause
is text-indexed. A future refresh should repeat the same exact-instrument and
hash checks before being considered for a separate corpus release.

Hugging Face legal datasets remain useful for offline exploration and retrieval
experiments, but they are not treated as the authoritative production source
for current-law updates.
