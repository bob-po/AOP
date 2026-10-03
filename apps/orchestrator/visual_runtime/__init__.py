"""Visual Runtime — observation / projection layer over Execution Runtime.

Does not own Agent lifecycle or execution semantics. Graph + Timeline are
projections of the same Execution Event stream + runtime edges.
"""

from .events import (
    VISUAL_EVENT_TYPES,
    normalize_event,
    map_execution_event_type,
)
from .projector import (
    project_visual_graph,
    project_timeline,
    apply_event_to_graph,
)
from .history import (
    synthesize_from_collaboration,
    merge_task_scheduler_events,
)

__all__ = [
    "VISUAL_EVENT_TYPES",
    "normalize_event",
    "map_execution_event_type",
    "project_visual_graph",
    "project_timeline",
    "apply_event_to_graph",
    "synthesize_from_collaboration",
    "merge_task_scheduler_events",
]
