"""Estado local: o que já foi visto e o que já foi alertado."""
import json
import sqlite3
from pathlib import Path

CAMINHO = Path(__file__).resolve().parent.parent / "radar.db"


def conectar():
    con = sqlite3.connect(CAMINHO)
    con.execute("""CREATE TABLE IF NOT EXISTS vistos (
        id TEXT PRIMARY KEY, autor TEXT, quando TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS cursor (
        autor TEXT PRIMARY KEY, since_id TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS digitais (
        id TEXT PRIMARY KEY, autor TEXT, assinatura TEXT,
        quando REAL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS alertas (
        id TEXT PRIMARY KEY, autor TEXT, url TEXT, texto TEXT,
        analise TEXT, integras TEXT, transcricao TEXT,
        quando TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.commit()
    return con


def ja_visto(con, post_id):
    return con.execute("SELECT 1 FROM vistos WHERE id=?", (post_id,)).fetchone() is not None


def marcar_visto(con, post):
    con.execute("INSERT OR IGNORE INTO vistos (id, autor) VALUES (?,?)",
                (post.id, post.autor))
    con.commit()


def since_id(con, autor):
    linha = con.execute("SELECT since_id FROM cursor WHERE autor=?", (autor,)).fetchone()
    return linha[0] if linha else None


def salvar_cursor(con, autor, post_id):
    atual = since_id(con, autor)
    if atual is None or str(post_id) > str(atual):
        con.execute("INSERT OR REPLACE INTO cursor VALUES (?,?)", (autor, str(post_id)))
        con.commit()


def salvar_alerta(con, post, analise, integras, transcricao):
    con.execute("INSERT OR REPLACE INTO alertas "
                "(id, autor, url, texto, analise, integras, transcricao) "
                "VALUES (?,?,?,?,?,?,?)",
                (post.id, post.autor, post.url, post.texto,
                 json.dumps(analise, ensure_ascii=False),
                 json.dumps(integras, ensure_ascii=False), transcricao))
    con.commit()


# ---------------------------------------------------------------- #
# Deduplicação entre contas: o mesmo corte sai nos 4 perfis.
# ---------------------------------------------------------------- #
import re
import time
from difflib import SequenceMatcher


def _assinatura(post, transcricao):
    """Texto normalizado que representa o conteúdo falado."""
    base = (transcricao or post.texto or "").lower()
    return re.sub(r"[^a-z0-9 ]+", " ", base)[:400].strip()


def duplicado(con, post, transcricao, cfg):
    """Se já alertamos algo muito parecido há pouco, devolve o autor original."""
    d = cfg.get("dedup", {})
    if not d.get("ativo"):
        return None
    assinatura = _assinatura(post, transcricao)
    if len(assinatura) < 40:
        return None

    corte = time.time() - d["janela_horas"] * 3600
    for autor, anterior in con.execute(
            "SELECT autor, assinatura FROM digitais WHERE quando > ?", (corte,)):
        if SequenceMatcher(None, assinatura, anterior).ratio() >= d["similaridade_minima"]:
            return autor
    return None


def registrar_digital(con, post, transcricao):
    con.execute("INSERT OR REPLACE INTO digitais VALUES (?,?,?,?)",
                (post.id, post.autor, _assinatura(post, transcricao), time.time()))
    con.execute("DELETE FROM digitais WHERE quando < ?", (time.time() - 86400,))
    con.commit()
