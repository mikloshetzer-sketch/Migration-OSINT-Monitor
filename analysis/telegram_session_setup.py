from getpass import getpass
from telethon import TelegramClient
from telethon.sessions import StringSession

def main():
    print("Telegram one-time session setup")
    api_id_raw = input("Telegram API ID: ").strip()
    api_hash = getpass("Telegram API HASH: ").strip()

    if not api_id_raw.isdigit():
        raise SystemExit("ERROR: API ID must be numeric.")
    if not api_hash:
        raise SystemExit("ERROR: API HASH is empty.")

    client = TelegramClient(StringSession(), int(api_id_raw), api_hash)
    client.start()

    session_string = client.session.save()

    print("\nLOGIN SUCCESSFUL")
    print("Save the value below as GitHub Actions secret: TELEGRAM_SESSION\n")
    print(session_string)
    print("\nTreat this value like a password. Do not commit or share it.")

    client.disconnect()

if __name__ == "__main__":
    main()
