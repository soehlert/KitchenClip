from .base import BaseParser
from .registry import register_parser


@register_parser
class HouseOfNashEatsParser(BaseParser):
    """
    Parser for houseofnasheats.com.
    """
    SUPPORTED_DOMAINS = ["houseofnasheats.com"]
