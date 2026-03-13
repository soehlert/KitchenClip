from .base import BaseParser
from .registry import register_parser


@register_parser
class LessWithLaurParser(BaseParser):
    """
    Parser for lesswithlaur.com.
    """
    SUPPORTED_DOMAINS = ["lesswithlaur.com"]
