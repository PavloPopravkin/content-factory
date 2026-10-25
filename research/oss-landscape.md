# Open-source ландшафт для Content Factory (срез 2026-10-25)

Роль в рое: исследователь. Обновление и расширение `~/www/yourhelp/SOCIAL-SCHEDULER-RESEARCH.md` (срез 2026-07-17).
Stars, `pushed_at`, лицензии взяты из GitHub REST API (`api.github.com/repos/{owner}/{repo}`) 2026-10-25.
Возможности взяты из README, официальных доков и исходников провайдеров (ссылки у каждого пункта).
Глубокий разбор Postiz (апгрейд, Temporal, P0) ведёт отдельная роль по `TASK-postiz.md`, здесь только как бэкенд.

## 0. Что изменилось с июля

| Проект | Июль 2026 | Октябрь 2026 | Что важно |
|---|---|---|---|
| Postiz | 33 421★ | 37 759★, pushed 2026-10-24, релиз v2.25.3 от 2026-10-24 | 4 релиза с октября закрывают security advisories (PSA-2026-…). Появился MCP (13 tools) и self-hosted MCP connector в v2.25.0 ([releases](https://github.com/gitroomhq/postiz-app/releases)) |
| TryPost | 398★, compose только dev | 737★, v2.0.0 от 2026-10-10, есть `compose.prod.yaml` на образе GHCR | Июльский минус "нет production Compose" снят ([docker docs](https://docs.trypost.it/self-hosting/docker.md)) |
| BrightBean Studio | 2 046★ | 2 569★, pushed 2026-10-25 | Появились REST API + MCP. Telegram и X по-прежнему нет |
| Mixpost Lite | 3 422★ | 3 863★, pushed 2026-03-16 | Lite не обновлялся 7 месяцев. API/MCP только в Pro |
| Новые | - | Postmill (форк Postiz), CogSend, yominpost, PostHive, Postsider | Все моложе 4 месяцев, ниже 250★ |

## 1. Self-hosted планировщики с публичным API

### 1.1 Сводная таблица

| | Postiz | TryPost | BrightBean Studio | Mixpost Pro | Postmill |
|---|---|---|---|---|---|
| Лицензия | AGPL-3.0 | AGPL-3.0 | AGPL-3.0 | коммерческая, $299 one-time (Lite MIT) | AGPL-3.0 |
| Стек | TS, Next.js + NestJS, Prisma, Postgres, Redis, Temporal | PHP 8.4, Laravel, Inertia/Vue, Postgres, Redis, Horizon, Reverb | Python, Django 5, HTMX, Postgres, worker, Caddy | PHP, Laravel package, Vue, Redis/Horizon, MySQL | TS, форк Postiz |
| ★ / pushed | 37 759 / 2026-10-24 | 737 / 2026-10-23 | 2 569 / 2026-10-25 | Lite: 3 863 / 2026-03-16 | 27 / 2026-10-24 (создан 2026-07-17) |
| Мульти-тенант | Organizations + "customers" (группы каналов) | Workspaces, роли, approvals | Orgs → workspaces → members, RBAC, Client role | "Multi-tenant support" в Pro | Orgs, свои app keys на организацию |
| IG feed / reels / stories | да / да / да | `instagram_feed` / `instagram_reel` / `instagram_story` | да / да (REELS) / да (STORIES) | да / да / да | наследует Postiz |
| FB feed / reels / stories | да / видео через `/{page}/videos` (URL `/reel/`) / да | `facebook_post` / `facebook_reel` / `facebook_story` | да / да (`video_reels`, 3-90 с) / в провайдере не найдено | да / да / в pricing не указано | наследует Postiz |
| Telegram канал | да | `telegram_post` | нет | нет | да |
| YouTube Shorts | обычный upload видео | `youtube_short` | да (Shorts в провайдере) | да ("videos and Shorts") | да |
| TikTok | да (`tiktok`, `tiktok.business`) | `tiktok_video`, `tiktok_photo` | да | да | да |
| LinkedIn page | да (`linkedin.page`) | `linkedin_page_post` | да (Company) | да | да |
| Public API | да, `/public/v1` | да, REST | да, `/api/v1/` | да | да + Node SDK |
| MCP | да, 13 tools | да, 80+ tools | да, `/api/v1/mcp` | да | - |
| Webhooks наружу | да, на публикацию | да, подписанные, с replay | в README не описаны | - | - |
| Admin UI | полный SaaS-UI, календарь | полный UI, календарь, очереди | полный UI + Django admin | полный UI | полный UI + дизайн-редактор |

Источники по строкам:
- Postiz провайдеры: [каталог `integrations/social`](https://github.com/gitroomhq/postiz-app/tree/main/libraries/nestjs-libraries/src/integrations/social). Типы постов: [`instagram.dto.ts`](https://github.com/gitroomhq/postiz-app/blob/main/libraries/nestjs-libraries/src/dtos/posts/providers-settings/instagram.dto.ts) и [`facebook.dto.ts`](https://github.com/gitroomhq/postiz-app/blob/main/libraries/nestjs-libraries/src/dtos/posts/providers-settings/facebook.dto.ts) содержат `@IsIn(['post', 'story'])`. Reels в Instagram задаются видео-постом (trial reels, аудио "only to Reels" в [`instagram.provider.ts`](https://github.com/gitroomhq/postiz-app/blob/main/libraries/nestjs-libraries/src/integrations/social/instagram.provider.ts)). FB-видео идёт через `/{id}/videos`, отдельного типа reel нет ([`facebook.provider.ts`](https://github.com/gitroomhq/postiz-app/blob/main/libraries/nestjs-libraries/src/integrations/social/facebook.provider.ts)). Telegram шлёт `sendVideo` и `sendMediaGroup` ([`telegram.provider.ts`](https://github.com/gitroomhq/postiz-app/blob/main/libraries/nestjs-libraries/src/integrations/social/telegram.provider.ts)).
- TryPost: [README](https://github.com/trypostit/trypost), список `content_type` из [Create post](https://docs.trypost.it/api-reference/posts/create-post.md), правила из [Posting guide](https://docs.trypost.it/api-reference/guides/posting.md).
- BrightBean: [README, таблица Supported Platforms и раздел "API & MCP for Agents"](https://github.com/brightbeanxyz/brightbean-studio#api--mcp-for-agents). STORIES/REELS в [`providers/instagram.py`](https://github.com/brightbeanxyz/brightbean-studio/blob/main/providers/instagram.py), `video_reels` в [`providers/facebook.py`](https://github.com/brightbeanxyz/brightbean-studio/blob/main/providers/facebook.py).
- Mixpost: [pricing](https://mixpost.app/pricing), [API docs](https://docs.mixpost.app/api/), [MCP docs](https://docs.mixpost.app/mcp/).
- Postmill: [README](https://github.com/postmill-ai/postmill-app). Там прямо написано "Postmill began as a fork of Postiz".

### 1.2 Модель авторизации API (ключевое для мульти-тенанта)

**Postiz** ([Public API](https://docs.postiz.com/public-api/introduction.md), [Developer settings](https://docs.postiz.com/general/settings/developers.md)):
- Ключ идёт в `Authorization: <key>` без префикса. OAuth-токен приложения идёт в тот же заголовок с префиксом `pos_`.
- Ключ принадлежит всему workspace (организации), `user` у него `null` ([Get Connected Account](https://docs.postiz.com/public-api/integrations/me.md)). Для N организаций нужно N ключей или одно OAuth-приложение.
- Лимит 90 запросов/час на create-post в self-hosted, меняется env `API_LIMIT`. Несколько постов в одном запросе считаются одним вызовом ([public-api](https://docs.postiz.com/public-api)).
- Полезные эндпоинты: `GET /integrations`, `GET /groups` (customers), `POST /upload`, `POST /posts`, `find-slot`, `change-status` draft↔schedule, `settings` (patch без перезапуска workflow), аналитика, connect-channel OAuth URL ([индекс](https://docs.postiz.com/llms.txt)).
- MCP endpoint: tools `integrationList`, `schedulePostTool`, `postsListTool`, `clippingTool` и другие, авторизация API key или OAuth ([MCP intro](https://docs.postiz.com/mcp/introduction.md)).
- Webhook на публикацию ([webhooks](https://docs.postiz.com/general/automations/webhooks.md)).

**TryPost** ([API intro](https://docs.trypost.it/api-reference/introduction.md)):
- `Authorization: Bearer <key>`. Ключ работает только у админа workspace. Правило "One key, one workspace": для нескольких workspace нужен ключ в каждом.
- MCP использует OAuth sign-in. MCP-токен в REST получает `403 Personal access token required.`
- Есть batch-создание по destinations с общим `post_group_id`, approve/reject, recurrence, queue slots, upload-token, attach-from-URL (≤10 файлов, ≤20 с на загрузку), подписанные webhooks с replay ([индекс](https://docs.trypost.it/llms.txt)).
- Stories без подписи: `instagram_story` и `facebook_story` текст не публикуют ([Posting guide](https://docs.trypost.it/api-reference/guides/posting.md)).

**BrightBean** ([README API & MCP](https://github.com/brightbeanxyz/brightbean-studio#api--mcp-for-agents)):
- `Authorization: Bearer bb_studio_...`. Ключ привязан к workspace, может быть ограничен списком соц-аккаунтов, наследует подмножество прав (`create_posts`, `publish_directly`, `upload_media` и др.).
- Лимиты 120 записей/мин на ключ, 1000 вызовов/час, 20 000/день. Поддерживается `idempotency_key`.
- Credentials соцсетей (Meta app и т.д.) задаются per organization через Django admin. Это редкое свойство: каждая организация может работать на своём developer app.

### 1.3 Прочие найденные, не кандидаты

| Проект | ★ / pushed | Почему нет |
|---|---|---|
| [CogSend](https://github.com/cogsend/cogsend) | 239 / 2026-10-22, MIT, Cloudflare Workers | Только Mastodon, Bluesky, LinkedIn, Threads, X. Нет IG/FB/Telegram |
| [Shoutrrr](https://github.com/coollabsio/shoutrrr) | 456 / 2026-10-24, Apache-2.0 | В июле не было TikTok, YouTube, Telegram |
| [yominpost](https://github.com/mrlong0129/yominpost) | 99 / создан 2026-10-05, MIT | TikTok и Threads "simulated for now". Интересен как AI-слой, см. §2 |
| [PostHive](https://github.com/AstaBlackClove/posthive), [Postsider](https://github.com/lumizone/postsider) | 20 и 13★ | Слишком молоды для прод-бэкенда |
| [Socioboard 5.0](https://github.com/socioboard/Socioboard-5.0) | репо не ответил в API 2026-10-25 | В июле уже слабая поставка, без Telegram |

## 2. Open-source "контент-фабрики" и AI-конвейеры

**Главный вывод: готового open-source конвейера "участники скидывают сырьё → LLM отбирает → монтаж рилса с субтитрами → подпись в голосе бренда → планировщик" не найдено.**
Поиск по GitHub (`content factory social media ai`, `telegram bot content pipeline instagram`, `opus clip open source shorts`, `auto captions short video whisper`, все с фильтром `pushed:>2026`) дал либо генераторы из темы, либо нарезку длинного видео, либо репо с 0-3★.

### 2.1 Ближе всего по идее

| Проект | ★ / pushed / лицензия | Что делает | Что берём |
|---|---|---|---|
| [Postiz AI agent + clipping](https://docs.postiz.com/general/clipping.md) | в составе Postiz | Длинное YouTube-видео → вертикальные клипы 1080×1920 с субтитрами → черновики постов. На self-hosted "нужно настроить clipping на инстансе", минут-лимита нет | Источник только YouTube-ссылка, не сырьё волонтёров. Годится как опция, не как ядро |
| [langchain-ai/social-media-agent](https://github.com/langchain-ai/social-media-agent) | 2 945 / 2026-10-25 / MIT | URL → пост в Twitter/LinkedIn, human-in-the-loop, ingestion из Slack, LangGraph, авторизация через Arcade | Паттерн HITL-апрува. Медиа-конвейера нет, сети не наши |
| [yominpost](https://github.com/mrlong0129/yominpost) | 99 / 2026-10-05 / MIT, FastAPI + SQLite | "Brand DNA → trends → ideation → format router → copy → visual → short-video storyboard + SRT → QA self-critique". Драйверы `claude_code`, `codex`, `agy`, `anthropic` с fallback. MCP без publish tool, публикует человек в UI | Идея slot-конвейера и driver-fallback совпадает с нашим intake. Реального монтажа видео нет, проект 3 недели |
| [Postmill](https://github.com/postmill-ai/postmill-app) | 27 / 2026-10-24 / AGPL | Форк Postiz: brand-voice profiles, prompt library, RAG по своему контенту, guardrails, per-org AI budget, агент в Telegram/Slack, мульти-формат дизайн (post/reel/story варианты) | Подтверждает спрос на "brand voice поверх Postiz". Молодой форк, ставить в прод рано |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 135 014 / 2026-10-25 / MIT | Тема → сценарий → озвучка → футаж (Pexels/Pixabay или свои файлы) → субтитры → музыка → видео. WebUI + API ([README](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/README-en.md)) | Генерация из темы, а не отбор реальных кадров. Как референс subtitle/ffmpeg-сборки |

### 2.2 Нарезка и монтаж коротких видео

| Проект | ★ / pushed / лицензия | Оценка |
|---|---|---|
| [Anil-matcha/AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) | 5 593 / 2026-10-24 / MIT | LLM-выбор хайлайтов, faster-whisper, автокроп в вертикаль. Есть `--mode local` (yt-dlp + faster-whisper + ffmpeg/opencv) и JSON-вывод. Ближе всего к talking-head "Голоси табору". По умолчанию ходит в платный MuAPI |
| [modelscope/FunClip](https://github.com/modelscope/FunClip) | 6 449 / 2026-10-08 / MIT | LLM-клиппинг с ASR от Alibaba. Акцент на китайский ASR, для укр. речи проверять |
| [WyattBlue/auto-editor](https://github.com/WyattBlue/auto-editor) | 5 624 / 2026-10-25 / Unlicense | Вырезает тишину и паузы, CLI. Хороший шаг препроцессинга |
| [ColinGPT9/clips-studio](https://github.com/ColinGPT9/clips-studio), [xixihhhh/hotclip](https://github.com/xixihhhh/hotclip), [fralapo/clippyme](https://github.com/fralapo/clippyme) | 150 / 371 / 61★ | Opus Clip-клоны, AGPL/AGPL/MIT. hotclip заточен на китайские платформы. Toy/early |
| [RayVentura/ShortGPT](https://github.com/RayVentura/ShortGPT), [gyoridavid/short-video-maker](https://github.com/gyoridavid/short-video-maker) | 8 070 / 2025-02-10; 1 431 / 2025-06-21 | Заброшены больше 4 месяцев |
| n8n-воркфлоу "Telegram → контент" ([пример](https://github.com/Anbutechofficial/Social-Media-Content-Pipeline)) | 0★ | Учебные, не переиспользуемы |

Итог по §2: монтаж у нас уже сильнее найденного (clip-engine: talking-head runbook, face-tracking, субтитры). Переиспользовать стоит отдельные библиотеки (§3), не готовые фабрики.

## 3. Библиотеки для встраивания

### 3.1 Telegram-intake

| Библиотека | ★ / pushed / лицензия | Заметка |
|---|---|---|
| [aiogram](https://github.com/aiogram/aiogram) | 5 905 / 2026-10-22 / MIT | Async Python, FSM для диалогов "пришли подпись/кто на фото" |
| [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) | 29 531 / 2026-10-19 / LGPL-3.0 ([README](https://github.com/python-telegram-bot/python-telegram-bot#license); GitHub API показывает GPL-3.0) | Самый зрелый Python-вариант |
| [grammY](https://github.com/grammyjs/grammY) | 3 783 / 2026-10-16 / MIT | TS, если сервис на Node рядом с Postiz |
| [Telegraf](https://github.com/telegraf/telegraf) | 9 204 / 2026-09-24 / MIT | TS, старше grammY |
| [tdlib/telegram-bot-api](https://github.com/tdlib/telegram-bot-api) | 4 502 / 2026-08-26 / BSL-1.0 | Локальный Bot API сервер. Обязателен для видео: облачный Bot API отдаёт боту файлы только до 20 MB, локальный сервер снимает лимит загрузки до 2000 MB ([Bot API: getFile и local server](https://core.telegram.org/bots/api#using-a-local-bot-api-server)) |

### 3.2 Распознавание речи и субтитры

| Библиотека | ★ / pushed / лицензия | Заметка |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 26 121 / 2026-10-25 / MIT | CTranslate2-бэкенд Whisper, word timestamps. База для CPU на S2 |
| [WhisperX](https://github.com/m-bain/whisperX) | 24 836 / 2026-10-22 / BSD-2-Clause | Точное выравнивание слов + диаризация. Нужно для караоке-субтитров и интервью на 2 голоса |
| [stable-ts](https://github.com/jianfch/stable-ts) | 2 281 / архивирован | Не брать, репозиторий archived |
| [m1guelpf/auto-subtitle](https://github.com/m1guelpf/auto-subtitle), [unconv/captacity](https://github.com/unconv/captacity) | последний push 2024 | Заброшены |

### 3.3 Монтаж и рендер

| Библиотека | ★ / pushed / лицензия | Заметка |
|---|---|---|
| ffmpeg + [MoviePy](https://github.com/Zulko/moviepy) | 15 034 / 2026-08-26 / MIT | Python-обвязка, живая |
| [Remotion](https://github.com/remotion-dev/remotion) | 67 313 / 2026-10-25 / своя лицензия | Бесплатно для non-profit и for-profit до 3 сотрудников, иначе нужна Company License ([LICENSE.md](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md)). Фонды проходят, коммерческой компании надо проверять по штату |
| [editly](https://github.com/mifi/editly) | 5 545 / 2025-05-12 / MIT | Затихает |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | см. §2.2 | Обрезка тишины |

### 3.4 Простая админка

| Вариант | ★ / pushed / лицензия | Когда |
|---|---|---|
| Django admin (как в BrightBean) | - | Если ядро на Django. Даром CRUD по организациям, каналам, слотам |
| [starlette-admin](https://github.com/jowilf/starlette-admin) | 1 066 / 2026-10-24 / MIT | FastAPI/Starlette + SQLAlchemy. Ближе всего к нашему Python-стеку autopost |
| [Filament](https://github.com/filamentphp/filament) | 32 334 / 2026-10-25 / MIT | Если ядро на Laravel (пара к TryPost) |
| [Refine](https://github.com/refinedev/refine) | 35 939 / 2026-09-10 / MIT | React-фреймворк админок, требует сборки фронта |
| [AdminJS](https://github.com/SoftwareBrothers/adminjs) | 8 993 / 2025-07-15 / MIT | Node, затихает (push 3+ месяца назад) |
| [Directus](https://github.com/directus/directus) | 38 631 / 2026-10-23 / GitHub API: NOASSERTION | Headless CMS + админка из схемы. Лицензию проверить по LICENSE до выбора |

## 4. Рекомендация

**Бэкенд публикации: Postiz.** Причины:
1. Он уже работает у нас в двух инстансах.
2. Из всех кандидатов только Postiz и TryPost покрывают весь список: IG feed/reels/stories, FB feed/stories, Telegram, YouTube, TikTok, LinkedIn page.
3. Есть public API, MCP, OAuth-приложения (`pos_`), webhooks, organizations и customers. Это готовая мульти-тенант изоляция: одна организация Postiz на одну организацию фабрики.
4. Самое большое сообщество (37 759★) и частые security-релизы.

Оговорки, которые надо закрыть до интеграции:
- Апгрейд до ≥ v2.25.3. Релизы v2.24.0-v2.25.3 закрывают несколько PSA ([releases](https://github.com/gitroomhq/postiz-app/releases)), наш v2.21.10 ниже их всех.
- Лимит 90 create-post/час на инстанс. Для 54 страниц поднять `API_LIMIT` и слать посты пачкой в одном запросе.
- FB-reel в Postiz - это видео через `/{page}/videos`, а не `video_reels`. Проверить на живой странице, как Meta это показывает.
- YouTube Shorts в Postiz не отдельный тип. Shorts определяется самим видео (вертикаль, длина).

**Запасной бэкенд: TryPost.** У него самая чистая API-модель (явный `content_type` с `facebook_reel` и `youtube_short`, approvals, queue slots, подписанные webhooks), а prod-Compose теперь есть. Июльский bake-off Postiz vs TryPost остаётся в силе. Поэтому публикацию в нашей библиотеке держать за интерфейсом-адаптером `Publisher` (Postiz, TryPost, текущий `slots.py`).

**BrightBean** не подходит как единый бэкенд, пока нет Telegram. Его идея per-organization platform credentials стоит взять в нашу модель данных.

**Пробел, который закрывает наша библиотека** (ни один найденный проект этого не делает):
1. Intake от людей: Telegram-бот (aiogram + локальный Bot API для видео > 20 MB) и upload-ссылка. Запись "кто прислал, когда, для какой организации".
2. Единое хранилище медиа: дедуп, EXIF-поворот, сжатие, транскрипция голосовых (faster-whisper/WhisperX).
3. LLM-отбор по инструкциям организации: что годится, политика лиц детей, сверка имени заезда (правила сейчас живут в `TASK-INTAKE.md`).
4. Авто-монтаж: рилсы с субтитрами и talking-head через clip-engine, сторис-нарезка.
5. Тексты в голосе бренда: профиль голоса на организацию, примеры, запреты (у YourHelp "благодійний внесок").
6. План: слоты по каналам организации → отправка в Postiz API (organization + integration IDs) → статус обратно по webhook.
7. Админка: организации, каналы, план, автор материала, правка/отмена, апрув в Telegram.
8. Правила расписания поверх бэкенда, включая субботнюю остановку автопостинга. Встроенной функции в доках Postiz и TryPost я не нашёл, её держит наш планировщик.
