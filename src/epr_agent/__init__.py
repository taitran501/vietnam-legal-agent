"""Bounded agentic workflow for the EPR legal assistant.

The legacy ``backend`` package remains available while this package becomes the
new application boundary.  The workflow is deliberately bounded: it can choose
only a small set of known actions and it must terminate after a fixed number of
retrieval and repair steps.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
