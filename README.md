# Telegram-Tools

Ce dépôt contient plusieurs scripts Python qui interagissent avec l'API Telegram Bot pour accomplir diverses tâches telles que la génération de liens d'invitation, la récupération d'informations sur les utilisateurs et les administrateurs, ou encore le transfert et la collecte de messages. Vous trouverez ci-dessous une description de chaque script et de ses fonctionnalités.
Scripts disponibles
1. Génération de liens d’invitation et ajout d’utilisateurs

Fichier concerné : generate_and_add_users.py

Ce script permet de :

    Générer un lien d'invitation pour un groupe ou une discussion.
    Ajouter un utilisateur à un groupe via son identifiant Telegram.

Utilisation :

    Définir les variables BOT_TOKEN, CHAT_ID et USER_ID avec les valeurs correspondantes.
    Exécuter le script pour obtenir un lien d’invitation ou ajouter un utilisateur au chat.

2. Récupération des administrateurs du groupe

Fichier concerné : get_chat_administrators.py

Ce script :

    Utilise l'API Telegram pour lister tous les administrateurs d'un groupe donné.
    Affiche le prénom, le nom, le nom d'utilisateur et le statut de chaque administrateur.

Utilisation :

    Définir BOT_TOKEN et CHAT_ID avec les informations nécessaires.
    Lancer le script pour obtenir une liste des administrateurs du groupe.

3. Surveillance des nouveaux utilisateurs

Fichier concerné : listen_for_users.py

Fonctionnalités :

    Écoute les nouvelles activités dans un chat Telegram.
    Identifie les utilisateurs nouveaux ou inconnus et les enregistre dans une liste.
    Permet de capturer les informations d’utilisateurs sur une période définie.

Utilisation :

    Configurer BOT_TOKEN pour votre bot.
    Lancer le script qui fonctionnera pendant une durée donnée (par exemple, 60 secondes).
    Une fois terminé, il affichera la liste des utilisateurs détectés.

4. Récupération d’un lien d’invitation

Fichier concerné : get_invite_link.py

Ce script :

    Obtient un lien d’invitation pour un groupe Telegram à l’aide de l’API.
    Permet de partager facilement un lien pour inviter de nouveaux membres.

Utilisation :

    Configurer BOT_TOKEN et CHAT_ID dans le script.
    Lancer le script pour récupérer un lien d’invitation valide.

5. Informations sur un membre

Fichier concerné : get_chat_member.py

Fonctionnalités :

    Récupère les détails d’un membre spécifique dans un groupe Telegram.
    Affiche des informations telles que le prénom, le nom, le statut et le nom d’utilisateur.

Utilisation :

    Définir BOT_TOKEN, CHAT_ID, et USER_ID.
    Lancer le script pour afficher les informations de l’utilisateur ciblé.

6. Permissions du bot

Fichier concerné : get_bot_permissions.py

Ce script :

    Vérifie les permissions du bot dans un groupe donné.
    Identifie si le bot est administrateur et affiche ses droits (comme épingler des messages, gérer des utilisateurs, etc.).

Utilisation :

    Passer les arguments nécessaires : -t pour le token, -c pour l’ID du groupe.
    Lancer le script pour voir les droits actuels du bot dans ce groupe.

7. Transfert et collecte de messages

Fichier concerné : forward_and_dump_messages.py

Fonctionnalités :

    Transfère un message Telegram d’un groupe à lui-même.
    Stocke les informations des messages transférés dans un fichier JSON.
    Permet de collecter et de sauvegarder une grande quantité de messages pour analyse ou archivage.

Utilisation :

    Passer les arguments suivants :
        -t ou --token pour le token du bot.
        -c ou --chat pour l’ID du groupe.
        -m ou --message-id pour l’ID du message à partir duquel commencer.
        -o ou --output-file pour spécifier le fichier de sortie.
    Lancer le script pour collecter et enregistrer les messages.

Installation et dépendances

    Prérequis :
        Python 3.x
        requests (bibliothèque Python pour les requêtes HTTP)

    Installation des dépendances :

pip install requests

Exécution :

    python script_name.py

Remarques et conseils

    Sécurité des tokens :
    Les tokens Telegram sont sensibles. Ne partagez pas votre token publiquement et stockez-le dans un endroit sécurisé.

    Gestion des permissions :
    Assurez-vous que votre bot a les permissions nécessaires dans le groupe cible. Par exemple, pour ajouter des utilisateurs ou obtenir des informations sur les membres, le bot doit être administrateur.

    Gestion des erreurs API :
    Si l'API retourne des erreurs (par exemple, un statut HTTP 403 ou 429), vérifiez vos permissions, le chat ID ou attendez avant de réessayer.

En résumé, ces scripts Python offrent une boîte à outils pour interagir avec l’API Telegram, qu’il s’agisse de gérer des utilisateurs, de récupérer des informations sur le groupe, ou d’archiver des messages.
