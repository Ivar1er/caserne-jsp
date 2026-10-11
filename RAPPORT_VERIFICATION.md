# Vérification de Caserne JSP

Archive de départ : `caserne_jsp.zip`. Audit et corrections du 11 octobre 2026.

## Problèmes corrigés

| Problème initial | Correction |
| --- | --- |
| Pages formateur/JSP bloquées par des `url_for` vers des fonctions absentes | Routes de fiches, notes, cours, évaluations et documents implémentées |
| Champ `centre` utilisé dans les pages mais absent de la base | Champ ajouté avec migration additive |
| Interrupteurs des modules sans effet sur les parcours | Affichage conditionnel et contrôle serveur des dix modules |
| Livret, matériel, statistiques, alertes, trésorerie annoncés sans implémentation | Fonctions utilisables, saisies et suppressions ; exports CSV pour statistiques et trésorerie |
| Suppression de section par requêtes SQL globales sans cascades enfants | Suppression ORM en cascade, contrôlée avec les contraintes de clés étrangères actives |
| Événements réaffectés à un niveau sans mise à jour des participants | Synchronisation des réponses futures / ciblage des nouveaux comptes, conservation de l'historique de niveau |
| Dates incorrectes, notes hors limites, rôles/niveaux non contrôlés | Validation serveur et messages explicites |
| Identifiants sensibles à la casse à la création mais non à la connexion | Contrôle et index d'unicité sans tenir compte de la casse |
| Mot de passe oublié : mot de passe fixe affiché et aucun e-mail envoyé | Lien signé envoyé via SMTP, expiration, révocation après usage, aucun changement avant utilisation |
| Mots de passe initiaux connus et communs | Secrets provisoires individuels, première connexion obligatoire et rotation des anciens mots de passe prédéfinis |
| Formulaires sans protection CSRF, déconnexion par lien GET | Jetons CSRF partout, déconnexion par POST |
| Documents stockés dans `static/`, accès public et écrasement possible | Dossier privé, autorisations par section/destinataire, téléchargement authentifié, noms aléatoires |
| Modification du mot de passe sans contrôle du mot de passe actuel | Vérification hors première connexion et révocation des autres sessions |
| Démarrage Gunicorn et configuration incomplets | `Procfile`, `.python-version`, `.env.example`, commandes d'installation/migration et serveur sans debug |
| Interface dépendant de jsDelivr | Bootstrap servi localement, licence incluse |
| Pilote PostgreSQL `pg8000` 1.31.2 avec avis de vulnérabilité | Mise à jour vers 1.31.5 |

## Résultats

- **86 tests réussis**, dont 3 tests dans Chromium (aucun test ignoré lors de la validation finale).
- Compilation et analyse statique Python : réussies.
- Installation initiale et démarrage Gunicorn avec 2 workers : réussis.
- Audit des dépendances de production : aucun avis de vulnérabilité connu remonté après correction.
- Environnement : Python 3.12.14, Flask 3.1.3, SQLAlchemy 2.0.54, SQLite et Chromium 153.

## Vérifications réalisées

- Tests d'intégration sur SQLite avec contraintes de clés étrangères actives : rôles, sessions, première connexion, profil, mots de passe, SMTP simulé, expiration/réutilisation de liens, création de comptes, sections, niveaux, événements, réponses, documents privés, validation de fichiers, limites de taille, notes, progression, matériel, alertes, trésorerie et exports.
- Migration d'une base reproduisant les anciens champs `user`, vérifiée deux fois pour contrôler son idempotence et la conservation du compte.
- Tests de refus d'accès entre sections, aux documents d'un autre JSP ou à ceux réservés à un autre formateur ; contrôles des modules désactivés côté serveur.
- Suppression d'une section contenant utilisateurs, réponses, notes, documents et données de modules, sans résidus dans les tables ni dans les fichiers déposés.
- Tests Chromium sur les trois espaces, avec formulaires CSRF réels, création de séance, déclaration de présence, ajout de note, dépôt/téléchargement de cours et déconnexion. Vérification des écrans desktop (1280 px) et mobile (390 px), de l'absence de débordement horizontal et d'erreur JavaScript ; contrôle visuel des captures de test.
- Compilation Python, analyse statique, cohérence des dépendances et audit des dépendances de production.

## Limites pratiques

La vérification porte sur le code fourni et sur des données temporaires, sans accès à votre base de production ni à votre hébergeur. PostgreSQL est pris en charge par la configuration et le pilote, mais aucun serveur PostgreSQL réel n'était disponible pour un test de bout en bout. L'envoi SMTP a été contrôlé avec un serveur simulé ; la réception réelle doit être validée une fois votre configuration renseignée. Aucun déploiement sur votre site ou modification de votre dépôt distant n'a été réalisé.

Le livret, l'inventaire et la trésorerie apportent des fonctions de base décrites dans le README, sans certification officielle, attribution individuelle des EPI ni traitement de paiements. Les présences sont déclaratives. Les contrôles réalisés ne constituent pas une garantie d'absence de tout défaut dans tous les environnements.
