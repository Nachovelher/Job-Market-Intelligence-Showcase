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

from jd_matcher import (  # noqa: E402
    _cosine_similarity,
    _tokenize,
    evaluate_jd,
    extract_min_experience_years,
)
from market_pulse import (  # noqa: E402
    canonical_job_key,
    compute_skills_ranking,
    dedupe_across_sites,
    detect_modality,
    filter_titles,
    make_bar,
    slugify,
)
from spanish_portals import _html_to_md  # noqa: E402


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
            {"title": "Becario BI"},
        ])
        self.assertEqual(list(filter_titles(df_titles)["title"]), ["Data Analyst"])


if __name__ == "__main__":
    unittest.main()
