"""Re-export shim — canonical implementation lives in ``eolex.eo_decomposer``."""

from eolex.eo_decomposer import (  # noqa: F401
    ACCUSATIVE_N,
    CONNECTING_VOWELS,
    KIND_COMPOUND,
    KIND_FUNCTION_WORD,
    KIND_SINGLE_ROOT,
    KIND_UNRESOLVED,
    NOMINAL_END,
    PROD_FLOOR_FOR_TAIL,
    SOLID_TIERS,
    TIER_CORE,
    TIER_EXTENDED,
    TIER_RANK,
    TIER_TAIL,
    VERB_END,
    ContentRoot,
    Decomposition,
    Decomposer,
    strip_flexion,
)
