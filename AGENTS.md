# AGENTS.md — asf-downloader

Ce document décrit le projet `asf-downloader`, ses conventions de code, son périmètre et son
plan de développement. Il est destiné à tout agent (humain ou IA) qui contribue au dépôt.

---

## 1. Écosystème : deux dépôts indépendants

Le projet global est volontairement scindé en **deux dépôts Git indépendants**, ayant chacun
leur cycle de release, leur CI et leur licence.

| Dépôt | Rôle | Dépend de | Statut |
|---|---|---|---|
| [`metadata-asf`](https://github.com/umr-lops/metadata-asf) | Collecte et export des **métadonnées** ASF (recherche, extraction, Parquet) | — | Dépôt compagnon |
| `asf-downloader` | **Téléchargement** des produits ASF (listing Parquet → produits sur disque) | `metadata-asf` (catalogue Parquet) | **Ce dépôt** — en développement |

### Frontière fonctionnelle

- **metadata-asf** : lecture seule, requêtes API légères, sortie Parquet (Ko–Mo).
- **asf-downloader** : authentification Earthdata, I/O lourd, sortie produits HDF5 (Go–To).
- Le catalogue produit par `metadata-asf` (fichiers Parquet) est le **contrat d'interface** :
  la colonne `granule_id` est la clé de téléchargement. `asf-downloader` ne fait **aucune
  recherche** par date/géométrie — il télécharge ce qui est listé.

> **Règle d'or :** si une fonctionnalité cherche/interroge le catalogue ASF, elle n'a rien à
> faire ici. Elle appartient à `metadata-asf`.

> Note : le dépôt de téléchargement était initialement nommé `fetch-asf` dans les docs de
> `metadata-asf` ; il a été renommé `asf-downloader` (décision utilisateur, 2026-11-03). Les
> références `fetch-asf` restantes dans `metadata-asf` seront mises à jour ultérieurement.

---

## 2. Objectif du projet `asf-downloader`

Fournir une bibliothèque Python 3 et une CLI pour **télécharger les produits NISAR RSLC/GSLC**
en partant d'une liste de produits (les catalogues Parquet journaliers de `metadata-asf`).

### Périmètre fonctionnel

- **Fournisseur** : ASF, via `asf_search`.
- **Mission** : `NISAR` (première et seule mission ciblée pour l'instant).
- **Produits** : **L1 — RSLC**, **L2 — GSLC** (fichiers HDF5, plusieurs Go chacun).
- **Source de listing** : catalogues Parquet `{mission}_ocean_YYYYMMDD.parquet` (colonne
  `granule_id`).
- **Transport** : backend **HTTPS** (asf_search) aujourd'hui ; interface de transport
  extensible pour un futur backend **S3** (in-cloud uniquement — voir §6).
- **Archivage** : entry point `nisar-archive` qui déplace les produits `.h5` d'un spool vers
  `<archive>/<PT>/<AM>/<YYYY>/<MM>/<DD>/` (PT = type de produit, AM = code mode d'acquisition,
  date = début d'acquisition), piloté par un listing txt/csv — parsing du nom de fichier,
  aucune API réseau.
- **Réseau** : authentification Earthdata (EDL) via `~/.netrc` (méthode recommandée ASF) ou via
  la variable d'environnement `ASF_EDL_TOKEN`. **Aucun secret dans le dépôt.**

### Hors périmètre (explicitement)

- Recherche/découverte de produits (dates, géométrie, WKT) → `metadata-asf`.
- Traitement scientifique des données SAR.
- Accès S3 direct **hors AWS us-west-2** (impossible — les credentials temporaires n'autorisent
  l'accès qu'au sein de la région us-west-2).
- Autres niveaux NISAR (RIFG, RUNW, ROFF, GUNW, GCOV, GOFF, RRSD, SME2) — au moins
  dans un premier temps.

---

## 3. Conception multi-missions

Comme `metadata-asf`, chaque mission est décrite par un **profil** (un module par mission) :

- `name` — identifiant CLI (ex. `NISAR`)
- `asf_dataset` — valeur passée aux recherches `asf_search`
- `supported_products` — liste de `(processing_level, product_type)`
- `s3_prefixes` — mapping `product_type -> {maturité -> préfixe S3}`, consommé par le futur
  backend S3

Les profils vivent dans `src/asf_downloader/profiles/` (un module par mission). Ajouter une
mission = ajouter un module + un test + une entrée dans le registre `MISSIONS`.

---

## 4. Interface CLI

Le package expose une commande `asf-downloader` avec un sous-commande `download` :

| Option | Type | Requis | Description |
|---|---|---|---|
| `--catalog` | `Path` | oui | Fichier Parquet `metadata-asf`, ou répertoire de tels fichiers |
| `--outputdir` | `Path` | oui | Répertoire de sortie des produits (créé s'il manque) |
| `--mission` | `str` | non | Mission cible (défaut : `NISAR`) |
| `--backend` | `str` | non | Backend de transport (défaut : `https`) |
| `--processes` | `int` | non | Workers de téléchargement parallèles (défaut : `3`) |
| `--product-types` | `list[str]` | non | Filtre sur les types de produits (ex. `RSLC GSLC`) |
| `--overwrite` | `flag` | non | Ré-télécharger les produits déjà présents |
| `--log-verbosity` | `str` | non | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` (défaut : `INFO`) |
| `--conf` | `Path` | non | Fichier de configuration YAML |

Exemple :

```bash
asf-downloader download \
  --catalog /data/nisar_catalog \
  --outputdir /data/nisar \
  --log-verbosity INFO \
  --conf config.yaml
```

Priorité : `CLI > fichier --conf > valeurs par défaut`.

Codes de sortie : `0` succès (tous produits téléchargés ou déjà présents), `1` erreur
d'exécution (au moins un produit en échec, ou erreur API), `2` usage invalide (arguments
invalides, mission/backend inconnu, catalogue manquant/illisible).

### Entry point `nisar-archive`

Deuxième console script du package (`asf_downloader.nisar_archive:main`) :

| Option | Type | Requis | Description |
|---|---|---|---|
| `--input-listing` | `Path` | oui | Listing des produits à archiver (txt/csv, un `.h5` par ligne, avec ou sans extension) |
| `--config-path` | `Path` | oui | Fichier YAML (`spool`, `archive_dir`, `log_level`) — voir `archive.example.yaml` |
| `--log-level` | `str` | non | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

Comportement : seuls les produits du listing sont déplacés du spool vers
`<archive_dir>/<PT>/<AM>/<YYYY>/<MM>/<DD>/<fichier>.h5` (PT = champ 4 du nom NISAR, AM =
champ 9, date = champ 12). Fichier `NISAR_` illisible ou non listé → `<archive_dir>/quarantine/` ;
fichier non NISAR → ignoré. Re-exécution idempotente (destination de même taille = skip).
Codes de sortie : `0` tout archivé, `1` au moins un produit manquant ou en quarantaine,
`2` usage invalide.

> **Config opérationnelle partagée** : un même YAML peut servir les deux commandes
> (`config_production_hpc.yaml` en production HPC). Les clés d'un fichier qui ne sont pas
> des champs du modèle consommé sont **ignorées avec un warning** (
> `asf_downloader.utils.warn_unknown_keys`) — mais les champs requis du modèle courant
> doivent toujours être présents. Un seul fichier de config opérationnel vit hors du dépôt,
> sous `/scale/project/lops-siam-airflow/configs_exploit/asf-downloader/`.

---

## 5. Stack technique

- **Python** ≥ 3.10
- **Runtime** :
  - `asf_search` — client officiel de l'API ASF (recherche + téléchargement HTTPS)
  - `pandas` / `pyarrow` — lecture des catalogues Parquet
  - `pydantic` (v2) — validation de la configuration
  - `pyyaml` — lecture du fichier `--conf`
  - `tenacity` — retry exponentiel sur les appels réseau/API
  - `tqdm` — (réservé ; les logs par produit passent par `logging`)
- **Dev** : `ruff`, `black`, `mypy`, `pytest`, `pytest-cov`, `pre-commit`
- **Logging** : module `logging` standard, sortie sur `stdout`.

---

## 6. Backend de transport (couche extensible)

La couche de transport est **isolée** derrière l'interface abstraite
`asf_downloader.transfer.base.TransferBackend` :

- `download(granule_ids, destination, *, processes, skip_existing) -> list[TransferResult]`
- `TransferResult` = `(granule_id, status ∈ {downloaded, skipped, failed}, path, size, error)`

Les backends enregistrés vivent dans `asf_downloader.transfer.BACKENDS` et sont instanciés par
`asf_downloader.transfer.get_backend(name)`.

| Backend | Statut | Notes |
|---|---|---|
| `https` | **implémenté** | asf_search, batch `granule_search` par chunks de 250, pool de threads, retry. Utilisable depuis notre HPC on-prem. |
| `s3` | **planifié** | AWS S3 direct (Earthdata Cloud). **Région us-west-2 uniquement** (credentials temporaires 1 h, pas de cross-bucket copy). À implémenter uniquement si on passe du calcul in-cloud. Les préfixes sont déjà dans le profil NISAR (`s3_prefixes`). |

Voir [`docs/download_options.md`](docs/download_options.md) pour l'analyse complète des options
de téléchargement, des credentials et des quotas.

> **Règle :** la CLI et la logique catalogue ne dépendent que de `TransferBackend` /
> `TransferResult`. Ajouter un backend ne doit jamais obliger à toucher à `cli.py` ni à
> `catalog.py`.

---

## 7. Conventions de code

- **Style** : `black` (line-length 100) + `ruff`.
- **Typage** : annotations obligatoires sur toutes les fonctions publiques ; `mypy --strict`
  doit passer sur `src/` et `tests/`.
- **Imports** : triés par `ruff` (isort intégré).
- **Logging** : `logger = logging.getLogger(__name__)` par module. Aucun `print()` sauf dans
  `cli.py` (résumé final).
- **Erreurs** : exceptions explicites (`CatalogError`, `UnknownMissionError`,
  `UnknownBackendError`), jamais de `except:` nu.
- **Docstrings** : format Google, en anglais (README, docs publiques et docstrings en anglais ;
  ce AGENTS.md en français, comme `metadata-asf`).
- **Pas de code mort** : imports et variables inutilisés supprimés.
- **Aucun secret** : ni credential EDL, ni clé API dans le code, la config de démo ou les logs.

---

## 8. Structure du dépôt

```text
asf-downloader/
├── AGENTS.md
├── README.md
├── Makefile
├── pyproject.toml
├── .pre-commit-config.yaml
├── config.example.yaml       # config de download
├── archive.example.yaml      # config de nisar-archive (spool, archive_dir, log_level)
├── apptainer.def
├── docs/
│   ├── download_options.md   # analyse des options de téléchargement (réf. de conception)
│   ├── conf.py / index.rst / api.rst
├── src/
│   └── asf_downloader/
│       ├── __init__.py          # réexport de l'API publique
│       ├── cli.py               # argparse (sous-commande download) + orchestration
│       ├── nisar_archive.py     # entry point nisar-archive (spool → <PT>/<AM>/<YYYY>/<MM>/<DD>/)
│       ├── config.py            # modèle Pydantic Config + config_from_yaml
│       ├── catalog.py           # lecture du listing Parquet (metadata-asf)
│       ├── transfer/
│       │   ├── __init__.py      # registre BACKENDS + get_backend()
│       │   ├── base.py          # TransferBackend (ABC) + TransferResult
│       │   └── https.py         # backend HTTPS (asf_search)
│       ├── profiles/
│       │   ├── __init__.py      # registre MISSIONS + get_profile()
│       │   ├── base.py          # MissionProfile
│       │   └── nisar.py         # profil NISAR (RSLC, GSLC, s3_prefixes)
│       └── utils.py             # setup_logging
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_catalog.py
    ├── test_transfer.py
    ├── test_cli.py
    ├── test_nisar_archive.py
    └── test_profiles.py
```

---

## 9. Plan de développement

### Étape 1 — Bootstrap ✅
- [x] Dépôt initialisé (hatchling, hatch-vcs, entry-point CLI, ruff/black/mypy/pytest, pre-commit)
- [x] Arborescence `src/asf_downloader/` + `tests/`
- [x] `docs/download_options.md` (analyse des options de téléchargement, credentials, quotas)
- [x] Backend `https` (asf_search) + interface `TransferBackend`
- [x] CLI `download`, config Pydantic, lecture catalogue Parquet
- [x] Tests unitaires (couverture ≥ 80 %), ruff/black/mypy verts

### Étape 2 — Durcissement & packaging (à faire)
- [x] Entry point `nisar-archive` (spool → `<PT>/<AM>/<YYYY>/<MM>/<DD>/`, quarantaine, tests)
- [ ] Test d'intégration `@pytest.mark.integration` (vrai appel ASF + petit téléchargement)
- [ ] Mesurer taille/checksum réels d'un produit NISAR RSLC/GSLC (réf. quotas)
- [ ] `apptainer.def` vérifié en build
- [ ] README : exemples détaillés + section déploiement HPC/Airflow
- [ ] Docs Sphinx finalisées (`docs/`)

### Étape 3 — Backend S3 (si et seulement si calcul in-cloud)
- [ ] `transfer/s3.py` : credentials temporaires EDL, `boto3`, préfixes du profil NISAR
- [ ] Tests + doc ; à activer uniquement pour un usage AWS us-west-2

---

## 10. Checklist avant commit

- [ ] `ruff check .` passe
- [ ] `black --check .` passe
- [ ] `mypy --strict src tests` passe
- [ ] `pytest` passe (couverture ≥ 80 %)
- [ ] Aucun `print()` résiduel (hors `cli.py`)
- [ ] Aucun secret, aucune clé API dans le code
- [ ] Docstrings à jour sur les fonctions publiques modifiées
- [ ] `AGENTS.md` mis à jour si le périmètre change

---

## 11. Points d'attention

- **Auth EDL** : `~/.netrc` recommandé (host `urs.earthdata.nasa.gov`) ; sinon `ASF_EDL_TOKEN`.
  Ne jamais committer de credentials.
- **Volume** : un RSLC/GSLC NISAR fait plusieurs Go. Prévoir disque et temps ; ne pas saturer le
  réseau (garder `processes` bas).
- **Batch API** : toujours grouper les `granule_id` en un seul `granule_search` par chunk
  (250), jamais une requête par produit.
- **S3** : région us-west-2 uniquement, credentials 1 h, pas de cross-bucket copy → ne pas
  exposer un backend S3 pour un usage on-prem.
- **Contrat Parquet** : si `metadata-asf` change sa colonne `granule_id`, prévenir ici (bump
  SemVer).
- **Maturité des données NISAR** : collections BETA et PROVISIONAL coexistent ; le listing
  `metadata-asf` est source de vérité, le téléchargeur ne filtre pas par maturité.
