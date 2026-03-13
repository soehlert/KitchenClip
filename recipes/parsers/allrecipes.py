from .base import BaseParser
from .registry import register_parser


@register_parser
class AllrecipesParser(BaseParser):
    """
    Parser for allrecipes.com.
    """
    SUPPORTED_DOMAINS = ["allrecipes.com"]
