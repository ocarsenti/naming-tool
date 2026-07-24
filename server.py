#!/usr/bin/env python3
"""API web pour check_marque_inpi.py : sert un endpoint JSON consommé par
le frontend statique (frontend/index.html)."""

import os
import re
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, request

from check_marque_inpi import fetch_classes, login, search_marque

app = Flask(__name__)

USERNAME = os.environ.get("INPI_API_USER")
PASSWORD = os.environ.get("INPI_API_PASSWORD")

RDAP_URL = "https://rdap.org/domain/{domain}"
DEFAULT_TLDS = ["com", "fr", "net", "io", "eu"]

# rdap.org route selon le registre bootstrap officiel de l'IANA
# (data.iana.org/rdap/dns.json), qui ne couvre pas tous les TLD (ex. .io,
# .eu en sont absents) : pour ces TLD, rdap.org renvoie un 404 "sec" (sans
# redirection) qui NE VEUT PAS DIRE que le domaine est libre. On court-circuite
# ces cas avec un serveur RDAP connu quand on en a un ; sinon on répond
# 'unknown' plutôt que de mentir.
RDAP_TLD_OVERRIDES = {
    "io": "https://rdap.identitydigital.services/rdap/domain/{domain}",
}

# Repli WHOIS (port 43, commande système `whois`) pour les TLD que le RDAP
# ne sait pas trancher. Format de sortie non standardisé selon le registre :
# heuristique best-effort par motifs de texte plutôt que parsing strict.
WHOIS_NOT_FOUND_PATTERNS = (
    "no match for",
    "not found",
    "no data found",
    "no entries found",
    "no object found",
    "status: available",
    "status: free",
    "is available for registration",
    "no matching record",
)
WHOIS_TAKEN_HINTS = (
    "creation date",
    "registrar:",
    "registrant",
    "name server",
    "domain name:",
    "domain:",
)

_session = None


def slugify_domain_label(nom: str) -> str:
    """Convertit un nom de marque en label de domaine (minuscules,
    sans accents ni espaces, [a-z0-9-] uniquement)."""
    normalized = unicodedata.normalize("NFKD", nom)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    label = re.sub(r"[^a-z0-9-]", "", ascii_only.lower().replace(" ", ""))
    return label.strip("-")


def check_domain_whois(domain: str) -> str:
    """Repli WHOIS quand le RDAP n'a pas pu trancher (TLD hors bootstrap
    IANA, erreur réseau...). Renvoie 'available', 'taken' ou 'unknown'."""
    try:
        proc = subprocess.run(
            ["whois", domain], capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"

    output = proc.stdout.lower()
    if not output.strip():
        return "unknown"
    if any(p in output for p in WHOIS_NOT_FOUND_PATTERNS):
        return "available"
    if any(p in output for p in WHOIS_TAKEN_HINTS):
        return "taken"
    return "unknown"


def check_domain(domain: str) -> str:
    """Interroge le RDAP (successeur du WHOIS, gratuit, sans clé) pour un
    domaine, avec repli WHOIS si le RDAP ne peut pas trancher. Renvoie
    'available', 'taken' ou 'unknown'."""
    tld = domain.rsplit(".", 1)[-1]
    override_url = RDAP_TLD_OVERRIDES.get(tld)

    try:
        url = override_url.format(domain=domain) if override_url else RDAP_URL.format(domain=domain)
        r = requests.get(url, timeout=8, allow_redirects=True)
    except requests.RequestException:
        return check_domain_whois(domain)

    if r.status_code == 200:
        return "taken"
    if r.status_code == 404:
        if override_url or r.history:
            return "available"
        # rdap.org n'a pas redirigé vers un vrai serveur de registre :
        # le TLD n'est probablement pas dans le bootstrap IANA, donc ce
        # 404 ne prouve rien sur la disponibilité réelle du domaine.
        return check_domain_whois(domain)
    return check_domain_whois(domain)


def get_session() -> requests.Session:
    """Renvoie une session INPI authentifiée, en se reloguant si besoin
    (le login initial est fait paresseusement au premier appel)."""
    global _session
    if _session is None:
        _session = requests.Session()
        login(_session, USERNAME, PASSWORD)
    return _session


def reset_session() -> None:
    global _session
    _session = None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/search")
def search():
    nom = request.args.get("nom", "").strip()
    if not nom:
        return jsonify({"error": "Paramètre 'nom' manquant."}), 400

    exact = request.args.get("exact", "false").lower() == "true"
    with_classes = request.args.get("with_classes", "false").lower() == "true"
    collections = request.args.get("collections", "FR,EU,WO").split(",")
    classes_raw = request.args.get("classes", "").strip()
    classes = [c.strip() for c in classes_raw.split(",") if c.strip()] or None

    try:
        session = get_session()
        try:
            data = search_marque(session, nom, collections, classes, exact)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                reset_session()
                session = get_session()
                data = search_marque(session, nom, collections, classes, exact)
            else:
                raise
    except requests.HTTPError as e:
        return jsonify({"error": f"Erreur API INPI : {e}"}), 502
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502

    records = data.get("results") or []
    total = data.get("metadata", {}).get("count", len(records))

    results = []
    for rec in records:
        field_map = {f["name"]: f.get("value") for f in rec.get("fields", [])}
        item = {
            "mark": field_map.get("Mark") or nom,
            "application_number": field_map.get("ApplicationNumber") or rec.get("documentId") or "?",
            "status": field_map.get("MarkCurrentStatusCode") or "?",
            "deposant": field_map.get("DEPOSANT") or "?",
        }
        if with_classes:
            notice_href = (rec.get("xml") or {}).get("href")
            if notice_href:
                try:
                    item["classes"] = fetch_classes(session, notice_href)
                except requests.HTTPError:
                    item["classes"] = None
        results.append(item)

    return jsonify({"nom": nom, "total": total, "count": len(results), "results": results})


@app.get("/domains")
def domains():
    nom = request.args.get("nom", "").strip()
    if not nom:
        return jsonify({"error": "Paramètre 'nom' manquant."}), 400

    tlds_raw = request.args.get("tlds", "").strip()
    tlds = [t.strip().lstrip(".") for t in tlds_raw.split(",") if t.strip()] or DEFAULT_TLDS

    label = slugify_domain_label(nom)
    if not label:
        return jsonify({"error": "Nom de marque invalide pour un domaine (aucun caractère alphanumérique)."}), 400

    domains_to_check = [f"{label}.{tld}" for tld in tlds]
    with ThreadPoolExecutor(max_workers=len(domains_to_check)) as pool:
        statuses = list(pool.map(check_domain, domains_to_check))

    results = [
        {"domain": domain, "tld": tld, "status": status}
        for domain, tld, status in zip(domains_to_check, tlds, statuses)
    ]
    return jsonify({"nom": nom, "label": label, "results": results})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099, debug=True)
