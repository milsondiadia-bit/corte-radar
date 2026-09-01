"""Notificação do alerta."""
import html
import os

import requests


TIPOS_PT = {
    "interview": "entrevista",
    "press_conference": "coletiva de imprensa",
    "speech": "discurso",
    "address": "pronunciamento",
    "hearing": "audiencia",
    "testimony": "depoimento",
    "session": "sessao",
    "podcast": "podcast",
    "doorstep": "declaracao a imprensa",
    "statement": "declaracao",
    "other": "outro",
}


def _pt(analise, campo_pt, campo, padrao=None):
    """Prefere a versao traduzida; cai na original se a IA nao mandou."""
    a = analise or {}
    v = a.get(campo_pt) or a.get(campo)
    return v if v else padrao


def _montar(post, analise, integras, motivos, transcricao):
    a = analise or {}
    q = _pt(a, "quem_fala_pt", "quem_fala", "nao identificado")
    tipo_bruto = a.get("tipo_evento") or "?"
    tipo = a.get("tipo_evento_pt") or TIPOS_PT.get(tipo_bruto, tipo_bruto)
    local = _pt(a, "veiculo_ou_local_pt", "veiculo_ou_local")
    assunto = a.get("assunto") or ""
    conf = a.get("confianca", 0)
    fala = a.get("transcricao_pt") or transcricao

    linhas = [
        "\U0001F399 <b>CORTE DETECTADO</b>",
        f"<b>Quem:</b> {html.escape(str(q))}",
        f"<b>Evento:</b> {html.escape(str(tipo))}" + (f" \u2014 {html.escape(str(local))}" if local else ""),
        f"<b>Assunto:</b> {html.escape(assunto)}",
        f"<b>Perfil:</b> @{post.autor} \u00b7 confian\u00e7a {conf:.0%}",
        f"<b>Post:</b> {post.url}",
    ]
    if post.duracao_seg:
        linhas.append(f"<b>Dura\u00e7\u00e3o do corte:</b> {post.duracao_seg:.0f}s")
    if fala:
        linhas += ["", f"<b>Transcri\u00e7\u00e3o:</b> <i>{html.escape(str(fala)[:600])}</i>"]
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
