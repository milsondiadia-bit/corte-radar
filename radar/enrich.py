"""
Enriquecimento: baixa o vídeo, transcreve o áudio e procura a íntegra.
"""
import os
import subprocess
import tempfile
from datetime import timedelta

import requests

_whisper = None


def _carregar_whisper(tamanho: str):
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(tamanho, device="cpu", compute_type="int8")
    return _whisper


def baixar_video(post, destino: str) -> str | None:
    """Tenta a URL .mp4 direta; se falhar, cai no yt-dlp pela URL do post."""
    caminho = os.path.join(destino, f"{post.id}.mp4")
    if post.video_url:
        try:
            r = requests.get(post.video_url, timeout=120, stream=True)
            r.raise_for_status()
            with open(caminho, "wb") as fh:
                for pedaco in r.iter_content(1 << 16):
                    fh.write(pedaco)
            return caminho
        except Exception:
            pass
    try:
        subprocess.run(
            ["yt-dlp", "-f", "best[ext=mp4]/best", "-o", caminho, post.url],
            check=True, capture_output=True, timeout=180,
        )
        return caminho if os.path.exists(caminho) else None
    except Exception:
        return None


def transcrever(post, cfg: dict) -> tuple[str | None, str | None]:
    """Devolve (transcricao, idioma_detectado)."""
    t = cfg["transcricao"]
    if not t["ativo"]:
        return None, None
    with tempfile.TemporaryDirectory() as tmp:
        caminho = baixar_video(post, tmp)
        if not caminho:
            return None, None
        modelo = _carregar_whisper(t["modelo_whisper"])
        segmentos, info = modelo.transcribe(
            caminho,
            language=t.get("idioma"),                     # None = detecta sozinho
            task="translate" if t.get("traduzir_para_ingles") else "transcribe",
            vad_filter=True,
        )
        limite = t["max_segundos"]
        texto = " ".join(s.text.strip() for s in segmentos if s.start < limite)
        return (texto.strip() or None), getattr(info, "language", None)


# ---------------------------------------------------------------- #
# Busca da gravação completa (YouTube Data API v3 — cota gratuita)
# ---------------------------------------------------------------- #
def buscar_integra(post, analise: dict, cfg: dict) -> list[dict]:
    if not cfg["buscar_integra"]["ativo"]:
        return []
    chave = os.environ.get("YOUTUBE_API_KEY")
    if not chave:
        return []

    b = cfg["buscar_integra"]
    depois = (post.criado_em - timedelta(days=b["janela_dias"]))
    canais = list((b.get("canais_prioritarios") or {}).items())

    consultas = (analise or {}).get("termos_busca") or [post.texto[:90]]
    vistos, achados = set(), []

    for consulta in consultas[:3]:
        alvos = [(nome, cid) for nome, cid in canais] or [(None, None)]
        for nome_canal, canal_id in alvos:
            if len(achados) >= b["max_resultados"]:
                break
            params = {
                "key": chave, "part": "snippet", "q": consulta,
                "type": "video", "maxResults": 5, "order": "relevance",
                "publishedAfter": depois.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            if canal_id:
                params["channelId"] = canal_id
            try:
                r = requests.get("https://www.googleapis.com/youtube/v3/search",
                                 params=params, timeout=30)
                r.raise_for_status()
                itens = r.json().get("items", [])
            except Exception:
                continue
            for it in itens:
                vid = it["id"]["videoId"]
                if vid in vistos:
                    continue
                vistos.add(vid)
                achados.append({
                    "titulo": it["snippet"]["title"],
                    "canal": it["snippet"]["channelTitle"],
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "publicado": it["snippet"]["publishedAt"],
                    "prioritario": bool(canal_id),
                })
    achados.sort(key=lambda x: (not x["prioritario"], x["publicado"]))
    return achados[: b["max_resultados"]]
