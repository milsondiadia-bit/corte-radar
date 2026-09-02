#!/usr/bin/env python3
"""
CORTE RADAR — monitora perfis do X e avisa quando sai um corte de fala
de autoridade, já sugerindo onde achar a gravação completa.

Uso:
    python -m radar.main                 # roda em loop
    python -m radar.main --uma-vez       # roda uma passada só
    python -m radar.main --testar-texto "..."   # testa o filtro num texto
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from radar import db, filters, classify, enrich, notify
from radar.sources import criar_fonte, Post

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("radar")


def carregar_config():
    with open(RAIZ / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def processar_perfil(fonte, con, usuario, cfg, posts=None):
    if posts is None:
        try:
            posts = fonte.posts_recentes(usuario, db.since_id(con, usuario))
        except Exception as e:
            log.warning("falha ao ler @%s: %s", usuario, e)
            return

    for post in sorted(posts, key=lambda p: p.criado_em):
        if db.ja_visto(con, post.id):
            continue
        db.marcar_visto(con, post)
        db.salvar_cursor(con, usuario, post.id)

        limite = cfg.get("max_idade_horas")
        if limite:
            idade = (datetime.now(timezone.utc) - post.criado_em).total_seconds() / 3600
            if idade > limite:
                log.info("  ✗ @%s %s (antigo: %.1fh)", usuario, post.id, idade)
                continue

        candidato, score, motivos, falante = filters.eh_candidato(post, cfg)
        if not candidato:
            log.info("  ✗ @%s %s (score %d)", usuario, post.id, score)
            continue

        log.info("  → candidato @%s %s (score %d) — analisando…",
                 usuario, post.id, score)

        transcricao = idioma = None
        try:
            transcricao, idioma = enrich.transcrever(post, cfg)
            if idioma:
                log.info("    áudio em '%s'", idioma)
        except Exception as e:
            log.warning("    transcrição falhou: %s", e)

        original = db.duplicado(con, post, transcricao, cfg)
        db.registrar_digital(con, post, transcricao)
        if original:
            log.info("    ✗ mesmo corte já alertado via @%s", original)
            continue

        try:
            analise = classify.classificar(post, transcricao, falante, cfg)
        except Exception as e:
            log.warning("    classificação falhou: %s", e)
            analise = None

        if analise is None:
            log.info("    ✗ IA nao respondeu — nao envio sem analise")
            continue
        if not analise.get("eh_corte"):
            log.info("    ✗ IA descartou")
            continue
        if analise.get("confianca", 0) < cfg["ia"]["confianca_minima"]:
            log.info("    ✗ confiança baixa (%.2f)", analise.get("confianca", 0))
            continue

        integras = []

        db.salvar_alerta(con, post, analise, integras, transcricao)
        notify.enviar(post, analise, integras, motivos, transcricao, cfg)
        log.info("    ✓ ALERTA enviado")


def rodada(fonte, con, cfg):
    perfis = cfg["perfis"]
    log.info("varrendo %d perfis…", len(perfis))

    # Uma consulta so para todos os perfis: paga-se um minimo em vez de
    # um por perfil. Se falhar, cai no modo antigo, perfil a perfil.
    lote = None
    if hasattr(fonte, "posts_recentes_lote"):
        try:
            since = {u: db.since_id(con, u) for u in perfis}
            lote = fonte.posts_recentes_lote(perfis, since)
        except Exception as e:
            log.warning("busca unica falhou (%s) — indo perfil a perfil", e)
            lote = None

    pausa = cfg.get("pausa_entre_perfis", 6)
    for i, usuario in enumerate(perfis):
        if lote is None and i:
            time.sleep(pausa)   # free tier do twitterapi.io = 0.2 QPS
        processar_perfil(fonte, con, usuario, cfg,
                         lote.get(usuario) if lote is not None else None)


def testar_texto(texto, cfg):
    falso = Post(id="0", autor="teste", texto=texto, url="",
                 criado_em=datetime.now(timezone.utc), duracao_seg=45)
    ok, score, motivos, falante = filters.eh_candidato(falso, cfg)
    print(f"score={score}  candidato={ok}  falante={falante}")
    for m in motivos:
        print("  -", m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--testar-texto")
    args = ap.parse_args()

    cfg = carregar_config()

    if args.testar_texto:
        testar_texto(args.testar_texto, cfg)
        return

    con = db.conectar()
    fonte = criar_fonte(cfg["fonte"])

    if args.uma_vez:
        rodada(fonte, con, cfg)
        return

    log.info("radar no ar — checando a cada %ds (Ctrl+C para parar)", cfg["intervalo"])
    while True:
        try:
            rodada(fonte, con, cfg)
        except KeyboardInterrupt:
            log.info("encerrando")
            sys.exit(0)
        except Exception as e:
            log.error("erro na rodada: %s", e)
        time.sleep(cfg["intervalo"])


if __name__ == "__main__":
    main()
