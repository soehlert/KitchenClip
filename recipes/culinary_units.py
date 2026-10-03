"""Domain definitions and category sets for culinary units and meal-kit unit resolution."""

HEAD_PRODUCE: set[str] = {
    "broccoli",
    "cauliflower",
    "cabbage",
    "lettuce",
    "radicchio",
    "bok choy",
    "endive",
}

BUNCH_HERBS: set[str] = {
    "cilantro",
    "parsley",
    "dill",
    "mint",
    "rosemary",
    "thyme",
    "chives",
    "basil",
    "tarragon",
    "sage",
}

BAG_PRODUCE: set[str] = {
    "spinach",
    "arugula",
    "spring mix",
    "greens",
    "slaw",
    "coleslaw",
}

PACKET_CATEGORIES: set[str] = {
    # Stocks, broths & pastes
    "concentrate",
    "stock",
    "broth",
    "paste",
    "bouillon",
    # Spices & seasonings
    "spice",
    "seasoning",
    "rub",
    "blend",
    "powder",
    # Sauces, dressings & marinades
    "sauce",
    "dressing",
    "glaze",
    "marinade",
    "vinaigrette",
    "dip",
    "salsa",
    # Condiments & spreads
    "mayo",
    "mayonnaise",
    "mustard",
    "ketchup",
    "aioli",
    "pesto",
    "relish",
    "jam",
    "jelly",
    "honey",
    "syrup",
    "sriracha",
    # Dairy pouches
    "sour cream",
    "crema",
    "cream cheese",
    "ricotta",
    # Dry pantry packets
    "yeast",
    "gelatin",
    "breadcrumbs",
    "panko",
}

CULINARY_UNIT_TOKENS: set[str] = {
    # Spoons
    "teaspoon", "teaspoons", "tsp", "tsps",
    "tablespoon", "tablespoons", "tbsp", "tbsps",
    # Volume
    "cup", "cups", "c",
    "fluid ounce", "fluid ounces", "fl oz", "fl. oz.",
    "pint", "pints", "pt", "pts",
    "quart", "quarts", "qt", "qts",
    "gallon", "gallons", "gal", "gals",
    "milliliter", "milliliters", "ml", "mls",
    "liter", "liters", "l",
    # Weight
    "ounce", "ounces", "oz", "ozs",
    "pound", "pounds", "lb", "lbs",
    "gram", "grams", "g",
    "kilogram", "kilograms", "kg", "kgs",
    # Produce/Count/Containers
    "packet", "packets", "pkt", "pkts",
    "pouch", "pouches",
    "block", "blocks",
    "package", "packages", "pkg", "pkgs",
    "container", "containers",
    "box", "boxes",
    "carton", "cartons",
    "tub", "tubs",
    "tin", "tins",
    "head", "heads",
    "bunch", "bunches",
    "bag", "bags",
    "can", "cans",
    "jar", "jars",
    "bottle", "bottles",
    "clove", "cloves",
    "stalk", "stalks",
    "slice", "slices",
    "pinch", "pinches",
    "dash", "dashes",
    "drop", "drops",
    "piece", "pieces",
}
