"""Versioned deterministic pin taxonomy and offline phrase catalog."""

from __future__ import annotations

TAXONOMY_VERSION = "2026.07.1"

TAG_RULES: dict[str, tuple[str, ...]] = {
    "market_food": (
        "market", "food", "restaurant", "cafe", "café", "bakery", "fish", "seafood",
        "sushi", "ramen", "bar", "dining",
    ),
    "temple_spirituality": (
        "temple", "shrine", "church", "mosque", "cathedral", "monastery", "spiritual",
    ),
    "museum_history": (
        "museum", "gallery", "archive", "palace", "castle", "historic", "history",
        "memorial", "heritage",
    ),
    "nature_gardens": (
        "park", "garden", "beach", "trail", "forest", "mountain", "botanical", "lake",
    ),
    "transport": ("station", "airport", "terminal", "metro", "subway", "rail", "train"),
    "accommodation": ("hotel", "hostel", "ryokan", "apartment", "resort", "inn"),
}

PHRASE_CATALOG: dict[str, list[dict[str, str]]] = {
    "market_food": [
        {"phrase": "Kore wa ikura desu ka?", "translation": "How much is this?"},
        {"phrase": "Osusume wa nan desu ka?", "translation": "What do you recommend?"},
        {"phrase": "Arigatou gozaimasu.", "translation": "Thank you very much."},
    ],
    "temple_spirituality": [
        {"phrase": "Irigu chi wa doko desu ka?", "translation": "Where is the entrance?"},
        {"phrase": "Shashin o totte mo ii desu ka?", "translation": "May I take photos?"},
        {"phrase": "Arigatou gozaimasu.", "translation": "Thank you very much."},
    ],
    "museum_history": [
        {"phrase": "Tenji wa doko desu ka?", "translation": "Where is the exhibition?"},
        {"phrase": "Eigo no annai wa arimasu ka?", "translation": "Is there information in English?"},
        {"phrase": "Shashin o totte mo ii desu ka?", "translation": "May I take photos?"},
    ],
    "nature_gardens": [
        {"phrase": "Toire wa doko desu ka?", "translation": "Where is the restroom?"},
        {"phrase": "Kono michi wa anzen desu ka?", "translation": "Is this path safe?"},
        {"phrase": "Arigatou gozaimasu.", "translation": "Thank you very much."},
    ],
    "transport": [
        {"phrase": "Eki wa doko desu ka?", "translation": "Where is the station?"},
        {"phrase": "Kono densha wa ... ni ikimasu ka?", "translation": "Does this train go to ...?"},
        {"phrase": "Kippu o kaitai desu.", "translation": "I would like to buy a ticket."},
    ],
    "accommodation": [
        {"phrase": "Chekku in onegaishimasu.", "translation": "I would like to check in."},
        {"phrase": "Wi-Fi no pasuwado wa nan desu ka?", "translation": "What is the Wi-Fi password?"},
        {"phrase": "Arigatou gozaimasu.", "translation": "Thank you very much."},
    ],
    "general_travel": [
        {"phrase": "Sumimasen.", "translation": "Excuse me."},
        {"phrase": "Osusume wa nan desu ka?", "translation": "What do you recommend?"},
        {"phrase": "Arigatou gozaimasu.", "translation": "Thank you very much."},
    ],
}

GENERIC_PHRASE_CATALOG: dict[str, list[dict[str, str]]] = {
    "market_food": [
        {"phrase": "How much is this?", "translation": "A useful market price question."},
        {"phrase": "What do you recommend?", "translation": "Ask for a local recommendation."},
        {"phrase": "Thank you.", "translation": "A basic polite close."},
    ],
    "temple_spirituality": [
        {"phrase": "Where is the entrance?", "translation": "Find the correct visitor approach."},
        {"phrase": "May I take photos?", "translation": "Ask before photographing."},
        {"phrase": "Thank you.", "translation": "A basic polite close."},
    ],
    "museum_history": [
        {"phrase": "Where is the exhibition?", "translation": "Ask for the relevant gallery or display."},
        {"phrase": "Is there information in English?", "translation": "Ask about accessible interpretation."},
        {"phrase": "May I take photos?", "translation": "Ask before photographing."},
    ],
    "nature_gardens": [
        {"phrase": "Where is the trail entrance?", "translation": "Start a route safely."},
        {"phrase": "Is this path open?", "translation": "Check local access conditions."},
        {"phrase": "Thank you.", "translation": "A basic polite close."},
    ],
    "transport": [
        {"phrase": "Where is the station?", "translation": "Find transit access."},
        {"phrase": "Does this go to ...?", "translation": "Confirm the direction before boarding."},
        {"phrase": "I would like to buy a ticket.", "translation": "A core transit request."},
    ],
    "accommodation": [
        {"phrase": "I would like to check in.", "translation": "Start an accommodation interaction."},
        {"phrase": "What is the Wi-Fi password?", "translation": "Ask for an essential service."},
        {"phrase": "Thank you.", "translation": "A basic polite close."},
    ],
    "general_travel": [
        {"phrase": "Excuse me.", "translation": "Get attention politely."},
        {"phrase": "Could you help me?", "translation": "Ask for assistance."},
        {"phrase": "Thank you.", "translation": "A basic polite close."},
    ],
}

RELATED_CONCEPTS = {
    "market_food": ["food culture", "seasonal ingredients", "market etiquette"],
    "temple_spirituality": ["respectful visitation", "spiritual traditions", "site guidance"],
    "museum_history": ["historical context", "curatorial themes", "museum etiquette"],
    "nature_gardens": ["local ecology", "seasonality", "responsible access"],
    "transport": ["wayfinding", "public transport", "arrival planning"],
    "accommodation": ["check-in", "accessibility", "local neighbourhood"],
    "general_travel": ["navigation", "respectful communication", "local guidance"],
}
