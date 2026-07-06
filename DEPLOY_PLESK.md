# Déploiement sur un serveur Plesk (Docker + reverse proxy)

Guide pour héberger l'application sur un serveur Plesk déjà configuré avec
Docker. Chaque commande est expliquée : tu les tapes toi-même.

**Principe.** Sur Plesk, c'est **nginx (géré par Plesk) qui détient les ports
80/443 et le certificat HTTPS** du domaine. On n'utilise donc PAS Caddy ici.
L'app tourne dans Docker et écoute sur un port local (`127.0.0.1:7000`), et on
relie le domaine à ce port depuis l'interface Plesk (« Docker Proxy Rules »).
On utilise le fichier **`docker-compose.plesk.yml`** (app + PostgreSQL, sans
Caddy).

```
Internet ──HTTPS──► nginx de Plesk (443, certificat Let's Encrypt)
                        │  proxy
                        ▼
                 127.0.0.1:7000  ──►  conteneur app (uvicorn:8000)
                                          │
                                          ▼
                                    conteneur db (PostgreSQL, interne)
```

---

## 1. Prérequis côté Plesk

- Un **domaine ou sous-domaine** créé dans Plesk (ex. `payout.tondomaine.fr`),
  avec son DNS qui pointe déjà vers le serveur.
- Le certificat **SSL/TLS Let's Encrypt** activé pour ce domaine
  (Plesk → le domaine → « SSL/TLS Certificates » → installer Let's Encrypt).
  Coche « Redirect from HTTP to HTTPS ».
- L'extension **Docker** installée (tu l'as déjà) et un **accès SSH** au
  serveur (Plesk → Tools & Settings → SSH, ou via ton hébergeur).

---

## 2. Récupérer le code (en SSH)

Connecte-toi au serveur en SSH, puis place le projet dans le dossier de ton
choix (ici sous ton home, hors de l'arborescence web du domaine — le code ne
doit pas être servi en statique) :

```
git clone https://github.com/TON_COMPTE/TON_REPO.git bobby-payout
cd bobby-payout
git checkout clip-payout-tool
```

(Rappel : le code doit d'abord être poussé sur GitHub. Depuis ta machine :
`git remote add origin git@github.com:TON_COMPTE/TON_REPO.git` puis
`git push -u origin clip-payout-tool`.)

---

## 3. Configurer le `.env`

Copie le modèle :

```
cp .env.example .env
```

Génère une clé secrète et un mot de passe Postgres (lance deux fois) :

