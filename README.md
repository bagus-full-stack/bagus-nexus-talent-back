# NexusTalent API

Backend FastAPI de NexusTalent : recherche de candidats par langage naturel (recherche hybride vecteur + graphe + LLM), ingestion et parsing de CV, gestion RGPD, utilisateurs et notifications.

## Stack

- **FastAPI** (async) + **Uvicorn**
- **PostgreSQL** (`asyncpg` + SQLAlchemy 2.0 async + Alembic) — utilisateurs, CV, demandes RGPD, notifications, réglages
- **Neo4j** — graphe de relations candidats / compétences / entreprises / écoles
- **Qdrant** — recherche vectorielle sur les profils candidats
- **Redis** — broker/backend Celery, tokens de réinitialisation de mot de passe, stockage du rate limiting
- **Celery** (worker + beat) — pipeline d'ingestion CV asynchrone, tâches RGPD planifiées
- **GLiNER** (NER) + **OpenAI/Anthropic** — extraction d'entités et structuration LLM des CV, synthèse des résultats de recherche
- **JWT** (access + refresh) via `python-jose`, mots de passe hashés avec `bcrypt`

## Architecture

```
app/
  core/        config (pydantic-settings), sécurité JWT, dépendances FastAPI (auth/RBAC), rate limiting
  db/          clients Postgres / Neo4j / Qdrant / Redis
  models/      modèles SQLAlchemy (Postgres)
  schemas/     schémas Pydantic (requêtes/réponses API)
  routers/     endpoints FastAPI par domaine
  services/    logique métier (ingestion, recherche hybride, graphe, RGPD, notifications...)
  tasks/       tâches Celery (ingestion, résolution d'entités, nettoyage RGPD)
alembic/       migrations de schéma Postgres
tests/         suite pytest (async, httpx + sqlite in-memory)
```

### Pipeline d'ingestion d'un CV

1. Upload (`POST /api/v1/ingestion/upload`) → fichier stocké sur disque (`CV_STORAGE_DIR`), entrée `CV` créée en base avec statut `en_cours`, tâche Celery déclenchée.
2. Le worker Celery (`app/tasks/ingestion_tasks.py` → `ingestion_service.run_pipeline`) :
   - extrait le texte (PDF/DOCX, fallback OCR via `pdf2image` + `pytesseract` si le texte est vide),
   - détecte la langue, extrait les entités (GLiNER),
   - structure le CV en JSON typé via un LLM,
   - calcule des indicateurs de qualité (`ok` / `a_valider` / `echec_parsing`),
   - indexe le candidat dans Qdrant (embedding) et Neo4j (relations : compétences, expériences, formations),
   - notifie l'utilisateur en cas d'échec.
3. Une entrée `a_valider`/`echec_parsing` peut être corrigée puis validée (`PATCH /api/v1/ingestion/{id}/validate`) ou rejetée (`DELETE /api/v1/ingestion/{id}/reject`).

### Recherche hybride

`POST /api/v1/candidats/search` (`search_service.hybrid_search`) : extraction de filtres depuis la requête en langage naturel → recherche vectorielle Qdrant → enrichissement via le graphe Neo4j → reranking → synthèse justificative par LLM par candidat.

### RGPD

`app/services/gdpr_service.py` : suppression ou anonymisation d'un candidat (Postgres + Neo4j + Qdrant), hash d'audit, et une tâche planifiée hebdomadaire (Celery beat, dimanche 3h) qui nettoie les entités orphelines du graphe.

## Prérequis

- Python 3.13
- Docker + Docker Compose (Postgres, Neo4j, Qdrant, Redis)
- `poppler-utils` et `tesseract-ocr` (fallback OCR) — déjà installés dans l'image Docker ; en local, à installer séparément si besoin.

## Démarrage en local

```bash
# 1. Dépendances Python
python -m venv .venv
source .venv/Scripts/activate   # .venv/bin/activate sous macOS/Linux ; .venv\Scripts\Activate.ps1 sous Windows PowerShell
pip install -r requirements.txt

# 2. Services d'infrastructure (Postgres, Neo4j, Qdrant, Redis)
# docker-compose.yml ne contient QUE l'infra, pas l'API : c'est volontaire, pour
# lancer l'API en local avec rechargement à chaud plutôt que de rebuilder une image
# Docker à chaque changement. Pour tout lancer en Docker, voir "Déploiement" plus bas.
docker compose up -d

# 3. Variables d'environnement
cp .env.example .env
# .env.example est écrit pour docker-compose.prod.yml (hosts = noms de service :
# "postgres", "neo4j", "qdrant", "redis"). Pour une API lancée en local (hors
# Docker) contre l'infra de dev ci-dessus, utiliser "localhost" à la place, avec
# les identifiants codés en dur dans docker-compose.yml :
#   DATABASE_URL=postgresql+asyncpg://nexustalent:nexustalent@localhost:5432/nexustalent
#   NEO4J_URI=bolt://localhost:7687
#   NEO4J_USER=neo4j
#   NEO4J_PASSWORD=neo4jpassword
#   QDRANT_URL=http://localhost:6333
#   REDIS_URL=redis://localhost:6379/0
# (ce sont d'ailleurs les valeurs par défaut de Settings() dans app/core/config.py,
# donc ces lignes peuvent aussi simplement être supprimées de .env).
# Seul JWT_SECRET_KEY est obligatoire (voir commande de génération dans le fichier).

# 4. Migrations de base de données
alembic upgrade head

# 5. Lancer l'API
uvicorn app.main:app --reload

# 6. Lancer le worker Celery (dans un autre terminal, pour l'ingestion de CV et les tâches RGPD)
celery -A app.tasks.celery_app worker --loglevel=info
# + le scheduler, si besoin du nettoyage RGPD planifié
celery -A app.tasks.celery_app beat --loglevel=info
```

