"""
Filtro 1 — heurística barata em cima da legenda do post.
Calibrado para contas OSINT/geopolítica em inglês.
"""
import re
import unicodedata

# "TRUMP:"  "Vladimir Putin:"  "IDF Spokesperson:"
FALANTE = re.compile(
    r"^\s*([A-Z][\w.'’\-]*(?:\s+[A-Z][\w.'’\-]*){0,4})\s*:\s*\S",
    re.UNICODE,
)
# rótulo inicial a descascar: "🚨 BREAKING:", "JUST IN —", "WATCH |"
ROTULO = re.compile(r"^[\W\d_]*([A-Za-z][A-Za-z\s]{1,18}?)\s*[:\|\-–—]\s*")
ASPAS = re.compile(r'["“”][^"“”]{12,}["“”]')


def _normalizar(txt: str) -> str:
    txt = txt.lower()
    txt = unicodedata.normalize("NFD", txt)
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


def _contem(texto_norm: str, termos: list[str]) -> list[str]:
    achados = []
    for t in termos:
        tn = _normalizar(str(t))
        padrao = re.escape(tn) if not tn.isalnum() else rf"\b{re.escape(tn)}\b"
        if re.search(padrao, texto_norm):
            achados.append(t)
    return achados


def _descascar_rotulos(texto: str, prefixos: list[str]) -> str:
    """Remove 'BREAKING:', 'JUST IN —', '🚨 WATCH |' do começo, repetidamente."""
    prefixos_norm = {_normalizar(p) for p in prefixos}
    for _ in range(3):
        m = ROTULO.match(texto)
        if not m or _normalizar(m.group(1).strip()) not in prefixos_norm:
            break
        texto = texto[m.end():]
    return texto.lstrip("\"'“ ")


def detectar_falante(texto: str, prefixos: list[str]) -> str | None:
    """Devolve o nome antes dos dois-pontos, se o padrão bater."""
    limpo = _descascar_rotulos(texto, prefixos)
    for linha in limpo.split("\n")[:3]:
        m = FALANTE.match(linha)
        if m:
            nome = m.group(1).strip()
            if _normalizar(nome) in {_normalizar(p) for p in prefixos}:
                continue
            if len(nome) > 60:
                continue
            return nome
    return None


def pontuar(post, cfg: dict) -> tuple[int, list[str], str | None]:
    """Devolve (score, motivos, falante_detectado). Score negativo = descartar."""
    f = cfg["filtro"]
    texto = post.texto or ""
    norm = _normalizar(texto)
    motivos, score = [], 0

    if _contem(norm, f["blacklist"]):
        return -1, ["blacklist"], None

    dur = post.duracao_seg
    if dur is not None:
        if dur < f["duracao_min_seg"]:
            return -1, [f"curto demais ({dur:.0f}s)"], None
        if dur > f["duracao_max_seg"]:
            return -1, [f"longo demais ({dur:.0f}s) — talvez já seja a íntegra"], None

    # padrão "Reporter:" / "Q:" — formato pergunta-resposta
    achados = _contem(norm, f["padrao_reporter"]["termos"])
    if achados:
        score += f["padrao_reporter"]["peso"]
        motivos.append(f"formato P&R: {achados[0]}")

    # padrão "NOME:" no início
    falante = detectar_falante(texto, f["padrao_falante"]["prefixos_ignorar"])
    if falante:
        score += f["padrao_falante"]["peso"]
        motivos.append(f'padrão falante: "{falante}:"')

    for chave in ("verbos_fala", "contexto", "gatilhos", "cargos"):
        bloco = f[chave]
        achados = _contem(norm, bloco["termos"])
        if achados:
            score += bloco["peso"]
            motivos.append(f"{chave}: {', '.join(str(a) for a in achados[:3])}")

    if ASPAS.search(texto):
        score += f["aspas"]["peso"]
        motivos.append("citação entre aspas")

    # penalidade por vocabulário de imagem de combate
    achados = _contem(norm, f["penalidade_imagem"]["termos"])
    if achados:
        score += f["penalidade_imagem"]["peso"]
        motivos.append(f"⚠ imagem de combate: {achados[0]}")

    return score, motivos, falante


def eh_candidato(post, cfg: dict):
    score, motivos, falante = pontuar(post, cfg)
    return score >= cfg["filtro"]["score_minimo"], score, motivos, falante
