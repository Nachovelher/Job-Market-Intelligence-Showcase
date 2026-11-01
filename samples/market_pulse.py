"""Motor de deduplicación inter-portal sensible a ciudad (Entity Resolution) y analítica Market Pulse."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

import pandas as pd

from cities import City, city_of_jd, detect_city

INCLUDE = re.compile(
    r"\b(?:data|datos|IA|AI|ML|BI|LLM|python|sql|erp|qlik|power\s*bi|tableau|supply\s+chain)\b"
    r"|machine learning|analytic|anal[ií]tic|analista|intelig|business\s+intelligence",
    re.I,
)
EXCLUDE = re.compile(
    r"\b(?:senior|sr\.?|leads?|principal|head|director|vp|chief|staff|manager|graduate|researcher|stager|phd|sap|abap)\b"
    r"|pr[aá]cticas|becari|intern(?:ship)?|postdoc",
    re.I,
)

SKILLS_CATALOG: list[tuple[str, str, re.Pattern]] = [
    ("SQL", "Datos & Bases de Datos", re.compile(r"\b(?:sql|t-sql|pl/sql|postgresql|mysql|sql\s+server)\b", re.I)),
    ("Python", "Programación & Data Science", re.compile(r"\b(?:python|pandas|numpy|scikit-learn|scipy)\b", re.I)),
    ("Power BI", "Business Intelligence", re.compile(r"\b(?:power\s*bi|dax|power\s+query)\b", re.I)),
    ("Excel Avanzado", "Business Intelligence", re.compile(r"\b(?:excel|tablas\s+din[aá]micas|pivot\s+tables|vba)\b", re.I)),
    ("Qlik (Sense / View)", "Business Intelligence", re.compile(r"\b(?:qlik|qlik\s*sense|qlikview)\b", re.I)),
    ("Tableau", "Business Intelligence", re.compile(r"\b(?:tableau)\b", re.I)),
    ("Looker / Looker Studio", "Business Intelligence", re.compile(r"\b(?:looker|data\s+studio)\b", re.I)),
    ("ERP (SAP / Ekon / Navision)", "Dominio & ERP", re.compile(r"\b(?:erp|sap|ekon|cegid|navision|dynamics|business\s+central|odoo|coupa)\b", re.I)),
    ("Supply Chain / Logística / Compras", "Dominio & ERP", re.compile(r"\b(?:supply\s+chain|cadena\s+de\s+suministro|log[ií]stica|logistics|compras|procurement|inventario|stock|otif|producci[oó]n)\b", re.I)),
    ("Master Data / Data Governance", "Datos & Bases de Datos", re.compile(r"\b(?:datos\s+maestros|master\s+data|mdm|data\s+governance|data\s+quality|calidad\s+del?\s+dato)\b", re.I)),
    ("ETL / Data Warehousing", "Data Engineering", re.compile(r"\b(?:etl|elt|data\s+warehouse|dwh|modelado\s+dimensional|star\s+schema)\b", re.I)),
    ("dbt", "Data Engineering", re.compile(r"\b(?:dbt)\b", re.I)),
    ("Azure / Data Factory", "Cloud & Big Data", re.compile(r"\b(?:azure|data\s+factory|adf|synapse)\b", re.I)),
    ("Microsoft Fabric", "Cloud & Big Data", re.compile(r"\b(?:microsoft\s+fabric|ms\s+fabric)\b", re.I)),
    ("AWS", "Cloud & Big Data", re.compile(r"\b(?:aws|amazon\s+web\s+services|redshift|s3|athena|glue)\b", re.I)),
    ("GCP / BigQuery", "Cloud & Big Data", re.compile(r"\b(?:gcp|google\s+cloud|bigquery)\b", re.I)),
    ("Databricks / Spark", "Cloud & Big Data", re.compile(r"\b(?:databricks|spark|pyspark)\b", re.I)),
    ("Snowflake", "Cloud & Big Data", re.compile(r"\b(?:snowflake)\b", re.I)),
    ("Git / CI/CD", "Ingeniería de Software", re.compile(r"\b(?:git|github|gitlab|ci/cd|docker)\b", re.I)),
    ("LLMs / GenAI / Agentes", "IA & Automatización", re.compile(r"\b(?:llm|llms|genai|ia\s+generativa|generative\s+ai|openai|claude|langchain|rag|prompt\s+engineering)\b", re.I)),
    ("Automatización (Power Automate / n8n)", "IA & Automatización", re.compile(r"\b(?:power\s+automate|n8n|make|zapier|rpa|uipath)\b", re.I)),
]


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60]


def canonical_job_key(company: str, title: str, city: str = "") -> str:
    """Genera una clave canónica inmune a acentos y sufijos societarios, particionada por ciudad si está disponible."""
    comp_slug = slugify(company or "")
    comp_root = comp_slug.split("-")[0] if comp_slug else "unknown"
    title_slug = slugify(title or "")
    city_slug = slugify(city or "")
    return f"{title_slug}|{comp_root}|{city_slug}" if city_slug else f"{title_slug}|{comp_root}"


def tag_city(frame: pd.DataFrame, cities: list[City], default: str) -> pd.DataFrame:
    """Etiqueta cada fila con su ciudad canónica según alias metropolitanos o ciudad de origen."""
    if frame is None or frame.empty:
        return frame
    locs = frame["location"] if "location" in frame.columns else pd.Series("", index=frame.index)
    return frame.assign(city=[detect_city(str(loc), cities, default) for loc in locs.fillna("")])


def filter_titles(jobs: pd.DataFrame) -> pd.DataFrame:
    if jobs.empty:
        return jobs
    titles = jobs["title"].fillna("")
    return jobs[titles.str.contains(INCLUDE) & ~titles.str.contains(EXCLUDE)].copy()


def dedupe_across_sites(jobs: pd.DataFrame) -> pd.DataFrame:
    """Colapsa la misma oferta publicada en múltiples portales dentro de una misma ciudad conservando la JD más extensa."""
    if jobs.empty:
        return jobs
    cities_col = jobs["city"].fillna("") if "city" in jobs.columns else pd.Series("", index=jobs.index)
    keys = [
        canonical_job_key(str(c or ""), str(t or ""), str(ct or ""))
        for c, t, ct in zip(jobs["company"].fillna(""), jobs["title"].fillna(""), cities_col)
    ]
    jd_len = jobs["description"].fillna("").astype(str).str.len()
    return (
        jobs.assign(_key=keys, _jd_len=jd_len)
        .sort_values("_jd_len", ascending=False)
        .drop_duplicates("_key")
        .drop(columns=["_key", "_jd_len"])
    )


def detect_modality(text: str) -> str:
    if re.search(r"\b(?:h[ií]brido|hybrid|teletrabajo\s+parcial|\d\s+d[ií]as\s+en\s+oficina|\d\s+days\s+remote)\b", text, re.I):
        return "Híbrido"
    if re.search(r"\b(?:100%\s*remoto|full\s*remote|totalmente\s+remoto|remoto\s+en\s+espa[ñn]a)\b", text, re.I):
        return "100% Remoto"
    if re.search(r"\b(?:presencial|on-?site|en\s+oficina)\b", text, re.I):
        return "Presencial"
    return "No especificado"


def make_bar(pct: float, width: int = 12) -> str:
    filled = round((pct / 100.0) * width)
    return "█" * filled + "░" * (width - filled)


def compute_skills_ranking(texts: list[str]) -> list[dict]:
    """Calcula la frecuencia y cuota de mercado (%) de cada tecnología sobre una colección de JDs."""
    total = len(texts)
    if total == 0:
        return []
    counts: Counter = Counter()
    for txt in texts:
        for name, _, pat in SKILLS_CATALOG:
            if pat.search(txt):
                counts[name] += 1

    ranking = []
    for name, category, _ in SKILLS_CATALOG:
        cnt = counts[name]
        if cnt > 0:
            ranking.append({
                "skill": name,
                "category": category,
                "count": cnt,
                "pct": round((cnt / total) * 100, 1),
            })
    ranking.sort(key=lambda x: x["count"], reverse=True)
    return ranking


def compute_multi_city_pulse(jds: list[dict], cities: list[City]) -> dict[str, dict]:
    """Particiona una colección de JDs por ciudad y calcula métricas tecnológicas independientes por hub."""
    assigned = [city_of_jd(jd, cities) for jd in jds]
    result: dict[str, dict] = {}
    for city in cities:
        city_texts = [
            f"{jd.get('title', '')}\n{jd.get('body', '')}"
            for jd, jc in zip(jds, assigned)
            if jc == city.name
        ]
        result[city.name] = {
            "total_jds_analyzed": len(city_texts),
            "skills_ranking": compute_skills_ranking(city_texts),
        }
    return result
