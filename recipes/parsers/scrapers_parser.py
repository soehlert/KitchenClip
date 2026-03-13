import logging

from .base import BaseParser

logger = logging.getLogger(__name__)

class ScrapersParser(BaseParser):
    """
    Parser that uses the recipe-scrapers library or JSON-LD.
    Acts as a fallback for domains without custom parsers.
    Inherits all core logic from BaseParser.
    """
    pass
