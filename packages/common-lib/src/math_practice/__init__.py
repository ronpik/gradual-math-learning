"""math_practice: shared foundation for the adaptive math practice system.

Exposes the full public API of the adaptive-practice engine (spec v1):
configuration, domain models, difficulty scoring, ability tracking, item
selection, mastery tracking, and the orchestrating :class:`PracticeEngine`.
"""

from .ability import AbilityTracker
from .config import EngineConfig
from .difficulty import AdditionFixedDifficultyScorer, DifficultyScorer
from .engine import PracticeEngine, TrialResult
from .mastery import MasteryState, MasteryTracker
from .models import Exercise, build_curriculum
from .selection import SelectionPolicy
from .state import EngineState, ExerciseMastery

__version__ = "0.1.0"

__all__ = [
    "EngineConfig",
    "Exercise",
    "build_curriculum",
    "DifficultyScorer",
    "AdditionFixedDifficultyScorer",
    "AbilityTracker",
    "SelectionPolicy",
    "MasteryState",
    "MasteryTracker",
    "PracticeEngine",
    "TrialResult",
    "EngineState",
    "ExerciseMastery",
]
