import importlib
import pkgutil

from .demo_parser import DemoParser
from .registry import ParserRegistry, register_parser
from .scrapers_parser import ScrapersParser


# Automatically discover and register all parsers in this package
def discover_parsers():
    for loader, module_name, is_pkg in pkgutil.walk_packages(__path__):
        if module_name not in ["registry", "base", "scrapers_parser", "demo_parser"]:
            importlib.import_module(f".{module_name}", __package__)

discover_parsers()

__all__ = ["ParserRegistry", "register_parser", "ScrapersParser", "DemoParser"]
