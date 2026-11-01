"""Suite de tests unitarios para los módulos de muestra del Showcase."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
if str(SAMPLES) not in sys.path:
    sys.path.insert(0, str(SAMPLES))

from cities import DEFAULT_CITIES, city_of_jd, detect_city, load_cities  # noqa: E402
from jd_matcher import (  # noqa: E402
    _cosine_similarity,
    _tokenize,
    evaluate_jd,
    extract_min_experience_years,
)
from market_pulse import (  # noqa: E402
    canonical_job_key,
    compute_multi_city_pulse,
    compute_skills_ranking,
    dedupe_across_sites,
    detect_modality,
    filter_titles,
    make_bar,
    slugify,
    tag_city,
)
from spanish_portals import _html_to_md, _jsonld_location  # noqa: E402

CITIES = list(DEFAULT_CITIES)


class TestShowcaseSuite(unittest.TestCase):
    def test_extract_min_experience_years(self) -> None:
        self.assertEqual(
            extract_min_experience_years("Buscamos perfil con mínimo de 5 años de experiencia en BI."),
            5,
        )
        self.assertEqual(
            extract_min_experience_years("Requirements: at least 6+ years of experience in SQL and Python."),
            6,
        )
        self.assertEqual(
            extract_min_experience_years("Experiencia mínima: 2 años en consultoría ERP o análisis de datos."),
            2,
        )

    def test_evaluate_jd_rejects_excessive_seniority(self) -> None:
        jd_body = (
            "We are looking for a Data Analyst in Barcelona. "
            "You must have a minimum of 6 years of experience building data warehouses with SQL and Python. "
            "Responsibilities include dashboarding in Power BI and ETL maintenance."
        )
        res = evaluate_jd("Data Analyst", "Acme Corp", jd_body, max_experience_years=4)
        self.assertFalse(res.passed)
        self.assertEqual(res.max_years_found, 6)

    def test_evaluate_jd_rejects_mandatory_third_language(self) -> None:
        jd_body = (
            "Buscamos Data Analyst para nuestro hub en Barcelona con SQL, Power BI y ERP SAP. "
            "Requisitos: experiencia de 2 años en análisis de datos e imprescindible alemán C1 fluido "
            "para interlocución diaria con la sede en Múnich."
        )
        res = evaluate_jd("Data Analyst", "Industrial BCN", jd_body, max_experience_years=4)
        self.assertFalse(res.passed)
        self.assertEqual(res.reject_reason, "mandatory_third_language")

    def test_evaluate_jd_high_affinity_for_erp_supply_chain_sql(self) -> None:
        jd_body = (
            "Buscamos un Supply Chain Data Analyst en Barcelona (híbrido). "
            "Trabajarás con datos del ERP (compras, inventario, producción, OTIF), "
            "consultas SQL diarias, gestión de datos maestros y cuadros de mando en Qlik Sense / Power BI. "
            "Valorable conocimientos de Python y automatización de procesos. Experiencia mínima de 2 años."
        )
        res = evaluate_jd("Supply Chain Data Analyst", "Logística BCN", jd_body, max_experience_years=4)
        self.assertTrue(res.passed)
        self.assertGreaterEqual(res.score, 65.0)

    def test_cosine_similarity_and_deduplication(self) -> None:
        t1 = _tokenize("sql python erp supply chain barcelona datos")
        self.assertAlmostEqual(_cosine_similarity(t1, t1), 1.0, places=5)
        self.assertEqual(
            canonical_job_key("Mática Partners S.L.", "Data Scientist – Time Series"),
            canonical_job_key("Matica Partners", "Data Scientist - Time Series"),
        )
        df = pd.DataFrame([
            {"site": "linkedin", "company": "Glovo Spain", "title": "Data Analyst", "description": "Short"},
            {"site": "indeed", "company": "Glovo", "title": "Data Analyst!", "description": "Longer full JD"},
        ])
        deduped = dedupe_across_sites(df)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped.iloc[0]["site"], "indeed")

    def test_dedupe_across_sites_preserves_distinct_cities(self) -> None:
        df = pd.DataFrame([
            {"site": "linkedin", "company": "Randstad España", "title": "Data Analyst", "city": "Barcelona", "description": "Short BCN"},
            {"site": "randstad", "company": "Randstad", "title": "Data Analyst", "city": "Barcelona", "description": "Complete BCN JD"},
            {"site": "randstad", "company": "Randstad España", "title": "Data Analyst", "city": "Madrid", "description": "Complete MAD JD"},
        ])
        deduped = dedupe_across_sites(df)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(set(deduped["city"]), {"Barcelona", "Madrid"})

    def test_city_detection_and_metropolitan_aliases(self) -> None:
        self.assertEqual(detect_city("Alcobendas, Community of Madrid, Spain", CITIES, "Barcelona"), "Madrid")
        self.assertEqual(detect_city("Sant Cugat del Vallès, Catalonia, Spain", CITIES, "Madrid"), "Barcelona")
        self.assertEqual(detect_city("Tres Cantos, Spain", CITIES, "Barcelona"), "Madrid")
        self.assertEqual(detect_city("Remoto, Spain", CITIES, "Barcelona"), "Barcelona")

    def test_load_cities_and_legacy_fallback(self) -> None:
        cfg = {
            "locations": [
                {"city": "Madrid", "aliases": ["Madrid"], "linkedin_location": "Madrid, Spain", "tecnoempleo_province": "263"},
            ]
        }
        cities = load_cities(cfg)
        self.assertEqual([c.name for c in cities], ["Madrid"])
        self.assertEqual(cities[0].tecnoempleo_province, "263")
        self.assertEqual([c.name for c in load_cities({"location": "Barcelona"})], ["Barcelona"])
        self.assertEqual([c.name for c in load_cities({})], ["Barcelona", "Madrid"])

    def test_city_of_jd_and_tag_city(self) -> None:
        self.assertEqual(city_of_jd({"city": "Madrid", "location": "Remoto, Spain"}, CITIES), "Madrid")
        self.assertEqual(city_of_jd({"location": "Pozuelo de Alarcón, Spain"}, CITIES), "Madrid")
        df = pd.DataFrame([{"title": "BI Analyst", "location": "Getafe, Madrid"}])
        tagged = tag_city(df, CITIES, default="Barcelona")
        self.assertEqual(list(tagged["city"]), ["Madrid"])

    def test_multi_city_market_pulse_and_jsonld_location(self) -> None:
        jds = [
            {"title": "Data Analyst", "body": "SQL and Power BI", "city": "Barcelona"},
            {"title": "Analytics Engineer", "body": "SQL, dbt and Snowflake", "location": "Madrid, Spain"},
        ]
        pulse = compute_multi_city_pulse(jds, CITIES)
        self.assertEqual(pulse["Barcelona"]["total_jds_analyzed"], 1)
        self.assertEqual(pulse["Madrid"]["total_jds_analyzed"], 1)
        self.assertEqual(
            _jsonld_location({"jobLocation": [{"address": {"addressLocality": "Alcobendas"}}]}, "Madrid, Spain"),
            "Alcobendas, Spain",
        )

    def test_market_pulse_and_html_normalization(self) -> None:
        self.assertEqual(slugify("Analista de Datos / BI (Híbrido)"), "analista-de-datos-bi-hibrido")
        self.assertEqual(detect_modality("Modalidad híbrido en Barcelona"), "Híbrido")
        self.assertEqual(len(make_bar(50.0, width=10)), 10)
        ranking = compute_skills_ranking(["SQL and Python with Power BI", "SQL and SAP ERP"])
        self.assertEqual(ranking[0]["skill"], "SQL")
        self.assertEqual(ranking[0]["count"], 2)
        self.assertIn("## Requisitos", _html_to_md("<h2>Requisitos</h2>"))
        df_titles = pd.DataFrame([
            {"title": "Data Analyst"},
            {"title": "Senior Data Analyst"},
            {"title": "Analista Programador SAP ABAP"},
            {"title": "Becario BI"},
        ])
        self.assertEqual(list(filter_titles(df_titles)["title"]), ["Data Analyst"])


if __name__ == "__main__":
    unittest.main()
