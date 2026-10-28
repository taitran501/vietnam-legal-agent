# Corpus attribution and licenses

The root [MIT license](../../LICENSE) covers repository code. It does not replace terms attached to third-party corpus inputs or official legal texts. The manifests under `data/` remain the machine-readable source of pinned revisions, hashes, and source URLs.

| Input | License or source note | Attribution and verification |
| --- | --- | --- |
| `tmquan/phapdien-moj-gov-vn` (pinned in `data/universal_corpus_manifest.json`) | CC BY 4.0, as declared by the dataset | Attribute the dataset to its publisher, link to the [dataset page](https://huggingface.co/datasets/tmquan/phapdien-moj-gov-vn) and [official Pháp điển portal](https://phapdien.moj.gov.vn/), identify the pinned revision, and preserve changes/transformations where applicable. |
| `undertheseanlp/UTS_VLC` 2026 split (pinned in `data/universal_corpus_manifest.json`) | MIT, as declared by the dataset | Attribute Underthesea NLP and link to the [dataset page](https://huggingface.co/datasets/undertheseanlp/UTS_VLC) and the official legal database [vbpl.vn](https://vbpl.vn/). The input is a curated dataset; verify legal effect against official source text before relying on it. |
| Official-law delta in `data/corpus/official_delta/manifest.json` | The manifest describes an official government legal-document source and instructs users to retain attribution and the source URL; it does not assert a separate open-source license. | Preserve each instrument's official URL, source hash, retrieval time, and coverage metadata from the manifest. Do not imply that repository MIT terms apply to the legal text. |

For reuse, check the license and provenance at the pinned dataset revision and the terms published by the source. A source label or public availability is not a substitute for retaining attribution or verifying the underlying legal text. The skill package contains no corpus data.
