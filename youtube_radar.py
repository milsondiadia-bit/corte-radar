#!/usr/bin/env python3
"""
YOUTUBE RADAR — monitora canais do YouTube e avisa quando sai
entrevista/coletiva completa ou corte de fala de autoridade.

Le o RSS do canal (de graca), confere duracao e se foi live pela API
do YouTube (1 unidade por video) e so entao gasta IA na classificacao.

Uso:
    python youtube_radar.py
    python youtube_radar.py --horas 12
    python youtube_radar.py --seco          # mostra na tela, nao envia
    python youtube_radar.py --zerar
    python youtube_radar.py --marcar-tudo   # marca tudo como visto, sem enviar
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------
# CANAIS MONITORADOS
# Para acrescentar outro: pegue o channel_id (comeca com UC) e
# adicione uma linha aqui. Nada mais precisa mudar.
# ---------------------------------------------------------------

CANAIS = {
    "DRM News": "UCrvG04V6wbOau6fVJI01OlQ",
}

ARQUIVO_HISTORICO = "youtube_vistos.json"
LIMITE_HISTORICO = 2000

JANELA_HORAS_PADRAO = 12

# A partir de quantos segundos o video e tratado como material completo.
SEG_MATERIAL_COMPLETO = 900        # 15 min
# Abaixo disso e curto demais para ter fala aproveitavel.
SEG_CURTO_DEMAIS = 45

MODELOS_IA = ["gemini-flash-lite-latest", "gemini-3-flash-preview", "gemini-flash-latest"]

# Titulo que bate com isso nem chega na IA.
LIXO = [
    "showbiz", "celebrity", "red carpet", "box office", "movie review",
    "trailer", "album", "grammy", "oscar", "netflix", "kardashian",
    "horoscope", "recipe", "weight loss", "gadget review", "unboxing",
    "top 10", "top 5", "you won't believe", "shocking moment",
    "highlights", "full match", "transfer news", "premier league",
    "nba ", "nfl ", "cricket", "goal of the", "crypto price",
    "stock market today", "bitcoin price", "how to invest",
    "weekly roundup", "week in review", "recap",
]

SISTEMA = """You screen YouTube videos from news channels for a Brazilian political/geopolitical content creator.

He wants ONLY videos where a public figure (head of state, minister, diplomat, general, party leader, spokesperson, candidate, senior official) is actually SPEAKING on camera: interviews, press conferences, speeches, parliamentary sessions, hearings, testimony, doorstep remarks, statements to reporters, debates.

REJECT: news packages narrated by an anchor or voiceover, showbiz, sports, celebrity news, markets and crypto explainers, AI/tech product news, listicles, compilations, opinion monologues by channel hosts, and anything where nobody notable is speaking on camera.

