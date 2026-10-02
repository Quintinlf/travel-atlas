"""Turn coverage gaps into sourced, reviewable knowledge claims.

The Atlas schema was always built for an encyclopedia; what it lacked was content.
This package closes that loop:

    pins → areas → coverage gaps → source text → drafted claims → your review

Every stage is resumable and every claim carries the source record it came from, so
nothing enters the Atlas as an unattributed assertion. Drafts are written with
``review_status='draft'`` and are deliberately invisible to coverage scoring until a
human approves them — the pipeline proposes, it does not decide.
"""

from .areas import provision_areas
from .gaps import Gap, build_worklist
from .pipeline import IngestResult, run_ingest

__all__ = [
    "Gap",
    "IngestResult",
    "build_worklist",
    "provision_areas",
    "run_ingest",
]
