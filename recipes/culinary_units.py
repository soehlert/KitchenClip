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
