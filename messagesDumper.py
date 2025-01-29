import requests
import json
import time
import argparse



# Configuration via arguments
parser = argparse.ArgumentParser(
    description="Script pour transférer des messages Telegram.\n\nExemple d'utilisation:\npython3 script.py -t <BOT_TOKEN> -c <CHAT_ID> -m <START_MESSAGE_ID> -o <OUTPUT_FILE>\n",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument('-t', '--token', dest='BOT_TOKEN', type=str, required=True,
                    help="Le token du bot.")
parser.add_argument('-c', '--chat', dest='CHAT_ID', type=str, required=True,
                    help="L'ID du chat (avec le -).")
parser.add_argument('-m', '--message-id', dest='START_MESSAGE_ID', type=int, required=True,
                    help="ID du premier message à transférer.")
parser.add_argument('-o', '--output-file', dest='OUTPUT_FILE', type=str, default="telegram_messages17000_end.json",
                    help="Fichier de sortie pour stocker les messages transférés.")



args = parser.parse_args()

BOT_TOKEN = args.BOT_TOKEN
CHAT_ID = args.CHAT_ID
START_MESSAGE_ID = args.START_MESSAGE_ID
OUTPUT_FILE = args.OUTPUT_FILE

"""
BOT_TOKEN = "1454028790:AAG9hlnXzgA0uyRsJTkAttLkMWQ480JHXDU"  # Remplacez par votre token
CHAT_ID = "-652054017"  # ID du chat
START_MESSAGE_ID = 12202  # ID du premier message à transférer
OUTPUT_FILE = "telegram_messages17000_end.json"  # Fichier pour stocker les messages transférés
"""
# Fonction pour transférer un message
def forward_message(bot_token, chat_id, message_id):
    url = f"https://api.telegram.org/bot{bot_token}/forwardMessage"
    payload = {
        "from_chat_id": chat_id,
        "chat_id": chat_id,
        "message_id": message_id
    }
    headers = {
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            print(f"Message {message_id} transféré avec succès.")
            return response.json()  # Retourne la réponse en cas de succès
        elif response.status_code == 429:
            print("botting detected, sleeping 15")
            time.sleep(15)
        else:
            print(f"Échec pour le message {message_id} : {response.status_code} - {response.text}")
            return None
    except requests.RequestException as e:
        print(f"Erreur de requête pour le message {message_id} : {e}")
        return None

# Fonction principale pour dumper les messages
def dump_messages(bot_token, chat_id, start_message_id, output_file, max_iterations=16000):
    messages = []
    message_id = start_message_id

    for _ in range(max_iterations):
        result = forward_message(bot_token, chat_id, message_id)
        if result:
            messages.append(result)  # Stocke la réponse si elle est valide
            print(result)
            output_file2 = "realtime_17000.json"
            with open(output_file2, "a", encoding="utf-8") as file:
                json.dump(messages, file, ensure_ascii=False, indent=4)
        else:
            print(f"Message {message_id} non trouvé ou erreur détectée. On continue...")

        message_id -= 1  # Passe au message précédent

    # Sauvegarde des messages dans un fichier JSON
    if messages:
        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(messages, file, ensure_ascii=False, indent=4)
        print(f"{len(messages)} messages enregistrés dans {output_file}")
    else:
        print("Aucun message valide trouvé.")

# Exécution du script
if __name__ == "__main__":
    dump_messages(BOT_TOKEN, CHAT_ID, START_MESSAGE_ID, OUTPUT_FILE)
