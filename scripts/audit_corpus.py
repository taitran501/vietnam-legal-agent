"""Audit the legal manifest, source hashes, amendment chain, and rule pack."""

from __future__ import annotations

import json
import sys

try:
    from scripts.canonical_corpus import corpus_readiness_audit
except ModuleNotFoundError:  # Direct ``python scripts/audit_corpus.py`` execution.
    from canonical_corpus import corpus_readiness_audit


def main() -> int:
    audit = corpus_readiness_audit()
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["ready_for_promotion"] else 2


if __name__ == "__main__":
    sys.exit(main())
