import requests

# Configuration
BOT_TOKEN = "YOUR_BOT_TOKEN"  # Remplacez par votre token
CHAT_ID = "YOUR_CHAT_ID"      # ID du chat privé
USER_ID = "YOUR_USER_ID"      # Votre ID Telegram

# Fonction pour générer un lien d'invitation
def generate_invite_link(bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/exportChatInviteLink"
    payload = {"chat_id": chat_id}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        invite_link = response.json().get("result")
        print(f"Lien d'invitation : {invite_link}")
    else:
        print(f"Erreur lors de la génération du lien : {response.status_code} - {response.text}")

# Fonction pour ajouter un utilisateur au chat
def add_user_to_chat(bot_token, chat_id, user_id):
    url = f"https://api.telegram.org/bot{bot_token}/addChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print(f"Utilisateur {user_id} ajouté avec succès au chat {chat_id}")
    else:
        print(f"Erreur lors de l'ajout de l'utilisateur : {response.status_code} - {response.text}")

# Exemple d'utilisation
if __name__ == "__main__":
    # Générer un lien d'invitation
    generate_invite_link(BOT_TOKEN, CHAT_ID)
    
    # Ajouter un utilisateur
     add_user_to_chat(BOT_TOKEN, CHAT_ID, USER_ID)

