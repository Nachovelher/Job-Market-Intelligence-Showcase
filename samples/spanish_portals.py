"""Módulo de ingesta multi-portal para el mercado tecnológico en España / Barcelona:
- Extracción de Schema.org/JobPosting en JSON-LD con tolerancia a caracteres de control (Randstad, Tecnoempleo).
- Hidratación SSR Next.js (__NEXT_DATA__) y filtrado incremental sobre sitemaps XML (Manfred).
- Impersonación de huella TLS de navegador con curl_cffi y normalización HTML -> Markdown (markdownify).
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from typing import Any

import curl_cffi.requests as requests
import pandas as pd
from bs4 import BeautifulSoup
from markdownify import markdownify as md

LI_JOB_ID_RE = re.compile(r"(?:jobs/view/(?:[^/?#]*-)?|currentJobId=)(\d{8,12})")
MANFRED_SLUG_RE = re.compile(
    r"(?:data|datos|bi|business-intelligence|analytics|analyst|analista|ai|ia|ml|machine-learning|"
    r"python|sql|erp|supply|power-bi|qlik)",
    re.I,
)


def _html_to_md(raw_html: str) -> str:
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    text = md(unescaped, heading_style="ATX", bullets="-")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_linkedin_guest_jd(job_url: str) -> str:
    """Recupera la descripción completa de una oferta de LinkedIn usando el endpoint guest público."""
    m = LI_JOB_ID_RE.search(job_url or "")
    if not m:
        return ""
    job_id = m.group(1)
    api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        r = requests.get(api_url, impersonate="chrome", timeout=12)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        desc_div = soup.find("div", class_=re.compile(r"show-more-less-html__markup"))
        if not desc_div:
            return ""
        return _html_to_md(str(desc_div))
    except Exception:
        return ""


def scrape_randstad(terms: list[str], location: str = "barcelona", max_per_term: int = 8) -> pd.DataFrame:
    """Busca ofertas en Randstad España (randstad.es) y extrae el JobPosting JSON-LD."""
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    loc_slug = re.sub(r"[^a-z0-9]+", "-", location.lower()).strip("-")

    for term in terms[:5]:
        q_slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
        list_url = f"https://www.randstad.es/candidatos/ofertas-empleo/q-{q_slug}/p-{loc_slug}/"
        try:
            r = requests.get(list_url, impersonate="chrome", timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            offer_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/candidatos/ofertas-empleo/oferta/" in href:
                    full_url = href if href.startswith("http") else f"https://www.randstad.es{href}"
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        offer_links.append(full_url)

            for detail_url in offer_links[:max_per_term]:
                try:
                    rd = requests.get(detail_url, impersonate="chrome", timeout=12)
                    if rd.status_code != 200:
                        continue
                    sd = BeautifulSoup(rd.text, "html.parser")
                    job_ld = None
                    for sc in sd.find_all("script", type="application/ld+json"):
                        if sc.string and "JobPosting" in sc.string:
                            job_ld = json.loads(sc.string, strict=False)
                            break
                    if not job_ld:
                        continue

                    title = html.unescape(str(job_ld.get("title", "")).strip())
                    desc_html = str(job_ld.get("description", ""))
                    if isinstance(job_ld.get("responsibilities"), str):
                        desc_html += "<br><br><strong>Responsabilidades:</strong><br>" + job_ld["responsibilities"]
                    if isinstance(job_ld.get("experienceRequirements"), str):
                        desc_html += "<br><br><strong>Requisitos:</strong><br>" + job_ld["experienceRequirements"]

                    loc_str = f"{location.title()}, Spain"
                    job_loc = job_ld.get("jobLocation")
                    if isinstance(job_loc, dict):
                        addr = job_loc.get("address", {})
                        if isinstance(addr, dict):
                            locality = addr.get("addressLocality") or addr.get("addressRegion")
                            if locality:
                                loc_str = f"{locality}, Spain"

                    rows.append({
                        "site": "randstad",
                        "title": title,
                        "company": "Randstad España",
                        "location": loc_str,
                        "job_url": detail_url,
                        "job_url_direct": detail_url,
                        "description": _html_to_md(desc_html),
                    })
                    time.sleep(0.5)
                except Exception:
                    continue
        except Exception as exc:
            print(f"[aviso] Randstad '{term}' falló: {exc}", file=sys.stderr)
    return pd.DataFrame(rows)


def scrape_robert_walters(terms: list[str], location: str = "Barcelona, Catalonia, Spain") -> pd.DataFrame:
    """Extrae ofertas activas de Robert Walters en Barcelona mediante LinkedIn Guest Search + JobPosting API."""
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    queries = [
        '"Robert Walters" data',
        '"Robert Walters" analyst',
        '"Robert Walters" BI',
        '"Robert Walters" ERP',
        '"Robert Walters" supply chain',
        '"Robert Walters" IT',
    ]
    for q in queries:
        search_url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords={requests.utils.quote(q)}"
            f"&location={requests.utils.quote(location)}"
            "&f_TPR=r2592000"
        )
        try:
            r = requests.get(search_url, impersonate="chrome", timeout=12)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for card in soup.find_all("div", class_="base-card"):
                comp_el = card.find("h4", class_="base-search-card__subtitle")
                comp_name = comp_el.get_text(strip=True) if comp_el else ""
                if "robert walters" not in comp_name.lower():
                    continue

                title_el = card.find("h3", class_="base-search-card__title")
                loc_el = card.find("span", class_="job-search-card__location")
                link_el = card.find("a", class_="base-card__full-link")
                if not title_el or not link_el:
                    continue

                href = link_el.get("href", "").split("?")[0]
                m = LI_JOB_ID_RE.search(href)
                job_id = m.group(1) if m else href
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                desc = fetch_linkedin_guest_jd(href)
                rows.append({
                    "site": "robertwalters",
                    "title": title_el.get_text(strip=True),
                    "company": "Robert Walters",
                    "location": loc_el.get_text(strip=True) if loc_el else "Barcelona, Spain",
                    "job_url": href,
                    "job_url_direct": href,
                    "description": desc,
                })
                time.sleep(0.6)
            time.sleep(1.0)
        except Exception as exc:
            print(f"[aviso] Robert Walters '{q}' falló: {exc}", file=sys.stderr)
    return pd.DataFrame(rows)


def scrape_manfred(max_offers: int = 25) -> pd.DataFrame:
    """Extrae ofertas activas de Manfred (getmanfred.com) filtrando su sitemap de ofertas recientes."""
    rows: list[dict[str, Any]] = []
    try:
        r = requests.get("https://www.getmanfred.com/sitemap-offers.xml", impersonate="chrome", timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        all_urls = re.findall(r"<loc>(https://www\.getmanfred\.com/ofertas-empleo/\d+/[^<]+)</loc>", r.text)

        def _offer_id(u: str) -> int:
            m = re.search(r"/ofertas-empleo/(\d+)/", u)
            return int(m.group(1)) if m else 0

        candidate_urls = sorted(
            (u for u in set(all_urls) if MANFRED_SLUG_RE.search(u.split("/")[-1])),
            key=_offer_id,
            reverse=True,
        )[:max_offers]

        for url in candidate_urls:
            try:
                ro = requests.get(url, impersonate="chrome", timeout=12)
                if ro.status_code != 200:
                    continue
                so = BeautifulSoup(ro.text, "html.parser")
                nd_tag = so.find("script", id="__NEXT_DATA__")
                if not nd_tag or not nd_tag.string:
                    continue
                offer = json.loads(nd_tag.string).get("props", {}).get("pageProps", {}).get("offer", {})
                if not isinstance(offer, dict):
                    continue
                if offer.get("status") != "ACTIVE" and not offer.get("active"):
                    continue

                loc_raw = offer.get("locationsSummary")
                if isinstance(loc_raw, dict):
                    loc_summary = str(loc_raw.get("trimmedCitiesStr") or "")
                else:
                    loc_summary = str(loc_raw or "")
                is_remote = bool(offer.get("remote"))
                if "barcelona" not in loc_summary.lower() and not is_remote:
                    continue

                title = str(offer.get("title") or "").strip()
                company = str(offer.get("company") or "Manfred Client").strip()
                sal_min = offer.get("salaryMin")
                sal_max = offer.get("salaryMax")
                sal_str = f"\n\n**Salario publicado en Manfred:** {sal_min}€ - {sal_max}€" if sal_min else ""

                desc = ""
                jsonld_raw = offer.get("jsonld")
                if isinstance(jsonld_raw, str) and jsonld_raw.strip():
                    try:
                        jld = json.loads(jsonld_raw, strict=False)
                        desc = _html_to_md(str(jld.get("description", "")))
                    except Exception:
                        pass
                if not desc:
                    main_el = so.find("main")
                    desc = _html_to_md(str(main_el)) if main_el else ""

                loc_label = f"{loc_summary} (Remoto)" if is_remote and loc_summary else ("Remoto, Spain" if is_remote else f"{loc_summary}, Spain")
                rows.append({
                    "site": "manfred",
                    "title": title,
                    "company": company,
                    "location": loc_label,
                    "job_url": url,
                    "job_url_direct": url,
                    "description": (desc + sal_str).strip(),
                })
                time.sleep(0.4)
            except Exception:
                continue
    except Exception as exc:
        print(f"[aviso] Manfred falló: {exc}", file=sys.stderr)
    return pd.DataFrame(rows)


def scrape_tecnoempleo(terms: list[str], province_code: str = "233", max_per_term: int = 6) -> pd.DataFrame:
    """Extrae ofertas de Tecnoempleo en Barcelona (pr=233) usando su JSON-LD JobPosting."""
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for term in terms[:5]:
        list_url = f"https://www.tecnoempleo.com/ofertas-trabajo/?te={requests.utils.quote(term)}&pr={province_code}"
        try:
            r = requests.get(list_url, impersonate="chrome", timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].split("?")[0]
                if "/rf-" in href and href.startswith("https://www.tecnoempleo.com/"):
                    if href not in seen_urls:
                        seen_urls.add(href)
                        links.append(href)

            for detail_url in links[:max_per_term]:
                try:
                    rd = requests.get(detail_url, impersonate="chrome", timeout=12)
                    if rd.status_code != 200:
                        continue
                    sd = BeautifulSoup(rd.text, "html.parser")
                    job_ld = None
                    for sc in sd.find_all("script", type="application/ld+json"):
                        if sc.string and "JobPosting" in sc.string:
                            job_ld = json.loads(sc.string, strict=False)
                            break
                    if not job_ld:
                        continue

                    title = html.unescape(str(job_ld.get("title", "")).strip())
                    org = job_ld.get("hiringOrganization", {})
                    company = org.get("name", "Tecnoempleo") if isinstance(org, dict) else "Tecnoempleo"
                    desc = _html_to_md(str(job_ld.get("description", "")))

                    rows.append({
                        "site": "tecnoempleo",
                        "title": title,
                        "company": html.unescape(str(company).strip()),
                        "location": "Barcelona, Spain",
                        "job_url": detail_url,
                        "job_url_direct": detail_url,
                        "description": desc,
                    })
                    time.sleep(0.4)
                except Exception:
                    continue
        except Exception as exc:
            print(f"[aviso] Tecnoempleo '{term}' falló: {exc}", file=sys.stderr)
    return pd.DataFrame(rows)