L'API est servie sur `http://localhost:8000`, la documentation interactive sur `http://localhost:8000/docs`. Vérifier qu'elle répond : `curl http://localhost:8000/health`.

**Windows / PowerShell** : si `uvicorn` n'est pas reconnu après l'étape 1, c'est que le venv n'est pas activé dans le terminal courant. Deux options :
```powershell
.venv\Scripts\Activate.ps1        # puis lancer les commandes normalement
# ou, sans activer (si la politique d'exécution de scripts bloque Activate.ps1) :
.venv\Scripts\uvicorn.exe app.main:app --reload
```

### Premier utilisateur admin

Aucune migration ne crée de compte par défaut — la table `users` est vide au premier lancement. `create_admin.py` crée un compte admin :

```bash
python create_admin.py
```

Identifiants créés : `admin@nexustalent.app` / `bagus_admin` (modifiables en tête du fichier avant exécution — éviter les TLD réservés comme `.local`, `.internal`, `.test` : rejetés par la validation d'email de l'API). Le script est idempotent : le relancer avec le même email ne fait rien s'il existe déjà. Nécessite `.env` déjà configuré et Postgres accessible.

## Déploiement (Docker Compose prod)

```bash
cp .env.example .env   # renseigner toutes les valeurs, notamment les mots de passe et JWT_SECRET_KEY
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

Ce compose démarre l'API (2 workers Uvicorn), un worker Celery, Celery beat, et les 4 services d'infrastructure avec volumes persistants.

## Variables d'environnement

Voir `.env.example` pour la liste complète et les commentaires. Points clés :

| Variable | Rôle |
|---|---|
| `DATABASE_URL`, `NEO4J_*`, `QDRANT_URL`, `REDIS_URL` | Connexions aux 4 stores |
| `JWT_SECRET_KEY` | **Obligatoire**, sans défaut — génèrer avec `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Paramètres des tokens |
| `CORS_ORIGINS` | Origines frontend autorisées (liste séparée par des virgules), pas de wildcard |
| `RATE_LIMIT_ENABLED` | Active/désactive le rate limiting (Redis) ; désactivé automatiquement dans les tests |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Utilisés pour la structuration des CV et la synthèse de recherche |
| `CV_STORAGE_DIR` | Répertoire de stockage des fichiers CV uploadés |

## Authentification & rôles

JWT Bearer (`Authorization: Bearer <token>`), pas de cookies. Trois rôles (`recruteur`, `rh_interne`, `admin`) :

- `recruteur`, `rh_interne` : recherche, consultation candidats, ingestion de CV, notifications.
- `admin` uniquement : gestion des utilisateurs (`/api/v1/users`), demandes RGPD (`/api/v1/gdpr`).

Flux : `POST /api/v1/auth/login` → `{access_token, refresh_token}` → `POST /api/v1/auth/refresh` pour renouveler l'access token sans se reconnecter.

## Endpoints principaux

| Domaine | Endpoints |
|---|---|
| Auth | `POST /api/v1/auth/login`, `refresh`, `forgot-password`, `reset-password`, `GET /me` |
| Candidats | `POST /api/v1/candidats/search`, `GET /api/v1/candidats/{id}` |
| Ingestion | `POST /api/v1/ingestion/upload`, `GET /`, `GET /{id}`, `GET /{id}/status`, `PATCH /{id}/validate`, `DELETE /{id}/reject` |
| Graphe | `GET /api/v1/graph/subgraph`, `GET /api/v1/graph/node/{id}` |
| RGPD (admin) | `GET/POST /api/v1/gdpr`, `GET /{id}`, `POST /{id}/execute` |
| Utilisateurs (admin) | `GET/POST /api/v1/users`, `invite`, `PATCH /{id}/role`, `DELETE /{id}` |
| Notifications | `GET /api/v1/notifications`, `PATCH /read-all`, `PATCH /{id}/read` |
| Réglages | `GET/POST/DELETE /api/v1/settings/...`, préférences de notification |
| Santé | `GET /health` — vérifie Postgres, Neo4j, Qdrant |

Liste exhaustive et schémas de requête/réponse dans `/docs` (Swagger) une fois l'API démarrée.

## Sécurité

- Rate limiting (Redis, `slowapi`) : 200 req/min par IP par défaut, 5/min sur `login`/`forgot-password`/`reset-password`, 10/min sur `refresh`.
- CORS restreint aux origines listées dans `CORS_ORIGINS` (pas de wildcard avec credentials).
- Mots de passe hashés `bcrypt`, tokens JWT signés avec `JWT_SECRET_KEY` (obligatoire, aucun défaut).

## Tests

```bash
pytest -q
```

La suite utilise SQLite en mémoire pour Postgres et n'a pas besoin de Docker, à l'exception des tests qui exercent explicitement Redis (rate limiting) ou Celery (enregistrement des tâches), couverts en CI (`.github/workflows/ci.yml`) où `docker compose up` fournit les services réels.

```bash
ruff check .   # lint
```

## CI

`.github/workflows/ci.yml` : lint (`ruff`), démarrage des services via Docker Compose, migrations, suite pytest complète, puis un test end-to-end qui dispatch une vraie tâche Celery vers un worker réel pour détecter les régressions d'enregistrement de tâches.
