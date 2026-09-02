"""
Adaptadores de fonte de dados do X.

Todos devolvem a mesma estrutura (Post), então trocar de fornecedor
é mudar uma linha no config.yaml.

ECONOMIA (twitterapi.io):
    Antes: /user/last_tweets devolvia os 20 posts mais recentes de cada
    perfil, sempre. Pagava-se pelos 20 e o descarte (post ja visto, post
    sem video, resposta) acontecia depois, no seu lado.

    Agora: /tweet/advanced_search com tres filtros embutidos na consulta —
    since_time (so o que e novo), filter:videos (so post com video) e
    -filter:replies (sem respostas). A API devolve so o que interessa
    e a cobranca cai junto.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

# Epoch do Twitter: usado para descobrir a data a partir do ID do post.
EPOCH_TWITTER_MS = 1288834974657

# Teto da janela de busca. Se o bot ficar parado, nao volta mais que isso.
JANELA_MAXIMA_HORAS = 4


@dataclass
class Post:
    id: str
    autor: str
    texto: str
    url: str
    criado_em: datetime
    video_url: Optional[str] = None      # .mp4 direto, quando disponível
    duracao_seg: Optional[float] = None
    extra: dict = field(default_factory=dict)


class FonteBase:
    def posts_recentes(self, usuario: str, since_id: Optional[str]) -> list[Post]:
        raise NotImplementedError


def _data_do_id(tweet_id):
    """
    O ID do post do X carrega dentro de si o horario em que foi criado.
    Serve para transformar 'ja vi ate o post X' em 'busque a partir das Yh',
    sem precisar de nenhuma chamada extra.
    """
    try:
        ms = (int(tweet_id) >> 22) + EPOCH_TWITTER_MS
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- #
# 1) twitterapi.io  — ~US$0,15 por 1.000 tweets lidos
#    Alternativas equivalentes: Apify, ScrapeCreators, SocialCrawl.
# ---------------------------------------------------------------- #
class TwitterApiIO(FonteBase):
    BASE = "https://api.twitterapi.io/twitter"

    def __init__(self):
        self.key = os.environ["TWITTERAPI_IO_KEY"]

    def _janela(self, since_id, agora):
        """De que horario em diante buscar, para este perfil."""
        desde = _data_do_id(since_id) if since_id else None
        mais_antigo = agora - timedelta(hours=JANELA_MAXIMA_HORAS)
        if desde is None or desde < mais_antigo:
            desde = mais_antigo
        return desde

    def _buscar(self, consulta):
        """Roda a consulta e devolve (lista_de_tweets, quantos_foram_cobrados)."""
        bruto, cursor, pagina, cobrados = [], None, 0, 0
        while pagina < 3:
            params = {"query": consulta, "queryType": "Latest"}
            if cursor:
                params["cursor"] = cursor

            r = requests.get(
                f"{self.BASE}/tweet/advanced_search",
                headers={"X-API-Key": self.key},
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            dados = r.json()

            lote = dados.get("tweets") or []
            cobrados += len(lote)
            bruto.extend(lote)

            if not lote or not dados.get("has_next_page"):
                break
            cursor = dados.get("next_cursor")
            if not cursor:
                break
            pagina += 1
        return bruto, cobrados

    def _montar(self, t, usuario_padrao=None):
        """Transforma o tweet cru em Post. Devolve None se nao tiver video."""
        tid = str(t.get("id"))
        autor = (t.get("author") or {}).get("userName") or usuario_padrao or ""
        video_url, dur = self._extrair_video(t)
        if not video_url:
            return None
        return Post(
            id=tid,
            autor=autor,
            texto=t.get("text", ""),
            url=t.get("url") or f"https://x.com/{autor}/status/{tid}",
            criado_em=self._data(t.get("createdAt")),
            video_url=video_url,
            duracao_seg=dur,
        )

    def posts_recentes_lote(self, perfis, since_ids):
        """
        Busca os posts de TODOS os perfis numa consulta so.

        ECONOMIA: a twitterapi.io cobra um minimo por chamada, mesmo quando
        ela volta vazia. Quatro perfis em quatro chamadas pagavam quatro
        minimos por rodada; agrupados, paga-se um.
        """
        agora = datetime.now(timezone.utc)

        # a janela tem que cobrir o perfil mais atrasado de todos
        desde = min(self._janela(since_ids.get(u), agora) for u in perfis)
        desde_ts = int((desde - timedelta(minutes=1)).timestamp())

        grupo = "(" + " OR ".join(f"from:{u}" for u in perfis) + ")"
        consulta = f"{grupo} since_time:{desde_ts} filter:videos -filter:replies"

        bruto, cobrados = self._buscar(consulta)
        print(f"    busca unica ({len(perfis)} perfis): {cobrados} posts "
              f"cobrados (~{cobrados * 15} creditos)")

        saida = {u: [] for u in perfis}
        for t in bruto:
            post = self._montar(t)
            if not post:
                continue
            if post.autor not in saida:
                continue
            corte = since_ids.get(post.autor)
            if corte and post.id <= str(corte):
                continue
            saida[post.autor].append(post)
        return saida

    def posts_recentes(self, usuario, since_id=None):
        agora = datetime.now(timezone.utc)

        # De onde comecar a buscar: do ultimo post ja visto, ou do teto.
        desde = _data_do_id(since_id) if since_id else None
        mais_antigo = agora - timedelta(hours=JANELA_MAXIMA_HORAS)
        if desde is None or desde < mais_antigo:
            desde = mais_antigo

        # folga de 1 min para nao perder post na virada da rodada
        desde_ts = int((desde - timedelta(minutes=1)).timestamp())

        consulta = (
            f"from:{usuario} since_time:{desde_ts} "
            "filter:videos -filter:replies"
        )

        bruto, cursor, pagina, cobrados = [], None, 0, 0
        while pagina < 2:
            params = {"query": consulta, "queryType": "Latest"}
            if cursor:
                params["cursor"] = cursor

            r = requests.get(
                f"{self.BASE}/tweet/advanced_search",
                headers={"X-API-Key": self.key},
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            dados = r.json()

            lote = dados.get("tweets") or []
            cobrados += len(lote)
            bruto.extend(lote)

            if not lote or not dados.get("has_next_page"):
                break
            cursor = dados.get("next_cursor")
            if not cursor:
                break
            pagina += 1

        print(f"    @{usuario}: {cobrados} posts cobrados "
              f"(~{cobrados * 15} creditos)")

        posts = []
        for t in bruto:
            tid = str(t.get("id"))
            if since_id and tid <= since_id:
                continue
            video_url, dur = self._extrair_video(t)
            if not video_url:
                continue  # só interessa post com vídeo
            posts.append(Post(
                id=tid,
                autor=usuario,
                texto=t.get("text", ""),
                url=t.get("url") or f"https://x.com/{usuario}/status/{tid}",
                criado_em=self._data(t.get("createdAt")),
                video_url=video_url,
                duracao_seg=dur,
            ))
        return posts

    @staticmethod
    def _extrair_video(t):
        midias = (t.get("extendedEntities") or {}).get("media", []) \
              or (t.get("entities") or {}).get("media", []) \
              or t.get("media", [])
        for m in midias:
            if m.get("type") in ("video", "animated_gif"):
                variantes = (m.get("video_info") or {}).get("variants", []) \
                            or m.get("variants", [])
                mp4 = [v for v in variantes if v.get("content_type") == "video/mp4"]
                if not mp4:
                    continue
                melhor = max(mp4, key=lambda v: v.get("bitrate", 0))
                dur_ms = (m.get("video_info") or {}).get("duration_millis") \
                         or m.get("duration_millis")
                return melhor["url"], (dur_ms / 1000 if dur_ms else None)
        return None, None

    @staticmethod
    def _data(s):
        if not s:
            return datetime.now(timezone.utc)
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%SZ"):
            try:
                d = datetime.strptime(s, fmt)
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------- #
# 2) API oficial do X (v2, pay-per-use ~US$0,005 por post lido)
# ---------------------------------------------------------------- #
class XOficial(FonteBase):
    BASE = "https://api.x.com/2"

    def __init__(self):
        self.token = os.environ["X_BEARER_TOKEN"]
        self._ids = {}

    def _user_id(self, usuario):
        if usuario not in self._ids:
            r = requests.get(f"{self.BASE}/users/by/username/{usuario}",
                             headers=self._h(), timeout=30)
            r.raise_for_status()
            self._ids[usuario] = r.json()["data"]["id"]
        return self._ids[usuario]

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def posts_recentes(self, usuario, since_id=None):
        params = {
            "max_results": 20,
            "exclude": "replies",
            "tweet.fields": "created_at,text,attachments",
            "expansions": "attachments.media_keys",
            "media.fields": "type,duration_ms,variants,preview_image_url",
        }
        if since_id:
            params["since_id"] = since_id

        r = requests.get(f"{self.BASE}/users/{self._user_id(usuario)}/tweets",
                         headers=self._h(), params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        midias = {m["media_key"]: m
                  for m in payload.get("includes", {}).get("media", [])}

        posts = []
        for t in payload.get("data", []):
            chaves = (t.get("attachments") or {}).get("media_keys", [])
            video_url = dur = None
            for k in chaves:
                m = midias.get(k, {})
                if m.get("type") in ("video", "animated_gif"):
                    mp4 = [v for v in m.get("variants", [])
                           if v.get("content_type") == "video/mp4"]
                    if mp4:
                        video_url = max(mp4, key=lambda v: v.get("bit_rate", 0))["url"]
                        dur = (m.get("duration_ms") or 0) / 1000 or None
                    break
            if not video_url:
                continue
            posts.append(Post(
                id=t["id"], autor=usuario, texto=t["text"],
                url=f"https://x.com/{usuario}/status/{t['id']}",
                criado_em=datetime.fromisoformat(
                    t["created_at"].replace("Z", "+00:00")),
                video_url=video_url, duracao_seg=dur,
            ))
        return posts


def criar_fonte(nome: str) -> FonteBase:
    return {"twitterapi_io": TwitterApiIO, "x_official": XOficial}[nome]()
