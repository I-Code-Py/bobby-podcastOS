# Bobby San Podcast — Clip Payout Tool

Outil de gestion de la rémunération des clippeurs : on assigne à chaque
clippeur ses **comptes réseaux** (chaîne YouTube, profil TikTok, profil
Instagram), l'outil scrape **toutes les vidéos de chaque compte**, somme les
vues, et calcule le montant dû à chaque clippeur (taux configurable, défaut
**1 € / 1000 vues**) — sans jamais payer deux fois les mêmes vues.

Premier module d'une future suite de gestion du podcast (architecture
monolithe modulaire : les prochains modules s'ajouteront sous `app/modules/`).

## Fonctionnement

- **Clippeur** → on lui assigne un ou plusieurs **comptes** (une URL de profil
  par plateforme). Un même clippeur peut avoir plusieurs comptes.
- **Vues** : toutes les vidéos publiques de chaque compte sont scrapées chaque
  nuit à 3h — YouTube/TikTok via **yt-dlp**, Instagram via un **navigateur
  headless** (Playwright, page publique du profil + scroll, comme un
  visiteur normal). Aucune connexion à un compte, donc aucun risque de ban.
  Le total du compte = somme des vues de ses vidéos. Si le scraping échoue
  3 fois, le compte bascule en **saisie manuelle** : on entre le total à la main.
- **Seuil de comptabilisation** : les vidéos sous un seuil de vues (défaut
  **1000**, réglable dans Paramètres) ne sont pas comptées dans le total ni
  dans les paiements.
- **Historique & évolution** : chaque scraping enregistre les vues du jour,
  par compte **et par vidéo**. La page « Évolution » d'un clippeur montre des
  courbes : total du clippeur jour par jour, total par compte, et la tendance
  de chaque vidéo avec sa croissance.
- **Récap hebdomadaire** : généré chaque **dimanche à 18h** — pour chaque
  clippeur, les nouvelles vues depuis son dernier paiement (delta par compte)
  et le montant dû. Le bouton « Marquer payé » fige le compteur : le récap
  suivant ne comptera que les vues gagnées après.

## Démarrage (production, Docker)

> Guide détaillé commande par commande :
> - VPS neuf (Docker + Caddy HTTPS) : **[DEPLOY.md](DEPLOY.md)**
> - Serveur **Plesk** (Docker + reverse proxy Plesk) : **[DEPLOY_PLESK.md](DEPLOY_PLESK.md)**

```bash
cp .env.example .env
# Éditer .env : SECRET_KEY, mots de passe Postgres, APP_DOMAIN

docker compose up -d --build

# Créer le premier compte administrateur
docker compose exec app python -m app.cli create-user --admin
```

L'app est servie en HTTPS par Caddy (certificat automatique Let's Encrypt)
sur le domaine `APP_DOMAIN`. Les migrations Alembic s'appliquent au démarrage
du conteneur.

## Développement local (sans Docker)

```bash
pip install -r requirements-dev.txt
cat > .env <<'EOF'
DATABASE_URL=sqlite:///./data/app.db
SECRET_KEY=dev-secret
SESSION_SECURE=false
EOF
alembic upgrade head
python -m app.cli create-user --admin
uvicorn app.main:app --reload
```

## CLI

```bash
python -m app.cli create-user [--admin]   # créer un utilisateur
python -m app.cli refresh-views           # rafraîchir les vues maintenant
python -m app.cli weekly-payout           # générer le récap maintenant
```

Ces actions existent aussi en boutons dans l'écran Paramètres.

## Tests

```bash
python -m pytest tests/
```

## Sécurité

- Comptes multi-utilisateurs (rôles admin / lecture seule), mots de passe
  hachés en argon2, sessions signées (cookies HttpOnly/Secure/SameSite).
- Protection CSRF sur tous les formulaires, rate-limit sur le login.
- HTTPS terminé par Caddy, headers de sécurité, conteneur non-root,
  aucun secret dans le code (tout passe par `.env`).

## Limites connues

- Le scraping peut casser quand une plateforme change son site (structure HTML
  ou API interne). Le compte bascule alors en « à saisir manuellement » avec
  un badge dans l'UI ; on entre le total de vues à la main et un bouton
  « Rafraîchir » retente le scraping.
- Instagram tourne via un navigateur headless (Playwright + Chromium) plutôt
  que yt-dlp : plus fiable pour lister un profil sans compte, mais plus lourd
  (image Docker plus grosse, build plus long, plus de mémoire au scraping).
  Reste le connecteur le plus fragile des trois si Instagram change sa page.
- Le total d'un compte dépend de ce que le scraping remonte : si une plateforme
  ne renvoie qu'une partie des vidéos, le total est sous-estimé. Le nombre de
  vidéos suivies est affiché sur la fiche du compte pour repérer un écart.
- Le scheduler tourne dans le process de l'app : le conteneur doit rester
  actif en continu (c'est le cas avec `restart: unless-stopped`).
