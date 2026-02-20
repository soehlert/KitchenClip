from .registry import ParserRegistry, register_parser
from .scrapers_parser import ScrapersParser
from .demo_parser import DemoParser

__all__ = ["ParserRegistry", "register_parser", "ScrapersParser", "DemoParser"]