```
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Édite le fichier :

```
nano .env
```

Valeurs à renseigner :

| Variable | Valeur |
|---|---|
| `SECRET_KEY` | la 1ère valeur générée |
| `POSTGRES_PASSWORD` | la 2ème valeur générée |
| `DATABASE_URL` | le **même** mot de passe Postgres : `postgresql+psycopg://bobby:LE_MDP@db:5432/bobby` |
| `SESSION_SECURE` | `true` (le HTTPS est assuré par Plesk) |
| `APP_PORT` | `7000` (ou un autre port libre si 7000 est pris) |
| `YOUTUBE_API_KEY` | ta clé YouTube Data API v3 (console.cloud.google.com → activer l'API → créer une clé API) |

> `APP_DOMAIN` ne sert pas ici (c'était pour Caddy) — tu peux le laisser tel quel.

---

## 4. Lancer les conteneurs — commandes docker compose

Toutes les commandes ci-dessous utilisent le fichier Plesk avec l'option
`-f docker-compose.plesk.yml`.

**Construire et démarrer** (app + base) en arrière-plan :

```
docker compose -f docker-compose.plesk.yml up -d --build
```

**Vérifier que les deux services tournent** (STATUS `running`, la base
`healthy` après ~30 s) :

```
docker compose -f docker-compose.plesk.yml ps
```

**Regarder les logs de l'app** — tu dois voir les migrations Alembic
(`Running upgrade -> 06d4e2a6e31e`), les deux jobs planifiés, puis uvicorn
qui écoute sur le port 8000 :

```
docker compose -f docker-compose.plesk.yml logs app
```

**Tester en local sur le serveur** que l'app répond bien sur le port publié
(doit renvoyer `{"status":"ok"}`) :

```
curl http://127.0.0.1:7000/health
```

---

## 5. Relier le domaine à l'app dans l'interface Plesk

Deux méthodes selon ta version de Plesk. **Essaie la A d'abord.**

### Méthode A — Docker Proxy Rules (le plus simple)

1. Plesk → **Websites & Domains** → ton domaine.
2. Ouvre **« Docker Proxy Rules »** (ou « Règles de proxy Docker »).
3. Clique **Add Rule** :
   - **Container** : sélectionne le conteneur de l'app (nom du type
     `bobby-payout-app-1`).
   - **Container port** / **Port** : `8000` (le port interne d'uvicorn).
   - Laisse le chemin sur `/`.
4. Applique. Plesk configure nginx pour envoyer le domaine vers le conteneur.

Ouvre `https://payout.tondomaine.fr` : tu dois arriver sur la page de
connexion, en HTTPS, avec un cadenas valide.

### Méthode B — Directive nginx (si la méthode A n'est pas disponible)

1. Plesk → ton domaine → **Apache & nginx Settings**.
2. Dans **« Additional nginx directives »**, colle (adapte le port si tu as
   changé `APP_PORT`) :

   ```
   location / {
       proxy_pass http://127.0.0.1:7000;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

3. **Applique**. Le header `X-Forwarded-Proto` est important : il indique à
   l'app que la requête d'origine était en HTTPS (cookies de session
   sécurisés). uvicorn le respecte déjà (`--proxy-headers`).

---

## 6. Créer le premier compte administrateur

```
docker compose -f docker-compose.plesk.yml exec app python -m app.cli create-user --admin
```

La commande demande un email et un mot de passe (min. 10 caractères).
Connecte-toi ensuite sur `https://payout.tondomaine.fr`, ajoute un clippeur,
un clip avec ses URLs, et vérifie que les vues remontent.

---

## 7. Exploitation courante (toujours avec `-f docker-compose.plesk.yml`)

Suivre les logs en direct (Ctrl-C pour quitter sans arrêter l'app) :

```
docker compose -f docker-compose.plesk.yml logs -f app
```

Redémarrer l'app :

```
docker compose -f docker-compose.plesk.yml restart app
```

**Mettre à jour** après un push sur GitHub (les migrations s'appliquent
automatiquement au redémarrage, les données sont conservées) :

```
git pull
docker compose -f docker-compose.plesk.yml up -d --build
```

Arrêter / tout relancer :

```
docker compose -f docker-compose.plesk.yml down
docker compose -f docker-compose.plesk.yml up -d
```

**Sauvegarder la base** (à faire régulièrement, c'est ta compta clippeurs) :

```
docker compose -f docker-compose.plesk.yml exec db pg_dump -U bobby bobby > backup_$(date +%F).sql
```

Automatiser chaque nuit à 2h (`crontab -e`, adapte le chemin du projet) :

```
0 2 * * * cd /var/www/vhosts/CHEMIN/bobby-payout && docker compose -f docker-compose.plesk.yml exec -T db pg_dump -U bobby bobby > ~/bobby_$(date +\%F).sql
```

**Restaurer** un dump :

```
docker compose -f docker-compose.plesk.yml exec -T db psql -U bobby bobby < backup_2026-07-06.sql
```

---

## Dépannage

- **502 Bad Gateway sur le domaine** : l'app n'écoute pas / mauvais port.
  Vérifie `docker compose -f docker-compose.plesk.yml ps` et
  `curl http://127.0.0.1:7000/health`. Vérifie que le port de la règle de
  proxy (méthode A : `8000` conteneur / méthode B : `7000` hôte) est cohérent.
- **Boucle de redirection ou cookie refusé au login** : le header
  `X-Forwarded-Proto` n'arrive pas jusqu'à l'app. En méthode A c'est
  automatique ; en méthode B, vérifie que la ligne `proxy_set_header
  X-Forwarded-Proto $scheme;` est bien présente.
- **Le port 7000 est déjà pris** : change `APP_PORT` dans `.env`, refais
  `docker compose -f docker-compose.plesk.yml up -d`, et mets à jour le port
  dans la règle de proxy (méthode B).
