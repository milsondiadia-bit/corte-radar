# Corte Radar

Monitora @MarioNawfal, @Osint613, @clashreport e @nexta_tv, detecta quando sai um
**corte de fala** de figura pública (entrevista, coletiva, discurso, sessão,
depoimento) e avisa no Telegram **já com links prováveis da gravação completa**.

## Como funciona

```
4 perfis ──► só posts com vídeo
                  │
                  ▼
         [1] filtro por pontuação        ← barato, descarta a maior parte
             padrão "NOME:" + "Reporter:" + verbos + cargos
             menos penalidade por imagem de combate
                  │
                  ▼
         [2] transcrição do áudio        ← Whisper local, detecta idioma
             e traduz ru/he/ar/tr para inglês
                  │
                  ▼
         [3] dedup entre as 4 contas     ← o mesmo corte sai nos quatro
                  │
                  ▼
         [4] classificação com IA        ← confirma e extrai
             quem falou / onde / termos de busca / onde procurar
                  │
                  ▼
         [5] busca da íntegra no YouTube
                  │
                  ▼
         [6] alerta no Telegram
```

## O que faz o filtro funcionar nestas contas

Essas quatro contas seguem padrões de legenda bem definidos, e o filtro é
construído em cima deles:

| Sinal | Peso | Exemplo |
|---|---|---|
| `Reporter:` / `Q:` no texto | +6 | O Osint613 escreve a legenda como transcrição do diálogo: *"Reporter: Did you post that picture...? Trump: It wasn't a depiction..."* |
| Padrão `NOME:` no início | +5 | `TRUMP: "We will not allow..."` — descasca antes rótulos como `🚨 BREAKING:` e `JUST IN —` |
| Contexto de evento | +3 | press conference, hearing, Oval Office, Knesset |
| Gatilhos | +3 | "when asked", "told reporters", "speaking at" |
| Cargos e nomes próprios | +2 | president, IDF, Kremlin, Putin, Netanyahu |
| Citação entre aspas | +2 | |
| **Vocabulário de imagem de combate** | **−4** | "drone footage", "footage shows", "aftermath of", "smoke rises" |

A penalidade é o ponto crítico aqui. Clash Report e Nexta postam muito vídeo de
drone, ataque e rescaldo — que não é o que você quer. Mas é **penalidade, não
descarte**: um ministro pode estar *falando sobre* um ataque, e nesse caso os
outros sinais compensam.

Resultado nos testes com legendas típicas: 10 de 10 classificadas corretamente.

## Deduplicação

Os quatro perfis se sobrepõem muito — o mesmo corte do Trump sai nos quatro em
questão de minutos. O robô compara a transcrição de cada novo corte com os das
últimas 8 horas e só alerta o primeiro. Ajuste em `dedup:` no `config.yaml`.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt install ffmpeg          # necessário para o Whisper
cp .env.example .env             # preencha as chaves
python tools/resolve_channels.py # descobre os IDs dos canais do YouTube
```

Teste sem gastar nada:

```bash
python -m radar.main --testar-texto 'Reporter: Will you meet Putin? Trump: We will see.'
python -m radar.main --uma-vez
python -m radar.main               # loop contínuo
```

## De onde vêm os dados do X

| Rota | Custo de leitura | Observações |
|---|---|---|
| **API oficial (pay-per-use)** | ~US$ 0,005 por post lido | Desde fev/2026 <cite index="8-1">não há mais tier gratuito para novos desenvolvedores e os planos Basic/Pro fecharam para novas assinaturas</cite>. Cobra uma vez por post repetido no mesmo dia UTC. |
| **twitterapi.io / Apify / similares** | ~US$ 0,05–0,15 por 1.000 posts | <cite index="3-1">Fornecedores terceiros ficam bem abaixo da API oficial em cargas de leitura pesada</cite>. Termos de uso do X são área cinzenta. |
| **Nitter / snscrape** | grátis | Mortos. Não conte com isso. |

Esses quatro perfis são de altíssimo volume — Nawfal sozinho passa de 100 posts
por dia. Estimando ~250 posts/dia no total, ou 7.500/mês:

- API oficial: **~US$ 37/mês**
- twitterapi.io: **~US$ 1/mês**

A diferença aqui é grande o bastante para decidir sozinha a escolha. Os dois
adaptadores estão em `radar/sources.py`; troque a linha `fonte:` no `config.yaml`.

Custo da IA: só os candidatos chegam nela. Com Haiku, fica em frações de centavo
por post. A transcrição roda local e não custa nada além de CPU.

## Onde achar a íntegra

O `canais_desejados` já vem com os que mais publicam gravação completa deste tipo
de material: C-SPAN e Forbes Breaking News (coletivas americanas inteiras),
The White House, Reuters, AP, Sky News, LiveNOW from FOX, Al Jazeera, i24NEWS,
Bloomberg, United Nations, NATO, TRT World. Rode `tools/resolve_channels.py` e
cole o resultado em `canais_prioritarios`.

Um aviso: para falas de autoridades russas, iranianas e israelenses, a íntegra
muitas vezes **não está no YouTube**. Fica em kremlin.ru, no canal do Knesset, em
Telegram de ministério, na IRNA ou no UN Web TV. Por isso a IA devolve também o
campo `onde_procurar`, que aparece no alerta como pista para a busca manual.

A YouTube Data API tem cota gratuita de 10.000 unidades/dia e cada busca custa
100 — cerca de 100 buscas diárias de graça. Como o robô faz até 3 consultas por
alerta, isso cobre uns 30 alertas por dia.

## Calibrando

Tudo no `config.yaml`:

- **Perdendo cortes?** Baixe `score_minimo` para 3.
- **Vindo muito vídeo de guerra?** Aumente o peso de `penalidade_imagem` para −6.
- **Só interessa um tema** (só Oriente Médio, só Trump): adicione os nomes em
  `cargos` com peso alto, ou peça o filtro por tema no `SISTEMA` do `classify.py`.
- Depois de uns dias, rode
  `sqlite3 radar.db "select texto, analise from alertas"` para ver o que passou.

## Rodando 24/7

```ini
[Unit]
Description=Corte Radar
After=network.target

[Service]
WorkingDirectory=/caminho/para/corte-radar
ExecStart=/caminho/para/corte-radar/.venv/bin/python -m radar.main
Restart=always
User=seu_usuario

[Install]
WantedBy=multi-user.target
```

## Limites conhecidos

- **Repackaging.** Essas contas frequentemente republicam corte de terceiro com
  narração ou legenda própria. O prompt da IA já pede para marcar como falso
  quando o áudio é um narrador resumindo, mas não é infalível.
- O `yt-dlp` às vezes precisa de cookies para baixar vídeo do X. Se a transcrição
  começar a falhar em massa, exporte os cookies do navegador e passe `--cookies`.
- Nenhuma automação "descobre" a íntegra com certeza — ela entrega candidatos
  ordenados. A decisão final continua sua.
