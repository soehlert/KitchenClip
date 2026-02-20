from urllib.parse import urlparse
from typing import Type, List, Optional
from .base import BaseParser
from .scrapers_parser import ScrapersParser

class ParserRegistry:
    """
    Registry for custom recipe parsers.
    Checks for domain-specific parsers and falls back to ScrapersParser.
    """
    
    _parsers: List[Type[BaseParser]] = []

    @classmethod
    def register(cls, parser_class: Type[BaseParser]):
        """Register a new custom parser class."""
        if parser_class not in cls._parsers:
            cls._parsers.append(parser_class)
        return parser_class

    @classmethod
    def get_parser(cls, url: str) -> BaseParser:
        """
        Factory method to return the best parser for the given URL.
        """
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        for parser_class in cls._parsers:
            # Check if parser has a list of supported domains
            supported_domains = getattr(parser_class, "SUPPORTED_DOMAINS", [])
            if domain in supported_domains:
                return parser_class(url)

        # Fallback to the general scraper
        return ScrapersParser(url)

# Helper decorator for easy registration
def register_parser(cls):
    return ParserRegistry.register(cls)
