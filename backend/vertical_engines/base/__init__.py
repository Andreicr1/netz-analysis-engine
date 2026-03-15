"""Base interfaces for vertical engines.

All vertical engines must implement these abstract classes to ensure
a consistent API surface for the ProfileLoader and route layer.
"""

from vertical_engines.base.base_analyzer import BaseAnalyzer
from vertical_engines.base.base_critic import BaseCritic
from vertical_engines.base.base_extractor import BaseExtractor

__all__ = ["BaseAnalyzer", "BaseCritic", "BaseExtractor"]
