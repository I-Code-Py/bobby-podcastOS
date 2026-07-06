# Déploiement sur un VPS (pré-prod ou prod)

Guide pas-à-pas pour mettre l'application en ligne sur un VPS Linux avec
Docker. Chaque commande est expliquée avant d'être donnée : tu les tapes
toi-même, une par une — aucun script à exécuter aveuglément.

Le même setup sert de pré-prod ET de prod : rien ne change dans le code,
seul le serveur (et éventuellement le domaine) change.

---

## 0. Prérequis

- **Un VPS** Debian 12 ou Ubuntu 24.04 chez n'importe quel hébergeur
  (Hetzner, OVH, Scaleway… ~4-6 €/mois). 2 Go de RAM et 20 Go de disque
  suffisent largement pour ~10 clippeurs.
- **L'IP publique** du VPS et l'accès SSH root fournis par l'hébergeur.
- **Un nom de domaine ou sous-domaine** pointant vers cette IP — obligatoire
  pour que Caddy obtienne automatiquement le certificat HTTPS (étape 3).
- **Le code poussé sur GitHub** (étape 4 — à faire depuis ta machine).

---

## 1. Première connexion et sécurisation minimale

Connecte-toi au VPS avec l'IP fournie par l'hébergeur :

```
ssh root@IP_DU_VPS
```

Mets à jour la liste des paquets puis le système (corrige les failles connues
de l'image fournie par l'hébergeur) :

```
apt update
apt upgrade -y
```

Crée un utilisateur de travail non-root (remplace `eugene` si tu veux) et
donne-lui les droits sudo — on ne travaille jamais en root au quotidien :

```
adduser eugene
usermod -aG sudo eugene
```

Installe le pare-feu UFW et n'autorise que SSH (22), HTTP (80) et HTTPS
(443). Le port 80 reste nécessaire : Let's Encrypt s'en sert pour valider le
certificat, et Caddy y redirige automatiquement vers HTTPS :

```
apt install -y ufw
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

(`ufw enable` demande confirmation — vérifie bien que la règle 22/tcp est
listée avant de valider, sinon tu te coupes l'accès SSH.)

Déconnecte-toi et reconnecte-toi avec ton utilisateur :

```
exit
ssh eugene@IP_DU_VPS
```

---

## 2. Installation de Docker

On installe Docker depuis le dépôt officiel Docker (pas le script
`get.docker.com`, comme ça tu vois chaque étape).

Installe les outils nécessaires pour ajouter un dépôt tiers :

```
sudo apt install -y ca-certificates curl gnupg
```

Télécharge la clé de signature officielle de Docker (elle sert à vérifier que
les paquets viennent bien de Docker) :

```
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

> Sur Ubuntu, remplace `debian` par `ubuntu` dans l'URL ci-dessus **et** dans
> la commande suivante.

Déclare le dépôt Docker auprès d'apt (la commande détecte ta version de
Debian toute seule via `VERSION_CODENAME`) :

```
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

Installe Docker et le plugin compose :

```
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Ajoute ton utilisateur au groupe docker pour ne pas taper sudo à chaque
commande docker (nécessite de se déconnecter/reconnecter pour prendre effet) :

```
sudo usermod -aG docker eugene
exit
ssh eugene@IP_DU_VPS
```

Vérifie que tout fonctionne :

```
docker --version
docker compose version
```

---

## 3. DNS : faire pointer un (sous-)domaine vers le VPS

Caddy génère le certificat HTTPS automatiquement, mais il lui faut un nom de
domaine qui pointe vers l'IP du VPS.

**Option A — sous-domaine gratuit (parfait pour la pré-prod)** :
va sur https://www.duckdns.org, connecte-toi, crée un sous-domaine
(ex. `bobbypayout`) et mets l'IP de ton VPS dans le champ « current ip ».
Ton domaine sera `bobbypayout.duckdns.org`.

**Option B — ton propre domaine** : dans l'interface DNS de ton registrar,
crée un enregistrement `A` (ex. `payout.tondomaine.fr`) vers l'IP du VPS.

Vérifie la propagation depuis le VPS (la réponse doit contenir l'IP du VPS) :

```
sudo apt install -y dnsutils
dig +short bobbypayout.duckdns.org
```

---

## 4. Pousser le code sur GitHub (depuis ta machine, pas le VPS)

Crée un repo sur https://github.com/new (privé recommandé — l'outil contient
ta logique de paie), puis depuis le dossier du projet en local :

```
git remote add origin git@github.com:TON_COMPTE/TON_REPO.git
git push -u origin clip-payout-tool
```

(Si tu préfères que `main` soit la branche déployée, fusionne d'abord :
`git checkout main && git merge clip-payout-tool && git push -u origin main`.)

---

## 5. Récupérer le code sur le VPS

