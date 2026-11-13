"""Configuration independent of domain imports to avoid validation cycles."""
from copy import deepcopy

CATEGORIES = ("creators", "athletes", "music", "teams", "events", "gaming_media")
LANES = ("direct", "audience", "adjacent")
FORMATS = ("content_series", "ambassador", "event_activation", "season_program", "licensed_content")
CAPABILITIES = {
    "content_owner": "Ответственный за контент и согласования",
    "ongoing_owner": "Ресурс на регулярную работу с партнёром",
    "event_team": "Команда офлайн-активации",
    "paid_media": "Бюджет и команда платного продвижения",
    "conversion_tracking": "Измерение целевого действия",
    "brand_measurement": "Возможность измерить брендовый результат",
}


def preferences(raw=None):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("search_preferences: нужен объект")
    allowed = {"categories", "lanes", "languages", "formats", "order", "max_profiles", "capabilities"}
    if set(raw) - allowed:
        raise ValueError("Неизвестные настройки поиска: " + ", ".join(sorted(set(raw)-allowed)))
    result = deepcopy(raw)
    for key, choices, default in (("categories", CATEGORIES, list(CATEGORIES)), ("lanes", LANES, list(LANES)),
                                  ("languages", ("es", "pt", "en"), []), ("formats", FORMATS, list(FORMATS))):
        values = result.setdefault(key, default)
        if (not isinstance(values, list) or any(not isinstance(v, str) or v not in choices for v in values)
                or len(values) != len(set(values)) or (key != "languages" and not values)):
            raise ValueError(f"search_preferences.{key}: нужны уникальные допустимые значения")
    if result.setdefault("order", "balanced") not in ("balanced", "focused"):
        raise ValueError("order: balanced или focused")
    maximum = result.setdefault("max_profiles", 3)
    if type(maximum) is not int or not 1 <= maximum <= len(FORMATS):
        raise ValueError("max_profiles: целое 1–5")
    capabilities = result.setdefault("capabilities", {})
    if not isinstance(capabilities, dict) or set(capabilities) - set(CAPABILITIES):
        raise ValueError("Неизвестные capabilities")
    for key, value in capabilities.items():
        if value is not None and type(value) is not bool:
            raise ValueError(f"capabilities.{key}: true / false / null")
    return result
