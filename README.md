# naming-tool

Deux scripts pour vérifier la disponibilité d'un nom (marque déposée / raison
sociale déjà utilisée) avant un dépôt de marque ou la création d'une société.

⚠️ **Ces données sont fournies à titre informatif.** Elles ne remplacent pas
une recherche d'antériorité approfondie (orthographique, phonétique,
intellectuelle) avant tout dépôt de marque.

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env   # puis renseigne les clés dont tu as besoin
```

La vérification de domaine (`server.py`, endpoint `/domains`) s'appuie sur le
RDAP et, en repli pour les TLD non couverts (ex. `.eu`), sur la commande
système `whois` (paquet `whois` sur Debian/Ubuntu : `apt install whois`).

## 1. `check_marque_inpi.py` — Base marques (INPI)

Interroge l'API officielle "API PI Marques" de l'INPI (bases FR / EU / WO) et
retourne, pour chaque marque trouvée : numéro de dépôt, statut, déposant et
classes de Nice associées.

**Prérequis** : un compte technique gratuit.
1. Créer un compte sur https://data.inpi.fr/login
2. Dans "Mon espace client" → "Accès APIs PI" (https://data.inpi.fr/espace_personnel/acces),
   activer l'accès **Marques**
3. Suivre le mail d'activation pour définir un mot de passe sur https://api-gateway.inpi.fr/
4. Renseigner `INPI_API_USER` / `INPI_API_PASSWORD` dans `.env` (ou en variables d'env)

```bash
export INPI_API_USER="..."
export INPI_API_PASSWORD="..."

python check_marque_inpi.py "NomDeMarque"
python check_marque_inpi.py "NomDeMarque" --classes 9 41 42
python check_marque_inpi.py "NomDeMarque" --exact
python check_marque_inpi.py "NomDeMarque" --collections FR
```

## 2. `check_nom_sirene.py` — Base entreprises (Sirene)

Vérifie si un nom d'entreprise / raison sociale existe déjà.

- **Par défaut (`--source gouv`)** : utilise `recherche-entreprises.api.gouv.fr`,
  API publique de l'État, **sans clé ni compte à créer**.
- **`--source insee`** : API Sirene officielle de l'INSEE, plus complète,
  nécessite une clé gratuite (compte sur https://portail-api.insee.fr →
  créer une application → souscrire à l'API Sirene, plan "Public").

```bash
python check_nom_sirene.py "NomSociete"
python check_nom_sirene.py "NomSociete" --source insee --exact
```

## Statut

Scripts non testés en conditions réelles (nécessitent des comptes API créés
au préalable). Structure du JSON de réponse à confirmer/ajuster à la première
utilisation réelle.
