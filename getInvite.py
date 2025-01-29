import requests

# Configuration
BOT_TOKEN = "7749516098:AAGu1gvQhJBJWroNByC0peswDlM8FRG478Y"  # Token de votre bot
CHAT_ID = "7422779400"  # ID du groupe (commence par un "-")

# Fonction pour récupérer un lien d'invitation
def get_invite_link(bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/exportChatInviteLink"
    payload = {"chat_id": chat_id}

    response = requests.post(url, data=payload)
    if response.status_code == 200:
        data = response.json()
        if data.get("ok"):
            invite_link = data["result"]
            print(f"Lien d'invitation récupéré avec succès : {invite_link}")
            return invite_link
        else:
            print(f"Erreur de l'API Telegram : {data.get('description')}")
    else:
        print(f"Erreur HTTP : {response.status_code} - {response.text}")

# Récupérer le lien d'invitation
get_invite_link(BOT_TOKEN, CHAT_ID)