Installe git et clone le repo (pour un repo privé, GitHub te demandera un
« personal access token » à la place du mot de passe — à créer dans
GitHub → Settings → Developer settings → Personal access tokens) :

```
sudo apt install -y git
git clone https://github.com/TON_COMPTE/TON_REPO.git bobby-payout
cd bobby-payout
```

Si le code est sur la branche `clip-payout-tool` et pas sur `main` :

```
git checkout clip-payout-tool
```

---

## 6. Configuration `.env`

Copie le modèle :

```
cp .env.example .env
```

Génère une clé secrète forte (signe les cookies de session — si elle fuite,
n'importe qui peut forger une session) :

```
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Génère aussi un mot de passe pour Postgres (même commande, garde les deux
valeurs sous la main).

Édite le fichier :

```
nano .env
```

Variables à modifier — les autres peuvent rester telles quelles :

| Variable | Valeur |
|---|---|
| `SECRET_KEY` | la 1ère valeur générée ci-dessus |
| `POSTGRES_PASSWORD` | la 2ème valeur générée |
| `DATABASE_URL` | remets le **même** mot de passe Postgres dedans : `postgresql+psycopg://bobby:LE_MDP@db:5432/bobby` |
| `APP_DOMAIN` | ton domaine de l'étape 3, ex. `bobbypayout.duckdns.org` |
| `SESSION_SECURE` | `true` (déjà le cas dans l'exemple) |
| `YOUTUBE_API_KEY` | voir ci-dessous |

**Obtenir la clé YouTube (gratuite, 5 min)** : sur
https://console.cloud.google.com → créer un projet → « API et services » →
« Bibliothèque » → activer **YouTube Data API v3** → « Identifiants » →
« Créer des identifiants » → « Clé API ». Le quota gratuit (10 000 unités/jour)
couvre ~10 000 vidéos suivies — très large ici.

---

## 7. Lancement

Construis et démarre les trois conteneurs (app, Postgres, Caddy) en arrière-
plan. Le premier build prend quelques minutes :

```
docker compose up -d --build
```

Vérifie que les trois services tournent (colonne STATUS : `running`, et
`healthy` pour app et db après ~30 s) :

```
docker compose ps
```

Regarde les logs de l'app — tu dois voir les migrations Alembic
(`Running upgrade -> 06d4e2a6e31e`) puis les deux jobs planifiés et
uvicorn qui écoute :

```
docker compose logs app
```

Et les logs de Caddy — tu dois voir l'obtention du certificat
(`certificate obtained successfully`) :

```
docker compose logs caddy
```

---

## 8. Premier compte administrateur

Crée ton compte admin (la commande demande email et mot de passe —
minimum 10 caractères) :

```
docker compose exec app python -m app.cli create-user --admin
```

Ouvre `https://ton-domaine` dans le navigateur : tu dois être redirigé vers
la page de connexion en HTTPS avec un cadenas valide. Connecte-toi, ajoute un
clippeur de test, un clip avec ses URLs, et vérifie que les vues remontent.

---

## 9. Exploitation courante

Suivre les logs en direct (Ctrl-C pour quitter, ça n'arrête pas l'app) :

```
docker compose logs -f app
```

Redémarrer l'application :

```
docker compose restart app
```

**Mettre à jour** après un push sur GitHub :

```
git pull
docker compose up -d --build
```

(Les migrations Alembic s'appliquent automatiquement au démarrage du
conteneur ; la base et ses données ne sont pas touchées par le rebuild.)

**Sauvegarder la base** (à lancer régulièrement — c'est toute ta compta
clippeurs) :

```
docker compose exec db pg_dump -U bobby bobby > backup_$(date +%F).sql
```

Pour automatiser chaque nuit à 2h, ajoute une ligne à ta crontab
(`crontab -e`) :

```
0 2 * * * cd /home/eugene/bobby-payout && docker compose exec -T db pg_dump -U bobby bobby > /home/eugene/backups/bobby_$(date +\%F).sql
```

(crée d'abord le dossier : `mkdir -p /home/eugene/backups` — et pense à
copier ces fichiers hors du VPS de temps en temps.)

**Restaurer** une sauvegarde sur une base vide :

```
docker compose exec -T db psql -U bobby bobby < backup_2026-07-06.sql
```

---

## 10. Passage pré-prod → prod

Rien à changer dans le code. Deux chemins :

- **Le VPS de pré-prod devient la prod** : change juste `APP_DOMAIN` dans
  `.env` pour le domaine définitif, mets à jour le DNS, puis
  `docker compose up -d` (Caddy obtient le nouveau certificat tout seul).
- **Nouveau serveur** : refais les étapes 1-2 et 5-7 sur le serveur neuf,
  restaure le dernier dump (section 9), pointe le DNS vers la nouvelle IP.
