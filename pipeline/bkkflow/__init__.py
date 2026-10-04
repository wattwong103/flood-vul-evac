"""BKK/FLOW research pipeline.

The package is deliberately explicit about what is real. Every stage writes an
immutable artefact, records the source version it consumed, and refuses to
promote a run beyond ``demonstration`` until a validation gate says otherwise.

Stage order follows the PFLOW contract retained in the project plan:

    P0 sources -> P1 people -> P2 activities -> P3 trips -> P4 trajectories
    -> P5 aggregates -> F1 flood -> F2 network impact -> E1 cohort
    -> E2 evacuation -> V1 validation -> U1 publish
"""

__version__ = "0.1.0"

STAGE_ORDER = (
    "sources",
    "population",
    "activities",
    "trips",
    "trajectories",
    "aggregates",
    "flood",
    "network_impact",
    "cohort",
    "evacuation",
    "validate",
    "publish",
)
