"""
Filtro 2 — classificação com IA.
Suporta Gemini (gratuito) e Claude. Troque `ia.provedor` no config.yaml.
"""
import json
import os
import time

import requests

SISTEMA = """You analyze video posts from OSINT and geopolitics accounts on X \
(MarioNawfal, Osint613, clashreport, nexta_tv).

Decide whether the video is a CLIP of a public figure SPEAKING — an interview, \
press conference, speech, address, parliamentary session, hearing, testimony, \
podcast, doorstep remarks, or statement to reporters. The person on camera must \
be talking, and there must be a longer original recording somewhere.

NOT a speaking clip: combat or drone footage, aftermath of strikes, CCTV or \
dashcam video, protests, explosions, military hardware, satellite imagery, \
narrated news packages with no on-camera speaker, memes, animations, ads, \
AI-generated or edited compilations with voiceover.

Beware: many of these accounts repackage clips with their own voiceover or \
subtitles. If the audio is a narrator summarizing what someone said rather than \
the person's own voice, set eh_corte to false.

Reply with JSON only. No markdown, no code fences.
{
  "eh_corte": true|false,
  "confianca": 0.0-1.0,
  "quem_fala": "name and title, or null",
  "tipo_evento": "interview|press_conference|speech|address|hearing|testimony|session|podcast|doorstep|statement|other",
  "veiculo_ou_local": "outlet, program, venue or institution, or null",
  "idioma_original": "ISO code of what is spoken, or null",
  "assunto": "topic in up to 12 words",
  "data_provavel_evento": "YYYY-MM-DD if inferable, else null",
  "termos_busca": ["3-5 ready-to-use search queries in the ORIGINAL language of the event to find the full recording"],
  "onde_procurar": ["likely sources: C-SPAN, White House, Kremlin.ru, Knesset channel, UN Web TV, specific broadcaster, etc."]
}"""


def _montar_pergunta(post, transcricao, falante):
    partes = [
        f"Account: @{post.autor}",
        f"Posted: {post.criado_em.isoformat()}",
        f"Video duration: {post.duracao_seg:.0f}s" if post.duracao_seg else "",
        f"Speaker suggested by caption pattern: {falante}" if falante else "",
        f"Caption:\n{post.texto}",
    ]
    if transcricao:
        partes.append(f"Audio transcript:\n{transcricao[:3500]}")
    else:
        partes.append("(No transcript available — judge from the caption alone "
                      "and lower your confidence accordingly.)")
    return "\n\n".join(p for p in partes if p)


# ---------------------------------------------------------------- #
# Gemini — free tier, sem cartão
# ---------------------------------------------------------------- #
def _gemini(pergunta, cfg):
    chave = os.environ["GEMINI_API_KEY"]
    modelo = cfg["ia"]["modelo"]
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{modelo}:generateContent")

    corpo = {
        "systemInstruction": {"parts": [{"text": SISTEMA}]},
        "contents": [{"role": "user", "parts": [{"text": pergunta}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 900,
            "responseMimeType": "application/json",
        },
    }

    # free tier estoura em 429; espera e tenta de novo
    for tentativa in range(4):
        r = requests.post(url, params={"key": chave}, json=corpo, timeout=60)
        if r.status_code == 429:
            time.sleep(2 ** tentativa)
            continue
        r.raise_for_status()
        dados = r.json()
        try:
            return dados["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"resposta inesperada do Gemini: {str(dados)[:200]}")
    raise RuntimeError("Gemini: limite de requisições estourado após 4 tentativas")


# ---------------------------------------------------------------- #
# Claude — pago
# ---------------------------------------------------------------- #
def _claude(pergunta, cfg):
    from anthropic import Anthropic
    cliente = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = cliente.messages.create(
        model=cfg["ia"]["modelo"],
        max_tokens=900,
        system=SISTEMA,
        messages=[{"role": "user", "content": pergunta}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


PROVEDORES = {"gemini": _gemini, "claude": _claude}


def classificar(post, transcricao, falante, cfg):
    if not cfg["ia"]["ativo"]:
        return None

    pergunta = _montar_pergunta(post, transcricao, falante)
    bruto = PROVEDORES[cfg["ia"]["provedor"]](pergunta, cfg)
    bruto = bruto.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        return {"eh_corte": False, "confianca": 0.0, "erro_parse": bruto[:200]}
