#!/usr/bin/env python3
"""
Vérifie si un nom d'entreprise / raison sociale existe déjà, via deux sources
possibles :

1) "recherche-entreprises.api.gouv.fr" (par défaut) — API publique de l'État,
   ouverte, SANS clé ni compte à créer. Recommandée pour un premier filtre rapide.

2) L'API Sirene officielle de l'INSEE (api.insee.fr) — plus complète / plus de
   filtres, mais nécessite un compte sur https://portail-api.insee.fr, une
   application, et une souscription à l'API Sirene (clé gratuite, header
   X-INSEE-Api-Key-Integration). Utilise --source insee et la variable d'env
   INSEE_API_KEY.

Usage :
    python check_nom_sirene.py "NomSociete"
    python check_nom_sirene.py "NomSociete" --source insee
    python check_nom_sirene.py "NomSociete" --exact
"""

import argparse
import os
import sys
import requests

GOUV_SEARCH_URL = "https://recherche-entreprises.api.gouv.fr/search"
INSEE_BASE = "https://api.insee.fr/api-sirene/3.11"


def search_gouv(nom: str, size: int = 10) -> list[dict]:
    params = {"q": nom, "per_page": size}
    r = requests.get(GOUV_SEARCH_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    results = data.get("results", [])
    out = []
    for res in results:
        out.append({
            "siren": res.get("siren"),
            "nom": res.get("nom_complet") or res.get("nom_raison_sociale"),
            "activite": res.get("activite_principale"),
            "statut": "actif" if res.get("etat_administratif") == "A" else res.get("etat_administratif"),
        })
    return out


def search_insee(nom: str, api_key: str, exact: bool, size: int = 10) -> list[dict]:
    nom_clean = nom.strip().replace('"', "")
    if exact:
        q = f'denominationUniteLegale:"{nom_clean}"'
    else:
        q = f'denominationUniteLegale:"{nom_clean}"*'
    headers = {
        "X-INSEE-Api-Key-Integration": api_key,
        "Accept": "application/json",
    }
    params = {"q": q, "nombre": size}
    r = requests.get(f"{INSEE_BASE}/siren", headers=headers, params=params, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Erreur API INSEE (HTTP {r.status_code}) : {r.text[:300]}")
    data = r.json()
    units = data.get("unitesLegales", [])
    out = []
    for u in units:
        periode = (u.get("periodesUniteLegale") or [{}])[0]
        out.append({
            "siren": u.get("siren"),
            "nom": periode.get("denominationUniteLegale") or periode.get("nomUniteLegale"),
            "activite": periode.get("activitePrincipaleUniteLegale"),
            "statut": periode.get("etatAdministratifUniteLegale"),
        })
    return out


def main():
    parser = argparse.ArgumentParser(description="Vérifie un nom d'entreprise (base Sirene).")
    parser.add_argument("nom", help="Nom / raison sociale à rechercher")
    parser.add_argument("--source", choices=["gouv", "insee"], default="gouv",
                         help="'gouv' (défaut, sans clé) ou 'insee' (officiel, clé requise)")
    parser.add_argument("--exact", action="store_true",
                         help="Recherche exacte (mode --source insee uniquement)")
    parser.add_argument("--size", type=int, default=10, help="Nombre de résultats max")
    args = parser.parse_args()

    try:
        if args.source == "gouv":
            results = search_gouv(args.nom, args.size)
        else:
            api_key = os.environ.get("INSEE_API_KEY")
            if not api_key:
                sys.exit("Erreur : définis INSEE_API_KEY (clé API Sirene du portail INSEE).")
            results = search_insee(args.nom, api_key, args.exact, args.size)
    except requests.HTTPError as e:
        sys.exit(f"Erreur HTTP : {e}")
    except RuntimeError as e:
        sys.exit(str(e))

    if not results:
        print(f"Aucune entreprise trouvée pour « {args.nom} ».")
        return

    print(f"{len(results)} résultat(s) pour « {args.nom} » (source: {args.source}) :\n")
    for r in results:
        print(f"- {r['nom']}  [SIREN {r['siren']}]  statut={r['statut']}  activité={r['activite']}")


if __name__ == "__main__":
    main()