Reply with JSON only. No markdown, no code fences.
{
  "aproveitavel": true,
  "confianca": 0.0,
  "quem_fala": "name and title, or null",
  "tipo_evento": "interview|press_conference|speech|session|hearing|testimony|doorstep|statement|debate|other",
  "assunto": "topic in up to 12 words, in Portuguese",
  "motivo": "one short sentence in Portuguese"
}"""


# ---------------------------------------------------------------
# APOIO
# ---------------------------------------------------------------

def buscar(url, dados=None, cabecalhos=None, timeout=45):
    req = urllib.request.Request(url, data=dados, headers=cabecalhos or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def carregar_historico():
    if not os.path.exists(ARQUIVO_HISTORICO):
        return []
    try:
        with open(ARQUIVO_HISTORICO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def salvar_historico(ids):
    ids = ids[-LIMITE_HISTORICO:]
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(ids, f, ensure_ascii=False, indent=1)


def eh_lixo(titulo, descricao=None):
    """
    Olha SO o titulo. A descricao nao serve: muitos canais repetem a mesma
    apresentacao em todo video, e palavras como "showbiz" e "sports"
    aparecem ali mesmo em live de coletiva.
    """
    texto = (titulo or "").lower()
    for termo in LIXO:
        if termo in texto:
            return termo
    return None


def duracao_iso_para_seg(iso):
    """PT1H2M10S -> 3730"""
    m = re.match(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def formatar_duracao(seg):
    if not seg:
        return "?"
    if seg < 60:
        return f"{seg}s"
    return f"{seg // 60}min{seg % 60:02d}s"


# ---------------------------------------------------------------
# RSS
# ---------------------------------------------------------------

def ler_rss(canal_id):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={canal_id}"
    try:
        bruto = buscar(url)
    except Exception as e:
        print(f"  falha no RSS: {e}")
        return []

    ns = {
        "a": "http://www.w3.org/2005/Atom",
        "m": "http://search.yahoo.com/mrss/",
    }
    try:
        raiz = ET.fromstring(bruto)
    except Exception as e:
        print(f"  RSS ilegivel: {e}")
        return []

    itens = []
    for entrada in raiz.findall("a:entry", ns):
        vid = entrada.findtext("{http://www.youtube.com/xml/schemas/2015}videoId")
        titulo = entrada.findtext("a:title", default="", namespaces=ns)
        publicado = entrada.findtext("a:published", default="", namespaces=ns)
        grupo = entrada.find("m:group", ns)
        descricao = ""
        if grupo is not None:
            descricao = grupo.findtext("m:description", default="", namespaces=ns) or ""
        try:
            quando = datetime.fromisoformat(publicado.replace("Z", "+00:00"))
        except Exception:
            quando = datetime.now(timezone.utc)
        if vid:
            itens.append({
                "id": vid,
                "titulo": titulo.strip(),
                "descricao": descricao.strip(),
                "publicado": quando,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
    return itens


# ---------------------------------------------------------------
# API DO YOUTUBE — duracao e se foi live (1 unidade por chamada)
# ---------------------------------------------------------------

def detalhar(ids, chave):
    """Devolve {video_id: {'seg': int, 'foi_live': bool}} para ate 50 ids."""
    if not ids or not chave:
        return {}
    params = urllib.parse.urlencode({
        "part": "contentDetails,liveStreamingDetails",
        "id": ",".join(ids[:50]),
        "key": chave,
    })
    try:
        bruto = buscar(f"https://www.googleapis.com/youtube/v3/videos?{params}")
        dados = json.loads(bruto)
    except Exception as e:
        print(f"  API do YouTube falhou: {e}")
        return {}

    saida = {}
    for item in dados.get("items", []):
        detalhes = item.get("contentDetails", {}) or {}
        live = item.get("liveStreamingDetails", {}) or {}
        saida[item["id"]] = {
            "seg": duracao_iso_para_seg(detalhes.get("duration")),
            "foi_live": bool(live),
        }
    return saida


# ---------------------------------------------------------------
# IA
# ---------------------------------------------------------------

def classificar(video, chave):
    if not chave:
        return None

    pergunta = (
        f"Channel: {video['canal']}\n"
        f"Title: {video['titulo']}\n"
        f"Duration: {formatar_duracao(video.get('seg'))}\n"
        f"Was a livestream: {'yes' if video.get('foi_live') else 'no'}\n\n"
        f"Description:\n{video['descricao'][:1500]}"
    )
    corpo = json.dumps({
        "systemInstruction": {"parts": [{"text": SISTEMA}]},
        "contents": [{"role": "user", "parts": [{"text": pergunta}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 600,
            "responseMimeType": "application/json",
        },
    }).encode("utf-8")

    cabecalhos = {"x-goog-api-key": chave, "Content-Type": "application/json"}

    for modelo in MODELOS_IA:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        for espera in (0, 20, 40):
            if espera:
                time.sleep(espera)
            try:
                bruto = buscar(url, dados=corpo, cabecalhos=cabecalhos, timeout=60)
            except Exception as e:
                texto_erro = str(e)
                if any(c in texto_erro for c in ("401", "403", "404")):
                    break          # chave ou modelo errado: tenta o proximo modelo
                continue           # 429/503: espera e tenta de novo
            try:
                resposta = json.loads(bruto)
                texto = resposta["candidates"][0]["content"]["parts"][0]["text"]
                texto = texto.strip().removeprefix("```json").removeprefix("```")
                texto = texto.removesuffix("```").strip()
                return json.loads(texto)
            except Exception:
                continue
    return None


# ---------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------

def escapar(txt):
    return (txt or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def enviar(video, analise, token, chat_id, seco=False):
    if video["classe"] == "completo":
        cabeca = "🎙 <b>ENTREVISTA / MATERIAL COMPLETO</b>"
    else:
        cabeca = "✂️ <b>CORTE DE FALA</b>"

    quem = analise.get("quem_fala") or "nao identificado"
    linhas = [
        cabeca,
        "",
        f"<b>{escapar(video['titulo'])}</b>",
        "",
        f"Quem fala: {escapar(quem)}",
        f"Tipo: {escapar(analise.get('tipo_evento') or '-')}",
        f"Assunto: {escapar(analise.get('assunto') or '-')}",
        f"Duracao: {formatar_duracao(video.get('seg'))}"
        + ("  ·  foi live" if video.get("foi_live") else ""),
        f"Canal: {escapar(video['canal'])}",
        f"Confianca: {int(float(analise.get('confianca', 0)) * 100)}%",
        "",
        video["url"],
    ]
    texto = "\n".join(linhas)

    if seco:
        print("\n" + "-" * 50)
        print(texto)
        return True

    dados = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode("utf-8")
    try:
        buscar(f"https://api.telegram.org/bot{token}/sendMessage", dados=dados)
        return True
    except Exception as e:
        print(f"  falha ao enviar: {e}")
        return False


# ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horas", type=int, default=JANELA_HORAS_PADRAO)
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--zerar", action="store_true")
    ap.add_argument("--marcar-tudo", action="store_true")
    ap.add_argument("--confianca", type=float, default=0.6)
    args = ap.parse_args()

    if args.zerar:
        if os.path.exists(ARQUIVO_HISTORICO):
            os.remove(ARQUIVO_HISTORICO)
        print("Historico zerado.")
        return

    chave_yt = os.environ.get("YOUTUBE_API_KEY", "")
    chave_ia = os.environ.get("GEMINI_API_KEY", "")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not args.seco and not (token and chat_id):
        sys.exit("Faltam TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")

    vistos = carregar_historico()
    conhecidos = set(vistos)
    corte = datetime.now(timezone.utc) - timedelta(hours=args.horas)

    candidatos = []
    for nome, canal_id in CANAIS.items():
        print(f"\nLendo {nome}...")
        itens = ler_rss(canal_id)
        print(f"  {len(itens)} video(s) no feed")
        for item in itens:
            if item["id"] in conhecidos:
                continue
            if item["publicado"] < corte:
                continue
            item["canal"] = nome
            candidatos.append(item)

    if not candidatos:
        print("\nNada novo na janela.")
        return

    print(f"\n{len(candidatos)} video(s) novo(s) na janela de {args.horas}h")

    if args.marcar_tudo:
        salvar_historico(vistos + [v["id"] for v in candidatos])
        print("Marcados como vistos, sem enviar.")
        return

    # descarta lixo obvio antes de gastar cota
    filtrados = []
    for v in candidatos:
        termo = eh_lixo(v["titulo"])
        if termo:
            print(f"  ✗ lixo ({termo}): {v['titulo'][:60]}")
            vistos.append(v["id"])
            continue
        filtrados.append(v)

    # duracao e live
    detalhes = detalhar([v["id"] for v in filtrados], chave_yt)
    prontos = []
    for v in filtrados:
        d = detalhes.get(v["id"], {})
        v["seg"] = d.get("seg")
        v["foi_live"] = d.get("foi_live", False)

        if v["seg"] is not None and v["seg"] < SEG_CURTO_DEMAIS:
            print(f"  ✗ curto demais ({formatar_duracao(v['seg'])}): {v['titulo'][:50]}")
            vistos.append(v["id"])
            continue

        if v["foi_live"] or (v["seg"] or 0) >= SEG_MATERIAL_COMPLETO:
            v["classe"] = "completo"
        else:
            v["classe"] = "corte"
        prontos.append(v)

    enviados = 0
    for v in prontos:
        analise = classificar(v, chave_ia)
        if analise is None:
            print(f"  ✗ IA nao respondeu, nao envio: {v['titulo'][:50]}")
            continue          # nao marca como visto: tenta de novo na proxima
        if not analise.get("aproveitavel"):
            print(f"  ✗ IA descartou: {v['titulo'][:50]} — {analise.get('motivo','')}")
            vistos.append(v["id"])
            continue
        if float(analise.get("confianca", 0)) < args.confianca:
            print(f"  ✗ confianca baixa: {v['titulo'][:50]}")
            vistos.append(v["id"])
            continue

        if enviar(v, analise, token, chat_id, seco=args.seco):
            marca = "COMPLETO" if v["classe"] == "completo" else "CORTE"
            print(f"  ✓ {marca}: {v['titulo'][:60]}")
            vistos.append(v["id"])
            enviados += 1
            time.sleep(1)

    if not args.seco:
        salvar_historico(vistos)
    print(f"\n{enviados} aviso(s) enviado(s).")


if __name__ == "__main__":
    main()
