"""Notificação do alerta."""
import html
import os

import requests


def _montar(post, analise, integras, motivos, transcricao):
    q = (analise or {}).get("quem_fala") or "não identificado"
    tipo = (analise or {}).get("tipo_evento") or "?"
    local = (analise or {}).get("veiculo_ou_local")
    assunto = (analise or {}).get("assunto") or ""
    conf = (analise or {}).get("confianca", 0)

    linhas = [
        "🎙 <b>CORTE DETECTADO</b>",
        f"<b>Quem:</b> {html.escape(str(q))}",
        f"<b>Evento:</b> {html.escape(tipo)}" + (f" — {html.escape(local)}" if local else ""),
        f"<b>Assunto:</b> {html.escape(assunto)}",
        f"<b>Perfil:</b> @{post.autor} · confiança {conf:.0%}",
        f"<b>Post:</b> {post.url}",
    ]
    if post.duracao_seg:
        linhas.append(f"<b>Duração do corte:</b> {post.duracao_seg:.0f}s")
    if transcricao:
        linhas += ["", f"<b>Transcrição:</b> <i>{html.escape(transcricao[:600])}</i>"]
    if integras:
        linhas += ["", "<b>🔎 Possíveis íntegras:</b>"]
        for i in integras:
            marca = "⭐ " if i["prioritario"] else ""
            linhas.append(f"{marca}{html.escape(i['canal'])} — "
                          f"<a href=\"{i['url']}\">{html.escape(i['titulo'][:80])}</a>")
    else:
        linhas += ["", "🔎 Nenhuma íntegra encontrada ainda — vale buscar na mão."]
    if motivos:
        linhas += ["", f"<i>sinais: {html.escape('; '.join(motivos))}</i>"]
    return "\n".join(linhas)


def enviar(post, analise, integras, motivos, transcricao, cfg):
    corpo = _montar(post, analise, integras, motivos, transcricao)

    if cfg["notificar"]["canal"] == "console":
        print("\n" + "=" * 60)
        print(corpo.replace("<b>", "").replace("</b>", "")
                   .replace("<i>", "").replace("</i>", ""))
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": corpo, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=30,
    )
    if cfg["notificar"].get("enviar_video") and post.video_url:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendVideo",
            json={"chat_id": chat, "video": post.video_url},
            timeout=60,
        )
