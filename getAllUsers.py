import requests
import time

# Configuration
BOT_TOKEN = "1454028790:AAG9hlnXzgA0uyRsJTkAttLkMWQ480JHXDU"  # Token du bot
USERS = set()  # Utilisé pour stocker les utilisateurs uniques

# Fonction pour écouter les utilisateurs
def listen_for_users(bot_token, offset=None):
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {"offset": offset, "timeout": 10}
    response = requests.get(url, params=params)

    if response.status_code == 200:
        updates = response.json()
        if updates.get("ok"):
            for update in updates["result"]:
                message = update.get("message", {})
                if message:
                    user = message.get("from", {})
                    user_id = user.get("id")
                    user_name = user.get("first_name", "Inconnu")
                    if user_id and user_id not in USERS:
                        USERS.add((user_id, user_name))
                        print(f"Nouvel utilisateur détecté : {user_name} (ID: {user_id})")
                offset = update["update_id"] + 1
    else:
        print(f"Erreur HTTP : {response.status_code} - {response.text}")
    return offset

# Boucle principale pour capturer les utilisateurs
def collect_users(bot_token, duration=60):
    print("Début de la collecte des utilisateurs...")
    offset = None
    start_time = time.time()
    while time.time() - start_time < duration:
        offset = listen_for_users(bot_token, offset)
        time.sleep(1)  # Attente entre les requêtes
    print("Collecte terminée.")
    print("Liste des utilisateurs détectés :")
    for user_id, user_name in USERS:
        print(f" - {user_name} (ID: {user_id})")

# Lancer la collecte
if __name__ == "__main__":
    collect_users(BOT_TOKEN, duration=60)  # Collecter les utilisateurs pendant 60 secondes
