from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class BaseParser(ABC):
    """
    Abstract base class for all recipe parsers.
    Any custom parser should inherit from this and implement the methods.
    """
    
    def __init__(self, url: str, html: Optional[str] = None):
        self.url = url
        self.html = html

    @property
    @abstractmethod
    def title(self) -> str:
        """Return the recipe title."""
        pass

    @property
    @abstractmethod
    def ingredients(self) -> List[str]:
        """Return a list of raw ingredient strings."""
        pass

    @property
    @abstractmethod
    def instructions(self) -> str:
        """Return the instructions as a single string."""
        pass

    @property
    def description(self) -> str:
        """Return a brief description of the recipe."""
        return ""

    @property
    def image_url(self) -> str:
        """Return the main recipe image URL."""
        return ""

    @property
    def prep_time(self) -> Optional[int]:
        """Return prep time in minutes."""
        return None

    @property
    def cook_time(self) -> Optional[int]:
        """Return cook time in minutes."""
        return None

    @property
    def total_time(self) -> Optional[int]:
        """Return total time in minutes."""
        return None

    @property
    def servings(self) -> Optional[str]:
        """Return servings/yield as a string."""
        return None
