"""
Adaptadores de fonte de dados do X.

Todos devolvem a mesma estrutura (Post), então trocar de fornecedor
é mudar uma linha no config.yaml.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests


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


# ---------------------------------------------------------------- #
# 1) twitterapi.io  — ~US$0,15 por 1.000 tweets lidos
#    Alternativas equivalentes: Apify, ScrapeCreators, SocialCrawl.
# ---------------------------------------------------------------- #
class TwitterApiIO(FonteBase):
    BASE = "https://api.twitterapi.io/twitter"

    def __init__(self):
        self.key = os.environ["TWITTERAPI_IO_KEY"]

    def posts_recentes(self, usuario, since_id=None):
        r = requests.get(
            f"{self.BASE}/user/last_tweets",
            headers={"X-API-Key": self.key},
            params={"userName": usuario, "includeReplies": "false"},
            timeout=30,
        )
        r.raise_for_status()
        bruto = r.json().get("data", {}).get("tweets", []) or r.json().get("tweets", [])

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
