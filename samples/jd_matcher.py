"""Motor determinista de clasificación NLP y afinidad léxica (TF-IDF / Cosine Similarity).

Evalúa descripciones de ofertas tecnológicas (JDs) frente a:
1. Listas de exclusión de agregadores/empresas.
2. Extracción multilingüe (ES/EN) de requisitos mínimos de años de experiencia.
3. Restricciones de idiomas adicionales obligatorios (C1/nativo).
4. Puntuación híbrida (0-100%) combinando taxonomías ponderadas de competencias y similitud coseno.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# Patrones que detectan exigencia explícita de N años de experiencia
EXP_YEARS_PATTERNS = [
    re.compile(
        r"(?:m[ií]nimo(?:\s+de)?|al\s+menos|como\s+m[ií]nimo|minimum(?:\s+of)?|at\s+least|over|more\s+than)\s*"
        r"(\d{1,2})\s*\+?\s*(?:a[ñn]os|years|ans)\b(?:\s+(?:de\s+)?(?:experiencia|experience))?",
        re.I,
    ),
    re.compile(
        r"\b(\d{1,2})\s*\+\s*(?:a[ñn]os|years)\s+(?:de\s+|of\s+)?(?:experiencia|experience|relevant|proven)",
        re.I,
    ),
    re.compile(
        r"(?:experiencia|experience)\s+(?:m[ií]nima|previa|demostrable|required)?\s*(?:de\s+|of\s+|:\s*)?"
        r"(\d{1,2})\s*(?:\+|a\s+\d{1,2}|-\s*\d{1,2}|o\s+m[aá]s)?\s*(?:a[ñn]os|years)\b",
        re.I,
    ),
]

# Detección de tercer idioma obligatorio (nivel C1/nativo/imprescindible)
MANDATORY_OTHER_LANG_RE = re.compile(
    r"(?:fluent|native|c1|c2|biling[uü]e|imprescindible|indispensable|mandatory|required)\s+"
    r"(?:level\s+of\s+|in\s+|en\s+|nivel\s+de\s+)?"
    r"(?:german|alem[aá]n|french|franc[eé]s|dutch|holand[eé]s|neerland[eé]s|italian|italiano|chinese|chino|arabic|[aá]rabe)\b"
    r"|\b(?:german|alem[aá]n|french|franc[eé]s|dutch|neerland[eé]s)\s+"
    r"(?:c1|c2|nativo|native|fluent|biling[uü]e|imprescindible|indispensable|mandatory)\b",
    re.I,
)

# Taxonomía ponderada para perfiles Data / BI / ERP / Supply Chain Analytics
SKILL_WEIGHTS: list[tuple[str, re.Pattern, float]] = [
    ("SQL", re.compile(r"\b(?:sql|t-sql|pl/sql|postgresql|mysql|sql\s+server)\b", re.I), 14.0),
    ("ERP", re.compile(r"\b(?:erp|ekon|cegid|sap|navision|dynamics|business\s+central|odoo|oracle\s+erp|netsuite)\b", re.I), 14.0),
    ("Supply Chain", re.compile(r"\b(?:supply\s+chain|cadena\s+de\s+suministro|log[ií]stica|logistics|compras|procurement|aprovisionamiento|inventario|stock|otif|almac[eé]n|producci[oó]n|manufacturing|operaciones|operations)\b", re.I), 14.0),
    ("Qlik", re.compile(r"\b(?:qlik|qlik\s*sense|qlikview)\b", re.I), 13.0),
    ("Master Data", re.compile(r"\b(?:datos\s+maestros|master\s+data|mdm|data\s+governance|calidad\s+del?\s+dato|data\s+quality|coupa|ebuy|servicenow)\b", re.I), 11.0),
    ("BI / Dashboards", re.compile(r"\b(?:power\s*bi|tableau|looker|metabase|superset|business\s+intelligence|cuadros?\s+de\s+mando|dashboards?|reporting|kpis?)\b", re.I), 11.0),
    ("Python", re.compile(r"\b(?:python|pandas|numpy|jupyter|scikit-learn)\b", re.I), 9.0),
    ("Data / ETL", re.compile(r"\b(?:data\s+analyst|analista\s+de\s+datos|analytics\s+engineer|etl|elt|dbt|data\s+warehouse|modelado\s+de\s+datos|data\s+modeling|bigquery|snowflake|databricks|fabric)\b", re.I), 9.0),
    ("IA / Automatización", re.compile(r"\b(?:inteligencia\s+artificial|artificial\s+intelligence|llm|claude|openai|genai|automatizaci[oó]n|automation|n8n|power\s+automate)\b", re.I), 8.0),
    ("Excel", re.compile(r"\b(?:excel|tablas\s+din[aá]micas|pivot\s+tables|vba|power\s+query)\b", re.I), 5.0),
]

PRIMARY_TITLE_RE = re.compile(
    r"\b(?:data\s+analyst|analista\s+de\s+datos|bi\s+analyst|analista\s+bi|business\s+intelligence|"
    r"supply\s+chain\s+analyst|analista\s+de?\s+supply\s+chain|operaciones|operations\s+analyst|"
    r"reporting\s+analyst|master\s+data|datos\s+maestros|erp)\b",
    re.I,
)

STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un", "para", "con", "no", "una",
    "su", "al", "lo", "como", "mas", "pero", "sus", "le", "ya", "o", "este", "si", "porque", "esta",
    "the", "and", "to", "of", "in", "for", "with", "on", "is", "as", "are", "that", "be", "at", "by",
    "from", "or", "an", "you", "will", "we", "our", "your", "this", "have", "has", "work", "working",
}

DEFAULT_REFERENCE_PROFILE = (
    "Data Analyst BI Business Intelligence SQL Python Qlik Sense Power BI ERP Supply Chain "
    "Logística Producción Compras Master Data Datos Maestros ETL Automatización Barcelona"
)


@dataclass
class MatchResult:
    passed: bool
    score: float
    matched_skills: list[str]
    reject_reason: str | None = None
    max_years_found: int = 0


def _tokenize(text: str) -> Counter:
    words = re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9]{3,}", text.lower())
    return Counter(w for w in words if w not in STOPWORDS)


def _cosine_similarity(c1: Counter, c2: Counter) -> float:
    if not c1 or not c2:
        return 0.0
    common = set(c1.keys()) & set(c2.keys())
    num = sum(c1[k] * c2[k] for k in common)
    den1 = math.sqrt(sum(v * v for v in c1.values()))
    den2 = math.sqrt(sum(v * v for v in c2.values()))
    if den1 == 0 or den2 == 0:
        return 0.0
    return num / (den1 * den2)


def extract_min_experience_years(description: str) -> int:
    """Devuelve el máximo número de años mínimos exigidos explícitamente en la JD (0 si no detecta)."""
    if not description:
        return 0
    found = []
    for pat in EXP_YEARS_PATTERNS:
        for m in pat.finditer(description):
            try:
                yrs = int(m.group(1))
                if 1 <= yrs <= 15:
                    found.append(yrs)
            except ValueError:
                pass
    return max(found) if found else 0


def evaluate_jd(
    title: str,
    company: str,
    description: str,
    company_blacklist: list[str] | None = None,
    max_experience_years: int = 4,
    min_affinity_score: float = 15.0,
    reference_profile_text: str = DEFAULT_REFERENCE_PROFILE,
) -> MatchResult:
    """Evalúa si una oferta pasa las reglas de filtrado y calcula su afinidad (0-100)."""
    comp_lower = (company or "").lower().strip()
    for blocked in (company_blacklist or []):
        if blocked.lower() in comp_lower:
            return MatchResult(False, 0.0, [], reject_reason=f"blacklisted_company:{blocked}")

    full_text = f"{title or ''}\n{description or ''}"

    if description and len(description.strip()) >= 150:
        yrs = extract_min_experience_years(description)
        if yrs > max_experience_years:
            return MatchResult(
                False,
                0.0,
                [],
                reject_reason=f"requires_{yrs}_years_gt_{max_experience_years}",
                max_years_found=yrs,
            )

        if MANDATORY_OTHER_LANG_RE.search(description):
            return MatchResult(False, 0.0, [], reject_reason="mandatory_third_language")
    else:
        yrs = 0

    matched_skills: list[str] = []
    raw_skill_points = 0.0
    for label, pattern, weight in SKILL_WEIGHTS:
        if pattern.search(full_text):
            matched_skills.append(label)
            raw_skill_points += weight

    title_bonus = 15.0 if PRIMARY_TITLE_RE.search(title or "") else 0.0

    ref_tokens = _tokenize(reference_profile_text)
    jd_tokens = _tokenize(full_text)
    cos_sim = _cosine_similarity(ref_tokens, jd_tokens)
    lexical_points = min(20.0, cos_sim * 65.0)

    total_score = min(100.0, round(raw_skill_points + title_bonus + lexical_points, 1))

    if description and len(description.strip()) >= 150 and total_score < min_affinity_score:
        return MatchResult(
            False,
            total_score,
            matched_skills,
            reject_reason=f"low_affinity:{total_score}<{min_affinity_score}",
            max_years_found=yrs,
        )

    return MatchResult(True, total_score, matched_skills, reject_reason=None, max_years_found=yrs)
