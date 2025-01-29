import requests
import argparse
# Configuration
parser = argparse.ArgumentParser()
parser.add_argument('-t', dest='BOT_TOKEN', type=str, required=True, help="Le token du bot")
parser.add_argument('-c', dest='CHAT_ID', type=str, required=True, help="L'ID du chat (avec le -)")

parser.add_argument('-v', dest='verbose', action='store_true', help="Mode verbeux")
args = parser.parse_args()

BOT_TOKEN = args.BOT_TOKEN   # Token de votre bot
CHAT_ID = args.CHAT_ID  # ID du groupe (commence par un "-")
BOT_USER_ID = BOT_TOKEN.split(':')[0]
verbose = args.verbose

# Fonction pour récupérer les informations du bot dans le groupe
def get_bot_permissions(bot_token, chat_id, bot_user_id):
    url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
    payload = {"chat_id": chat_id, "user_id": bot_user_id}
    response = requests.get(url, params=payload)
    if response.status_code == 200:
        data = response.json()
        if verbose == True:
            print("url :", url)
            print("payload :", payload)
            print("response :", response)
        if data.get("ok"):
            member_info = data["result"]
            print(f"Informations sur le bot [", member_info['user']['id'], "] dans le groupe :")
            print(f" - Status : ", member_info['status'])  # Ex. "administrator" ou "member"
            print(f" - Bot : ", member_info['user']['is_bot'])
            print(f" - First Name : ", member_info['user']['first_name'])
            print(f" - Username : ", member_info['user']['username'])
            if member_info["status"] == "administrator":
                permissions = member_info.get("can_be_edited", False)
                admin_rights = {
                    "can_change_info": member_info.get("can_change_info", False),
                    "can_post_messages": member_info.get("can_post_messages", False),
                    "can_edit_messages": member_info.get("can_edit_messages", False),
                    "can_delete_messages": member_info.get("can_delete_messages", False),
                    "can_invite_users": member_info.get("can_invite_users", False),
                    "can_restrict_members": member_info.get("can_restrict_members", False),
                    "can_pin_messages": member_info.get("can_pin_messages", False),
                    "can_promote_members": member_info.get("can_promote_members", False),
                    "can_manage_chat": member_info.get("can_manage_chat", False),
                    "can_manage_video_chats": member_info.get("can_manage_video_chats", False),
                    "can_manage_topics": member_info.get("can_manage_topics", False),
                }
                print(" - Droits d'administration :")
                for right, has_permission in admin_rights.items():
                    print(f"   {right}: {'✅' if has_permission else '❌'}")
            else:
                print(" - Le bot n'est pas administrateur.")
        else:
            print(f"Erreur de l'API Telegram : {data.get('description')}")
    else:
        print(f"Erreur HTTP : {response.status_code} - {response.text}")

# Appeler la fonction
get_bot_permissions(BOT_TOKEN, CHAT_ID, BOT_USER_ID)
