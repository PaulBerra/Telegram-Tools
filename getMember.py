import requests

# Configuration
BOT_TOKEN = "XXXX:XXXX"
CHAT_ID = "-XXXX"  # ID du groupe
USER_ID = "XXXX"  # Remplacez par l'ID de l'utilisateur

# Fonction pour récupérer les informations d'un membre
def get_chat_member(bot_token, chat_id, user_id):
    url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id}

    response = requests.get(url, params=payload)
    if response.status_code == 200:
        data = response.json()
        if data.get("ok"):
            member = data["result"]
            user = member["user"]
            print(f"Informations sur l'utilisateur :")
            print(f" - Prénom : {user.get('first_name', 'N/A')}")
            print(f" - Nom : {user.get('last_name', 'N/A')}")
            print(f" - Username : {user.get('username', 'N/A')}")
            print(f" - Statut dans le groupe : {member.get('status', 'N/A')}")
        else:
            print(f"Erreur de l'API Telegram : {data.get('description')}")
    else:
        print(f"Erreur HTTP : {response.status_code} - {response.text}")

# Appeler la fonction
get_chat_member(BOT_TOKEN, CHAT_ID, USER_ID)
