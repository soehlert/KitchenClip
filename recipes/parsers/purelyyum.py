from .base import BaseParser
from .registry import register_parser


@register_parser
class PurelyYumParser(BaseParser):
    """
    Parser for purelyyumrecipes.com.
    """
    SUPPORTED_DOMAINS = ["purelyyumrecipes.com"]
