import requests

# Configuration
BOT_TOKEN = "XXXX:XXXX"
CHAT_ID = "-XXX"  # ID du groupe

# Fonction pour récupérer les administrateurs du groupe
def get_chat_administrators(bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/getChatAdministrators"
    payload = {"chat_id": chat_id}

    response = requests.get(url, params=payload)
    if response.status_code == 200:
        data = response.json()
        if data.get("ok"):
            admins = data["result"]
            print("Liste des administrateurs du groupe :")
            for admin in admins:
                user = admin["user"]
                print(f" - {user.get('first_name', 'N/A')} {user.get('last_name', '')} (ID: {user['id']})")
                print(f"   - Username: {user.get('username', 'N/A')}")
                print(f"   - Status: {admin['status']}")
        else:
            print(f"Erreur de l'API Telegram : {data.get('description')}")
    else:
        print(f"Erreur HTTP : {response.status_code} - {response.text}")

# Appeler la fonction
get_chat_administrators(BOT_TOKEN, CHAT_ID)
