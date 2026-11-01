"""Taxonomía geográfica multi-ciudad (Barcelona, Madrid) para el motor ELT de Market Intelligence:
configuración declarativa de áreas metropolitanas, alias locales y códigos provinciales por conector.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    name: str
    aliases: tuple[str, ...]
    linkedin_location: str
    tecnoempleo_province: str = ""


DEFAULT_CITIES: tuple[City, ...] = (
    City(
        "Barcelona",
        ("barcelona", "sant cugat", "hospitalet", "badalona", "sabadell", "terrassa", "mataro", "mataró", "cornella", "cornellà", "prat de llobregat", "catalonia", "cataluña", "catalunya", "valles", "vallès"),
        "Barcelona, Catalonia, Spain",
        "240",
    ),
    City(
        "Madrid",
        ("madrid", "alcobendas", "las rozas", "pozuelo", "getafe", "leganes", "leganés", "tres cantos", "boadilla", "alcorcon", "alcorcón", "community of madrid", "comunidad de madrid"),
        "Madrid, Community of Madrid, Spain",
        "263",
    ),
)


def load_cities(cfg: dict) -> list[City]:
    """Carga las ciudades configuradas en `locations` (con retrocompatibilidad para `location` simple)."""
    raw = cfg.get("locations")
    if isinstance(raw, list) and raw:
        cities = []
        for item in raw:
            name = str(item.get("city") or "").strip()
            if not name:
                continue
            aliases = tuple(a.lower() for a in (item.get("aliases") or [name]))
            cities.append(City(
                name=name,
                aliases=aliases,
                linkedin_location=str(item.get("linkedin_location") or f"{name}, Spain"),
                tecnoempleo_province=str(item.get("tecnoempleo_province") or ""),
            ))
        if cities:
            return cities
    legacy = str(cfg.get("location") or "").strip()
    if legacy:
        for preset in DEFAULT_CITIES:
            if preset.name.lower() == legacy.lower():
                return [preset]
        return [City(legacy, (legacy.lower(),), f"{legacy}, Spain")]
    return list(DEFAULT_CITIES)


def detect_city(location_text: str, cities: list[City], default: str = "") -> str:
    """Identifica el hub tecnológico a partir de una cadena libre de ubicación usando alias metropolitanos."""
    low = (location_text or "").lower()
    for city in cities:
        if any(alias in low for alias in city.aliases):
            return city.name
    return default


def city_of_jd(meta: dict, cities: list[City]) -> str:
    """Resuelve la ciudad canónica de una oferta priorizando el metadato `city` sobre `location`."""
    known = {c.name.lower(): c.name for c in cities}
    explicit = str(meta.get("city") or "").strip().lower()
    if explicit in known:
        return known[explicit]
    return detect_city(str(meta.get("location") or ""), cities, default=cities[0].name)
