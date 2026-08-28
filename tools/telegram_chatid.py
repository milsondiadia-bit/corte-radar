#!/usr/bin/env python3
"""
Descobre o TELEGRAM_CHAT_ID do bot novo.

Antes de rodar:
  1. Crie o bot no @BotFather e ponha o token no .env
  2a. Para receber na conversa privada: mande /start para o bot
  2b. Para receber num canal: crie o canal, adicione o bot como
      administrador e publique qualquer mensagem nele

Depois:
  python tools/telegram_chatid.py
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token:
    sys.exit("Defina TELEGRAM_BOT_TOKEN no .env primeiro.")

eu = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
if not eu.get("ok"):
    sys.exit(f"Token inválido: {eu}")
print(f"Bot: @{eu['result']['username']}\n")

r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
updates = r.get("result", [])

if not updates:
    print("Nenhuma mensagem encontrada.")
    print("Mande /start para o bot (ou publique no canal com ele como admin)")
    print("e rode este script de novo.")
    sys.exit(0)

vistos = {}
for u in updates:
    msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member")
    if not msg:
        continue
    chat = msg.get("chat", {})
    if chat.get("id"):
        vistos[chat["id"]] = chat

for cid, chat in vistos.items():
    nome = chat.get("title") or chat.get("username") or chat.get("first_name", "?")
    print(f"TELEGRAM_CHAT_ID={cid}    # {chat.get('type')} · {nome}")

print("\nCole a linha certa no .env e teste com:")
print("  python tools/telegram_chatid.py --testar")

if "--testar" in sys.argv:
    destino = os.environ.get("TELEGRAM_CHAT_ID")
    if not destino:
        sys.exit("\nDefina TELEGRAM_CHAT_ID no .env para testar.")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": destino,
              "text": "🎙 <b>Corte Radar</b> conectado. Canal isolado funcionando.",
              "parse_mode": "HTML"},
        timeout=20,
    ).json()
    print("\nEnvio:", "OK" if resp.get("ok") else resp)
