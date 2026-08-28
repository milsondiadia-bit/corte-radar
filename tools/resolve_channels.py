#!/usr/bin/env python3
"""
Descobre os IDs dos canais do YouTube listados em `canais_desejados`
e imprime o bloco pronto para colar em `canais_prioritarios`.

    python tools/resolve_channels.py

Custa 100 unidades de cota por canal. A cota diária gratuita é 10.000,
então rode isso uma vez e guarde o resultado.
"""
import os
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

chave = os.environ.get("YOUTUBE_API_KEY")
if not chave:
    sys.exit("Defina YOUTUBE_API_KEY no .env")

cfg = yaml.safe_load(open(RAIZ / "config.yaml", encoding="utf-8"))
desejados = cfg["buscar_integra"].get("canais_desejados", [])

print("  canais_prioritarios:")
for nome in desejados:
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"key": chave, "part": "snippet", "q": nome,
                    "type": "channel", "maxResults": 1},
            timeout=30,
        )
        r.raise_for_status()
        itens = r.json().get("items", [])
    except Exception as e:
        print(f"    # {nome}: erro — {e}", file=sys.stderr)
        continue

    if not itens:
        print(f"    # {nome}: não encontrado", file=sys.stderr)
        continue

    achado = itens[0]["snippet"]
    cid = itens[0]["id"]["channelId"]
    marca = "" if achado["title"].lower() == nome.lower() else \
            f"   # confira: achou '{achado['title']}'"
    print(f'    "{nome}": {cid}{marca}')
