#!/usr/bin/env python3
"""
Vérifie l'existence d'un nom de marque dans la base INPI (marques FR / EU / WO)
et liste les classes de Nice (produits & services) associées.

Nécessite un compte technique "API PI Marques" (voir data.inpi.fr > Mon espace
client > Accès APIs PI). Identifiants à fournir via variables d'env :
    INPI_API_USER=email_du_compte_technique
    INPI_API_PASSWORD=mot_de_passe

Usage :
    python check_marque_inpi.py "NomDeMarque"
    python check_marque_inpi.py "NomDeMarque" --classes 9 41 42
    python check_marque_inpi.py "NomDeMarque" --exact          # match exact au lieu de "commence par"
    python check_marque_inpi.py "NomDeMarque" --collections FR EU
    python check_marque_inpi.py "NomDeMarque" --with-classes  # ajoute les classes de Nice (plus lent)
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET

import requests

BASE = "https://api-gateway.inpi.fr"
AUTHENTICATE_URL = f"{BASE}/services/uaa/api/authenticate"
LOGIN_URL = f"{BASE}/auth/login"
SEARCH_URL = f"{BASE}/services/apidiffusion/api/marques/search"


DEBUG = os.environ.get("INPI_DEBUG", "").lower() in ("1", "true", "yes")


def _debug(label: str, r: requests.Response) -> None:
    if not DEBUG:
        return
    print(f"[DEBUG] {label}: HTTP {r.status_code}", file=sys.stderr)
    print(f"[DEBUG] {label} headers: {dict(r.headers)}", file=sys.stderr)
    print(f"[DEBUG] {label} cookies après appel: {dict(r.cookies)} / session: {dict(r.request._cookies if hasattr(r.request, '_cookies') else {})}", file=sys.stderr)
    body = r.text[:500]
    print(f"[DEBUG] {label} body (500 premiers car.): {body}", file=sys.stderr)


def login(session: requests.Session, username: str, password: str) -> None:
    """Réalise le flow d'auth INPI : récupère un XSRF-TOKEN puis se logue
    pour obtenir access_token / session_token (stockés comme cookies)."""
    r0 = session.get(AUTHENTICATE_URL, verify=True, timeout=15)
    _debug("GET authenticate", r0)
    xsrf = session.cookies.get("XSRF-TOKEN")
    if not xsrf:
        raise RuntimeError("Pas de XSRF-TOKEN reçu — vérifie que l'endpoint d'auth n'a pas changé.")

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": xsrf,
    }
    r = session.post(
        LOGIN_URL,
        json={"username": username, "password": password, "rememberMe": True},
        headers=headers,
        timeout=15,
    )
    _debug("POST login", r)
    if r.status_code != 200:
        raise RuntimeError(
            f"Échec de connexion à l'API INPI (HTTP {r.status_code}). "
            "Vérifie INPI_API_USER / INPI_API_PASSWORD (ce doivent être les "
            "identifiants du COMPTE TECHNIQUE généré lors de l'activation "
            "'Accès APIs PI' — pas ceux de connexion habituels à data.inpi.fr) "
            "et que l'accès 'API Marques' est bien activé."
        )
    if DEBUG:
        print(f"[DEBUG] cookies de session après login: {dict(session.cookies)}", file=sys.stderr)


def build_query(nom: str, classes, exact: bool) -> str:
    """Construit la requête au format SolR attendu par l'API INPI."""
    nom_clean = nom.strip().replace('"', "")
    # Phrase toujours entre guillemets : un nom multi-mots non quoté est
    # traité comme un OU entre mots-clés par l'API (matches massifs et
    # non pertinents), même pour un seul mot un guillemet évite toute ambiguïté.
    if exact:
        mark_clause = f'[Mark_Exp="{nom_clean}"]'
    else:
        # "commence par" — plus permissif pour repérer les variantes proches
        mark_clause = f'[Mark_Exp="{nom_clean}"*]'

    if classes:
        classes_expr = " OU ".join(classes)
        return f"({mark_clause} ET [ClassNumber=({classes_expr})])"
    return mark_clause


def search_marque(session, nom, collections, classes, exact, size=50):
    xsrf = session.cookies.get("XSRF-TOKEN")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": xsrf,
    }
    payload = {
        "collections": collections,
        "query": build_query(nom, classes, exact),
        "size": size,
    }
    r = session.post(SEARCH_URL, json=payload, headers=headers, timeout=20)
    _debug("POST search", r)
    r.raise_for_status()
    return r.json()


def fetch_classes(session: requests.Session, notice_href: str) -> list:
    """Récupère les classes de Nice d'une marque via sa fiche détaillée (XML)."""
    xsrf = session.cookies.get("XSRF-TOKEN")
    headers = {"Accept": "application/xml, text/xml, */*", "X-XSRF-TOKEN": xsrf}
    r = session.get(notice_href, headers=headers, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return [el.text for el in root.iter("ClassNumber") if el.text]


def format_results(nom: str, data: dict, session: requests.Session = None) -> str:
    records = data.get("results")
    if records is None:
        return f"Réponse brute (structure inattendue) :\n{data}"

    if not records:
        return f"Aucune marque trouvée pour « {nom} »."

    total = data.get("metadata", {}).get("count", len(records))
    lines = [f"{len(records)} résultat(s) affiché(s) sur {total} pour « {nom} » :\n"]
    for rec in records:
        field_map = {f["name"]: f.get("value") for f in rec.get("fields", [])}
        app_num = field_map.get("ApplicationNumber") or rec.get("documentId") or "?"
        mark = field_map.get("Mark") or nom
        status = field_map.get("MarkCurrentStatusCode") or "?"
        deposant = field_map.get("DEPOSANT") or "?"
        line = f"- {mark}  [{app_num}]  statut={status}  déposant={deposant}"
        if session is not None:
            notice_href = (rec.get("xml") or {}).get("href")
            if notice_href:
                try:
                    classes = fetch_classes(session, notice_href)
                    line += f"  classes={', '.join(classes) if classes else '?'}"
                except requests.HTTPError:
                    line += "  classes=erreur"
        lines.append(line)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Vérifie une marque sur la base INPI.")
    parser.add_argument("nom", help="Nom de la marque à rechercher")
    parser.add_argument("--classes", nargs="*", default=None,
                         help="Classes de Nice à filtrer, ex: --classes 9 41 42")
    parser.add_argument("--collections", nargs="*", default=["FR", "EU", "WO"],
                         help="Bases à interroger (FR, EU, WO). Défaut : les trois.")
    parser.add_argument("--exact", action="store_true",
                         help="Recherche exacte au lieu de 'commence par' (défaut).")
    parser.add_argument("--with-classes", action="store_true",
                         help="Récupère les classes de Nice pour chaque résultat "
                              "(1 requête HTTP supplémentaire par marque, plus lent).")
    args = parser.parse_args()

    username = os.environ.get("INPI_API_USER")
    password = os.environ.get("INPI_API_PASSWORD")
    if not username or not password:
        sys.exit(
            "Erreur : définis INPI_API_USER et INPI_API_PASSWORD "
            "(identifiants du compte technique API PI Marques)."
        )

    session = requests.Session()
    try:
        login(session, username, password)
        data = search_marque(session, args.nom, args.collections, args.classes, args.exact)
    except requests.HTTPError as e:
        sys.exit(f"Erreur HTTP : {e}")
    except RuntimeError as e:
        sys.exit(str(e))

    print(format_results(args.nom, data, session if args.with_classes else None))


if __name__ == "__main__":
    main()
