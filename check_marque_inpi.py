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
"""

import argparse
import os
import sys
import requests

BASE = "https://api-gateway.inpi.fr"
AUTHENTICATE_URL = f"{BASE}/services/uaa/api/authenticate"
LOGIN_URL = f"{BASE}/auth/login"
SEARCH_URL = f"{BASE}/services/apidiffusion/api/marques/search"


def login(session: requests.Session, username: str, password: str) -> None:
    """Réalise le flow d'auth INPI : récupère un XSRF-TOKEN puis se logue
    pour obtenir access_token / session_token (stockés comme cookies)."""
    r = session.get(AUTHENTICATE_URL, verify=True, timeout=15)
    r.raise_for_status()
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
    if r.status_code != 200:
        raise RuntimeError(
            f"Échec de connexion à l'API INPI (HTTP {r.status_code}). "
            "Vérifie INPI_API_USER / INPI_API_PASSWORD et que l'accès "
            "'API Marques' est bien activé sur ton compte data.inpi.fr."
        )


def build_query(nom: str, classes, exact: bool) -> str:
    """Construit la requête au format SolR attendu par l'API INPI."""
    nom_clean = nom.strip().replace('"', "")
    if exact:
        mark_clause = f"[Mark_Exp={nom_clean}]"
    else:
        # "commence par" — plus permissif pour repérer les variantes proches
        mark_clause = f"[Mark_Exp={nom_clean}*]"

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
    r.raise_for_status()
    return r.json()


def format_results(nom: str, data: dict) -> str:
    hits = data.get("result") or data.get("results") or data.get("hits") or data
    records = None
    for key in ("marks", "notices", "items", "hits", "content"):
        if isinstance(hits, dict) and key in hits:
            records = hits[key]
            break
    if records is None and isinstance(hits, list):
        records = hits
    if records is None:
        return f"Réponse brute (structure inattendue) :\n{data}"

    if not records:
        return f"Aucune marque trouvée pour « {nom} »."

    lines = [f"{len(records)} résultat(s) pour « {nom} » :\n"]
    for rec in records:
        app_num = rec.get("ApplicationNumber") or rec.get("applicationNumber") or "?"
        mark = rec.get("Mark") or rec.get("mark") or nom
        status = rec.get("MarkCurrentStatusCode") or rec.get("status") or "?"
        deposant = rec.get("DEPOSANT") or rec.get("deposant") or "?"
        raw_classes = rec.get("ClassNumber") or rec.get("classNumber") or []
        if isinstance(raw_classes, (str, int)):
            raw_classes = [raw_classes]
        classes_str = ", ".join(str(c) for c in raw_classes) if raw_classes else "?"
        lines.append(
            f"- {mark}  [{app_num}]  statut={status}  déposant={deposant}  classes={classes_str}"
        )
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

    print(format_results(args.nom, data))


if __name__ == "__main__":
    main()
