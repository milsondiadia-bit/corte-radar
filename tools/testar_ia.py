#!/usr/bin/env python3
"""
Testa a chave da IA e lista os modelos disponiveis.

    python tools/testar_ia.py            # testa o modelo do config.yaml
    python tools/testar_ia.py --listar   # lista modelos que a sua chave aceita
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
load_dotenv(RAIZ / ".env")

cfg = yaml.safe_load(open(RAIZ / "config.yaml", encoding="utf-8"))

if "--listar" in sys.argv:
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        sys.exit("Defina GEMINI_API_KEY no .env")
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     params={"key": chave}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Erro {r.status_code}: {r.text[:300]}")
    print("Modelos que aceitam generateContent:\n")
    for m in r.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            print(" ", m["name"].replace("models/", ""))
    print("\nUse um destes em ia.modelo no config.yaml")
    sys.exit(0)

from radar import classify
from radar.sources import Post

post = Post(
    id="teste", autor="Osint613",
    texto='Reporter: Will you meet Putin this year?\n'
          'Trump: We will see. I have a very good relationship with him.',
    url="https://x.com/Osint613/status/0",
    criado_em=datetime.now(timezone.utc), duracao_seg=42,
)

print(f"Provedor: {cfg['ia']['provedor']}  ·  Modelo: {cfg['ia']['modelo']}\n")
try:
    r = classify.classificar(post, None, "Reporter", cfg)
except Exception as e:
    sys.exit(f"FALHOU: {e}\n\nRode com --listar para ver os modelos validos.")

import json
print(json.dumps(r, indent=2, ensure_ascii=False))
print("\nEsperado: eh_corte=true, tipo_evento por volta de doorstep/statement.")
