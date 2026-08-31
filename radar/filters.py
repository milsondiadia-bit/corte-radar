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
# Linha inteira que TERMINA em dois-pontos, anunciando quem fala logo abaixo:
#   "Netanyahu on October 7:"
#   "Mosab Hassan Yousef, former Hamas member and former Shin Bet informant:"
# O padrao FALANTE nao pega esses porque tem palavra minuscula e virgula.
FALANTE_LINHA = re.compile(r"^\s*([A-Z][^:\n]{1,90}):\s*$")


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


def _nome_valido(nome: str, prefixos: list[str]) -> bool:
    nome = nome.strip()
    if not nome or len(nome) > 90:
        return False
    palavras = nome.split()
    if len(palavras) > 12:
        return False
    prefixos_norm = {_normalizar(p) for p in prefixos}
    if _normalizar(nome) in prefixos_norm:
        return False
    # primeira palavra tambem nao pode ser rotulo ("Writer", "Breaking"...)
    if _normalizar(palavras[0].rstrip(",")) in prefixos_norm:
        return False
    return True


def detectar_falante(texto: str, prefixos: list[str]) -> str | None:
    """Devolve o nome antes dos dois-pontos, se algum dos padroes bater."""
    limpo = _descascar_rotulos(texto, prefixos)
    linhas = limpo.split("\n")[:4]

    # padrao 1: "TRUMP: texto na mesma linha"
    for linha in linhas:
        m = FALANTE.match(linha)
        if m and _nome_valido(m.group(1), prefixos):
            return m.group(1).strip()

    # padrao 2: linha inteira terminando em dois-pontos
    for linha in linhas:
        m = FALANTE_LINHA.match(linha)
        if m and _nome_valido(m.group(1), prefixos):
            return m.group(1).strip()

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
