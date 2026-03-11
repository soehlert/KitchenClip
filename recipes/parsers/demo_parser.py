from .base import BaseParser
from .registry import register_parser


@register_parser
class DemoParser(BaseParser):
    """
    A demo parser for example.com to demonstrate modularity.
    """
    SUPPORTED_DOMAINS = ["example.com"]

    @property
    def title(self) -> str:
        return "Custom Scraped Recipe from Example.com"

    @property
    def ingredients(self) -> list[str]:
        return [
            "1.5 cups flour",
            "0.5 cup sugar",
            "16 ounces milk",
            "4 ounces milk"
        ]

    @property
    def instructions(self) -> str:
        return "1. Mix everything.\n2. Bake at 350F."

    @property
    def description(self) -> str:
        return "This is a demonstration of the custom parser system."
