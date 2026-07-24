#!/usr/bin/env python3
"""API web pour check_marque_inpi.py : sert un endpoint JSON consommé par
le frontend statique (frontend/index.html)."""

import os

import requests
from flask import Flask, jsonify, request

from check_marque_inpi import fetch_classes, login, search_marque

app = Flask(__name__)

USERNAME = os.environ.get("INPI_API_USER")
PASSWORD = os.environ.get("INPI_API_PASSWORD")

_session = None


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099, debug=True)
