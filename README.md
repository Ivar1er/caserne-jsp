# Caserne JSP — installation et mise à jour

Portail Flask en français, avec espaces administrateur, formateur et JSP. Python 3.12, SQLite en local ou PostgreSQL via `pg8000`.

## Démarrage sur Mac / Linux

Dans le dossier `caserne_jsp` :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m flask --app app init-db
python app.py
```

Ouvrir **http://127.0.0.1:5000**. La commande `init-db` affiche le mot de passe provisoire du premier compte **admin**. Conservez-le. À la première connexion, choisissez un nouveau mot de passe d'au moins 10 caractères et renseignez une adresse e-mail. Pour l'admin global, le choix de section sur l'écran de connexion n'a pas d'incidence.

Sous Windows, activer l'environnement avec `.venv\Scripts\activate` et copier `.env.example` en `.env` avec l'explorateur. Utiliser le serveur local `python app.py` ; Gunicorn est destiné à Linux.

## Mise à jour d'une installation existante

1. Arrêter le serveur et sauvegarder **la base réelle**, `.env` et les fichiers déposés. L'archive fournie ne contenait pas votre base ni des documents déposés : ils ne sont pas remplacés par des données de démonstration.
2. Remplacer les sources par celles de cette archive, en conservant `instance/`, `.env`, les fichiers de `static/uploads/` et, si vous utilisez Git, votre dossier `.git/` existant. Retirer les anciens `Procfile.txt`, `runtime.txt` et `templates/manage_users.html`, qui ont été remplacés.
3. Réinstaller les dépendances et vérifier que `.env` utilise la même `DATABASE_URL` et le bon `UPLOAD_FOLDER` persistant.
4. Exécuter **une seule fois avant le redémarrage** :

```bash
python -m flask --app app init-db
python -m flask --app app migrate-uploads
```

`init-db` ajoute les champs `centre` et `auth_version`, crée les nouvelles tables, retire les doublons de réponses et ajoute les index d'unicité. Les tables existantes ne sont pas réinitialisées. Si des identifiants ne diffèrent que par leur casse, la migration signale le conflit : les renommer dans la base sauvegardée avant de relancer. La rotation des anciens mots de passe prédéfinis (`Admin2026!`, `JSPinit2026`, `JSP2026!`) affiche un mot de passe provisoire individuel pour chaque compte concerné ; les conserver et les remettre aux titulaires.

`migrate-uploads` déplace les fichiers de `static/uploads/` vers le dossier privé. Elle refuse d'écraser un fichier existant. Si votre hébergeur sert directement `static/`, supprimer l'ancienne exposition publique des documents après ce déplacement.

Les anciennes sessions sont invalidées à la mise à jour. Les utilisateurs se reconnectent. Un changement de niveau conserve les notes, le livret, les documents et les participations passées ; les inscriptions futures sont mises à jour.

## Utilisation

- **Administrateur** : créer des sections, choisir les dix modules, créer des comptes JSP ou formateur avec leur niveau, réinitialiser un compte, supprimer un utilisateur ou une section. « Ouvrir cette section » permet d'utiliser son espace formateur.
- **Formateur** : publier/modifier/supprimer des événements et séances ; déclarer sa présence ; consulter les réponses ; mettre à jour les fiches des JSP ; publier des cours et évaluations ; enregistrer/supprimer des notes ; renseigner la progression ; gérer un inventaire de matériel et son état ; publier les alertes du portail ; saisir les recettes, dépenses et cotisations ; exporter les statistiques et la trésorerie en CSV.
- **JSP** : consulter les événements de son niveau, déclarer sa présence, retrouver ses notes et sa progression, télécharger les cours et évaluations et transmettre ses documents à tous les formateurs de sa section ou à un seul destinataire.

Un module désactivé masque ses fonctions et interdit aussi les appels directs à ses routes. Les documents individuels sont accessibles à leur propriétaire, au destinataire indiqué ou aux formateurs de la section lorsqu'ils sont partagés, ainsi qu'à l'admin global. Si un formateur destinataire est supprimé, ses documents reçus restent sur les fiches des JSP et redeviennent partagés avec les formateurs de la section.

Les statistiques portent sur les **présences déclarées**, et non sur un émargement réellement vérifié. Le livret permet de saisir librement les unités/compétences ; aucun référentiel officiel de certification n'est intégré. Le matériel est un inventaire de stock et d'état. La trésorerie est un journal de recettes et dépenses, sans paiement en ligne. Les alertes sont affichées dans le portail, sans envoi automatique de SMS ou d'e-mails.

Fichiers autorisés : PDF, PNG/JPG, DOCX, PPTX, XLSX et TXT, jusqu'à 20 Mo par requête. Les fichiers reçoivent des noms aléatoires ; aucun fichier existant n'est écrasé. Les types de documents sont contrôlés. Les téléchargements passent par des routes authentifiées et sont servis comme pièces jointes.

## E-mails de récupération

Renseigner `PUBLIC_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM` et, si nécessaire, `SMTP_USERNAME` / `SMTP_PASSWORD` dans `.env`. Utiliser l'URL **HTTPS** publique du portail. Par défaut : STARTTLS sur le port 587. Pour un serveur SSL sur 465 : `SMTP_SSL=true`, `SMTP_TLS=false`.

Les demandes de récupération envoient un lien signé, valable 30 minutes et invalidé après utilisation. Le mot de passe reste inchangé tant que le lien n'a pas été utilisé. Sans configuration e-mail, le portail invite à contacter l'administrateur et ne prétend pas avoir envoyé un message.

Si vous n'avez plus accès au compte admin :

```bash
python -m flask --app app reset-admin-password --username admin
```

La commande demande et confirme un nouveau mot de passe. La configuration et la réception réelle des e-mails doivent être vérifiées avec votre fournisseur SMTP.

## Hébergement en production

Définir `APP_ENV=production`, une `SECRET_KEY` aléatoire d'au moins 32 caractères, `DATABASE_URL`, `PUBLIC_URL` et un `UPLOAD_FOLDER` absolu sur **disque persistant**. Ne pas mettre de mots de passe dans le dépôt Git. Générer une clé avec :

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

Le fichier `.python-version` sélectionne Python 3.12. Le `Procfile` est correctement nommé et lance Gunicorn. Exécuter la migration `init-db` en tâche de préparation, hors des workers web, avant chaque déploiement nécessitant une mise à jour de schéma. Pour un serveur Linux classique :

```bash
python -m flask --app app init-db
gunicorn app:app --bind 127.0.0.1:8000 --workers 2 --timeout 60
```

Sur une plateforme utilisant `Procfile`, `PORT` doit être fourni par l'hébergeur. Servir en HTTPS. Les cookies de session sont sécurisés en production et ne fonctionneront pas sur une simple URL HTTP. `/health` répond 200 lorsque la base est initialisée, et 503 sinon. Prévoir une sauvegarde de la base et du dossier de documents.

Aucun compte ni schéma n'est créé implicitement par l'import d'`app.py`. Cela évite que plusieurs workers exécutent des migrations ou créent des administrateurs simultanément. Le mode debug est désactivé.

## Vérifications reproductibles

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Les tests utilisent une base et des fichiers temporaires, indépendants de vos données. Les tests dans un vrai navigateur sont facultatifs et nécessitent Chromium :

```bash
python -m playwright install chromium
RUN_BROWSER_TESTS=1 python -m pytest -q
```

Résultats et limites de la vérification : voir `RAPPORT_VERIFICATION.md`. Bootstrap est livré avec l'application pour que son interface ne dépende pas d'un CDN ; sa licence est incluse dans `static/vendor/`.
