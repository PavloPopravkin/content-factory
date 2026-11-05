# GitHub-аналоги и строительные блоки (срез 2026-11-05)

Роль в рое: исследователь. Расширяет `research/oss-landscape.md` (срез 2026-10-25). Проекты, разобранные там (TryPost, BrightBean, Mixpost, Postmill, MoneyPrinterTurbo, short-video-maker, AI-Youtube-Shorts-Generator, faster-whisper, editly, Remotion и др.), здесь не повторяю.

Метод. Stars, `pushed_at`, `created_at`, лицензия взяты из `api.github.com/repos/{owner}/{repo}` 2026-11-05 (без токена, `gh` на хосте нет). Поиск: `api.github.com/search/repositories` по 24 запросам, плюс npm registry `-/v1/search?text=postiz`. Возможности взяты из README (raw.githubusercontent.com) и исходников. Ограничение: часть поисковых запросов упёрлась в лимит 10/мин без токена (`ai shorts generator faceless video`, `photo to instagram caption ai telegram`, `content factory telegram`); выдача по ним неполная.

## 0. Главное

1. **Postiz уже содержит своего агента.** В теге v2.25.3 (наша живая версия) есть Mastra-агент `postiz` с 22 инструментами, чат-страница `/agents` и MCP-relay. Это готовый "разговорный" слой внутри Postiz, в который можно завести Telegram как ещё один транспорт. Минус: модель захардкожена `openai('gpt-5.2')`. Подробности в п. 1.1.
2. **Форма "фото в бот → AI-текст → апрув в Telegram → Postiz" уже повторена минимум 6 раз** (ourcaldo, PromoClown, n8n-ai-newsroom, marketing-agent, ai-smm-bot, ContentZavod). Все они моложе 6 месяцев, у всех 0-1★, у большинства нет лицензии. Код брать нельзя или незачем. Брать стоит паттерны, они сходятся.
3. **Устойчивый паттерн из всех аналогов: два бота или две роли.** Разговорный агент с LLM отдельно, апрув-бот без LLM отдельно, ключ Postiz только у паблишера, статус синхронизируется обратно из Postiz. У нас approval-by-hash уже ближе всех к этому.
4. **Для служения есть узкая ниша "проповедь → клипы"** (ConnectClips, sermon-shorts, sermon-pipeline, MIT). Готовой системы соцсетей для церквей или НКО на GitHub нет: запросы `church social media automation` и `nonprofit social media automation` дали 0 результатов.
5. **Карусель**: лучший кирпич `firstlinkai/content-machine` (MIT, Python, Pillow 1080×1350, публикует через Postiz, 250+ постов в проде по README).

## 1. Экосистема Postiz

### 1.1 Встроенный агент Postiz (ключевая находка)

- Mastra-агент: [`chat/mastra.service.ts`](https://github.com/gitroomhq/postiz-app/blob/v2.25.3/libraries/nestjs-libraries/src/chat/mastra.service.ts) регистрирует `agents: { postiz }`, хранилище `pStore` (Postgres, `@mastra/pg`).
- Инструменты (22 шт.): [`chat/tools/tool.list.ts`](https://github.com/gitroomhq/postiz-app/blob/v2.25.3/libraries/nestjs-libraries/src/chat/tools/tool.list.ts). Среди них `IntegrationListTool`, `IntegrationSchedulePostTool`, `PostsListTool`, `UploadFromUrlTool`, `GenerateImageTool`, `GenerateVideoTool`, `ClippingTool`, `UploadWidgetTool`, `DeletePostTool`.
- UI: `apps/frontend/src/app/(app)/(site)/agents/page.tsx` и `components/agents/agent.chat.tsx` (CopilotKit 1.72.0 в корневом `package.json`).
- MCP: `chat/mcp.relay.service.ts`, `chat/start.mcp.ts`.
- Наличие в v2.25.3 проверено: raw-файлы `mastra.service.ts`, `agents/page.tsx`, `upload.widget.tool.ts` по тегу v2.25.3 отдают HTTP 200. Последний релиз по API по-прежнему v2.25.3 от 2026-10-24.
- **Модель захардкожена**: [`load.tools.service.ts:116`](https://github.com/gitroomhq/postiz-app/blob/v2.25.3/libraries/nestjs-libraries/src/chat/load.tools.service.ts#L116) `model: openai('gpt-5.2')`, импорт `@ai-sdk/openai` (строка 3). Значит нужен платный OpenAI-ключ. Это нарушает правило "ID модели не хардкодить" и требует апрува Pavel'я на платное. Чтобы сменить модель, нужен патч форка (AGPL).
- Что брать: схему инструментов (имена, аргументы) как контракт нашего Telegram-агента. Telegram-бот может звать те же операции через Public API или MCP, не трогая ядро Postiz.
- Риск: апрува в инструментах нет, `IntegrationSchedulePostTool` пишет сразу в расписание. Для WWG (апрув Жени на каждый пост) агент Postiz напрямую не годится, нужен наш шлюз апрува перед ним. Не проверено: умеет ли агент создавать черновик (draft) вместо расписания.

### 1.2 Официальные репозитории gitroomhq (новое с октября)

| Репо | ★ / pushed / лицензия | Что это | Что брать | Риск |
|---|---|---|---|---|
| [gitroomhq/postiz-agent](https://github.com/gitroomhq/postiz-agent) | 562 / 2026-10-30 / AGPL-3.0 (LICENSE, API пишет NOASSERTION) | Официальный CLI `postiz` (npm 2.0.27 от 2026-10-30) + skill для Claude Code, Cursor, Gemini CLI, Grok, DeepSeek Harness. OAuth device flow или API key | CLI умеет загрузку медиа, которую MCP не делает. Готовый skill для наших агентов (Claude/Codex/agy) | Отдельный процесс, AGPL не заражает. По умолчанию смотрит в Postiz Cloud, для self-hosted нужен свой baseUrl |
| [gitroomhq/postiz-uploader](https://github.com/gitroomhq/postiz-uploader) | 12 / 2026-09-19 / нет | Дизайн-док и воркер нормализации медиа (ffmpeg/Pillow на RunPod Serverless, presigned URL in/out) | Идея: нормализовать каждое видео до отправки в Postiz, т.к. "Not every platform accepts 4K or odd codecs, so API customers hit rejections" (README) | Без лицензии, RunPod платный. У нас ffprobe-проверка уже есть, расширить её до нормализации |
| [gitroomhq/postiz-new-support-bot](https://github.com/gitroomhq/postiz-new-support-bot) | 4 / 2026-10-31 / нет | Discord-бот поддержки Postiz, мост в Intercom, Temporal | Пример, как сами авторы Postiz строят бота поверх Temporal (replay-правила при деплое) | Discord, не Telegram. Без лицензии |
| [gitroomhq/agent-media](https://github.com/gitroomhq/agent-media) → [agent-media-ai/agent-media](https://github.com/agent-media-ai/agent-media) | 83 (архив) / 1 / Apache-2.0 | Hosted MCP генерации видео/картинок/голоса, `make_ugc`, кредиты (100 = $1) | Список инструментов как образец (quote перед run, `rate_run`) | Платный облачный сервис. Не берём без апрува |
| [gitroomhq/postiz-n8n](https://github.com/gitroomhq/postiz-n8n) | 68 / 2025-10-07 / MIT | n8n-нода `n8n-nodes-postiz` 0.2.17 | Только если пойдём в n8n | Не обновлялась год |

### 1.3 Сторонние интеграции поверх Postiz

| Репо / пакет | ★ / pushed / лицензия | Что брать | Риск |
|---|---|---|---|
| [solomonneas/postiz-mcp](https://github.com/solomonneas/postiz-mcp) (npm `postiz-mcp` 0.2.0) | 2 / 2026-11-01 / MIT | 22 типизированных MCP-инструмента под self-hosted. Записи выключены по умолчанию (`POSTIZ_ENABLE_WRITE`), удаление требует `enableDelete` + `confirm: true`, локальный rate-limit guard | 2★, один автор. Паттерн "writes off by default" стоит повторить в нашем адаптере |
| Activepieces `@activepieces/piece-postiz` 0.1.2 ([код](https://github.com/activepieces/activepieces/tree/main/packages/pieces/community/postiz)) | часть activepieces | Действия: create-post, delete-post, find-available-slot, get-platform/post-analytics, list-integrations, list-posts, upload-file-from-url. Триггер new-post | Лицензию piece в этом проходе не проверял. Нужен ещё один сервис |
| npm `@pipedream/postiz`, `@infoinlet/mcp-social`, `@yonedaai/postree`, `agentic-publish` | - | Подтверждают, что Postiz Public API стал де-факто целью агентов | Малые пакеты, не исследовал |

### 1.4 Форки и клоны Postiz (новые)

| Репо | ★ / pushed / лицензия | Вывод |
|---|---|---|
| [FerdiKT/postflare](https://github.com/FerdiKT/postflare) | 8 / 2026-11-04 / AGPL-3.0, создан 2026-10-13 | Postiz-подобный планировщик целиком на Cloudflare Workers + D1 + R2. 36 интеграций, включая Google Business Profile и Telegram, "3 verified, the rest in beta" (README). Нам не подходит: мы уже держим Postiz, а GBP у них бета |
| [khanjer496-alt/postdelegate-app](https://github.com/khanjer496-alt/postdelegate-app), [Mohith1220/hookpost](https://github.com/Mohith1220/hookpost) | 0 / AGPL-3.0 | Ребрендинги на базе Postiz без заметной ценности |
| Postmill (из oss-landscape) | 39★ (было 27), pushed 2026-11-04 | Растёт медленно, вывод прежний |

## 2. Telegram-интейк и апрув (аналоги нашей формы)

| Репо | ★ / pushed / создан / лицензия | Форма | Что брать |
|---|---|---|---|
| [ourcaldo/postiz-telegram-bot](https://github.com/ourcaldo/postiz-telegram-bot) | 0 / 2026-10-30 / 2026-10-15 / нет | `/start` → загрузка медиа или URL (yt-dlp) → подпись → выбор каналов из Postiz → расписание через `/api/public/v1` | Самый точный аналог. Для IG `post_type=video`, если есть видео, иначе `post`. Каналы тянутся из Postiz живьём. `ALLOWED_USER_IDS` пустой = бот открыт всем, у нас так нельзя |
| [lioilsources/PromoClown](https://github.com/lioilsources/PromoClown) | 0 / 2026-11-01 / нет, Go | Два бота: агент (OpenClaw + vLLM Qwen, разговор, недельный план) и апрув-бот без LLM (ok / edit / no). SQLite, publisher раз в 5 мин и сразу после "ok", sync статуса из Postiz → published/failed. "Postiz API key jen zde" (ключ только у паблишера) | Архитектурный образец: разделение ролей, ключ Postiz в одном месте, обратная синхронизация |
| [saifali-55/n8n-ai-newsroom](https://github.com/saifali-55/n8n-ai-newsroom) | 0 / 2026-10-01 / нет | 78 нод n8n: Telegram + RSS → vision/OCR → LLM со строгим JSON → апрув текста → генерация картинки → апрув визуала (Original/Generated/Regenerate/Reject, ≤2 перегенерации) → Postiz | Два гейта (текст и визуал), валидация LLM-вывода по фиксированным полям с ошибкой вместо догадки, флаги `postiz_publish_started/complete` для идемпотентности, метка "иллюстрация" на AI-картинках, редактирование секретов в алертах |
| [Orland00/marketing-agent](https://github.com/Orland00/marketing-agent) | 0 / 2026-11-03 / нет | Мульти-тенант на одном Cloudflare Worker: Claude пишет в голосе бренда, апрув/правка/отказ в Telegram, cron-очередь публикации в Meta и X, ежедневный сбор статистики | Схема тенанта (brand voice, audience, hashtags) и сбор статистики обратно. Postiz не использует |
| [lunev51/ai-smm-bot](https://github.com/lunev51/ai-smm-bot) | 0 / 2026-07-23 / нет | Node: Claude пишет карусель, Satori + resvg рендерят 1080×1350, Meta Graph публикует IG/Threads/FB, grammY-панель с превью и ✅/❌ | Источник `custom`: фото пользователя в фирменной рамке + сгенерированный текст. Ровно случай WWG. Тема FIFO-очереди "тема списывается только после успешной публикации" |
| [mirasolutions06/ai-social-content-agent](https://github.com/mirasolutions06/ai-social-content-agent) | 0 / 2026-07-22 / MIT, Python | FastMCP-сервер: черновики, апрув, картинки, публикация | "Image source ladder": сначала предоставленные/лицензионные медиа, генерация только при нехватке. Это правило подходит WWG (607 своих фото) |
| [wilshawdirect/telegram-ops-kit](https://github.com/wilshawdirect/telegram-ops-kit) | 0 / 2026-10-21 / MIT, Python stdlib | Библиотека для апрув-ботов | Можно взять код: карточки апрува с nonce + idempotency + expiry, single-consumer polling с сохранённым offset (409 Conflict), operator guard, уважение `retry_after`, dead-man heartbeat |
| [sigurt33/ContentZavod](https://github.com/sigurt33/ContentZavod) | 1 / 2026-06-12 / нет | Русскоязычный "завод": JSON-посты в формате Postiz + обложки fal.ai + публикация через `postiz-agent` skill | Подтверждает: postiz-agent skill уже используют как слой публикации |
| [SAITS-Archive/saits-content-engine](https://github.com/SAITS-Archive/saits-content-engine) | 0 / архив / нет | Next.js + Drizzle + BullMQ, мульти-бренд, Claude + HeyGen + Higgsfield + Postiz | Архивирован. Только как пример white-label идеи |

Общий вывод по разделу. Ни один аналог не делает одновременно: мульти-тенант с разными правилами апрува (Женя на каждый пост, YourHelp по своим правилам), субботнюю остановку, журнал доставки и Postiz как бэкенд. Пробел из `oss-landscape.md` §"Пробел" остаётся открытым.

## 3. Разговорный слой (альтернатива)

| Репо | ★ / pushed / лицензия | Что это | Вывод |
|---|---|---|---|
| [langbot-app/LangBot](https://github.com/langbot-app/LangBot) | 18 729 / 2026-11-04 / Apache-2.0, Python | Платформа AI-ботов для Telegram, Discord, Slack, WeChat и др. Мульти-пайплайн, RAG, MCP, плагины, веб-панель управления | Сильный кандидат на разговорный слой, если не хотим писать бота сами. Но Pavel хочет админку внутри Postiz, а LangBot приносит вторую админку. Брать как запасной вариант или как образец pipeline-модели |

## 4. Служение и НКО

| Репо | ★ / pushed / лицензия | Что делает | Что брать |
|---|---|---|---|
| [connect-community-church/connectclips](https://github.com/connect-community-church/connectclips) | 3 / 2026-10-11 / MIT, Python | Проповедь (файл или YouTube) → faster-whisper large-v3 → Claude Sonnet выбирает 5-10 моментов с hook-заголовком и оценкой 0-100 → вертикальный reframe с трекингом лица → karaoke-субтитры → 1080×1920. ~15 мин на 50-мин проповедь, ~$0.05 Claude. Нужна NVIDIA 8 GB+ | Готовый модуль "проповедь → клипы" для тенанта служения. На S2 GPU нет (не проверял), значит только CPU-путь или другой хост |
| [pshouse/sermon-shorts](https://github.com/pshouse/sermon-shorts) | 1 / 2026-11-03 / MIT, Python | То же, плюс пропуск хвалы ("CCLI/music licensing generally does not cover social media"), объявлений и пожертвований; YuNet-детектор лица; громкость −13 LUFS с true-peak; рез по паузе между словами | Правило про музыку хвалы и авторские права вносим в правила тенанта служения. Аудио-нормализацию берём в clip-engine |
| [rvaccone/sermon-pipeline](https://github.com/rvaccone/sermon-pipeline) | 0 / 2026-10-04 / NOASSERTION, Go | Служение → видео для YouTube, srt, подкаст MP3 с главами, тексты, 3 клипа, 4 обложки, `Review.html` с сомнительным наверху | Идея одной страницы ревью "всё по одному материалу + сомнения сверху". Только Apple Silicon, прототип |
| [zhsongallen/CharityPen](https://github.com/zhsongallen/CharityPen) | 51 / 2023-08-15 / MIT | AI-помощник текстов для НКО | Заброшен, ничего не берём |
| [ChurchApps/FreeShow](https://github.com/ChurchApps/FreeShow) | 1 369 / 2026-11-04 / GPL-3.0 | Презентации для богослужений | Не про соцсети, вне scope |

## 5. Видео и карусели

| Репо | ★ / pushed / лицензия | Что брать | Риск |
|---|---|---|---|
| [firstlinkai/content-machine](https://github.com/firstlinkai/content-machine) | 0 / 2026-10-02 / MIT, Python | Одна JSON-схема "deck" → карусель 1080×1350 (Pillow) + сторис 1080×1920 + Reel (HyperFrames или Remotion) → публикация в IG, FB, Bluesky, Telegram через Postiz. В проде: 30 рилсов, 90 сторис-кадров, 5 каруселей, 250+ постов (README). Клиенты на `urllib`, без ORM и очередей | Лучший кирпич для карусели. Python и минимум зависимостей совпадают с нашим ядром. Скиллы `.claude/skills/firstlink-*` ссылаются на приватные файлы |
| [IgorShadurin/app.yumcut.com](https://github.com/IgorShadurin/app.yumcut.com) | 905 / 2026-10-24 / не определена (LICENSE 404) | Идея → сценарий, голос, визуал, субтитры, монтаж 9:16. Есть User API с ключами и OpenAPI | Лицензия не ясна, код не брать. Faceless-формат не подходит WWG (у них реальные фото) |
| [xixihhhh/clipforge](https://github.com/xixihhhh/clipforge) | 1 194 / 2026-10-26 / AGPL-3.0 | Фото товара → продающий ролик, исходник товара "фиксируется без искажений" | Идея "не искажать исходное фото" полезна для WWG до/после. Китайский e-commerce стек, AGPL |
| [leamsigc/ShortsGenerator](https://github.com/leamsigc/ShortsGenerator) | 360 / 2026-10-11 / MIT | Локальный генератор shorts | Слабее MoneyPrinterTurbo из прошлого среза |
| [SamurAIGPT/AI-Faceless-Video-Generator](https://github.com/SamurAIGPT/AI-Faceless-Video-Generator) | 530 / 2026-09-17 / MIT | Сценарий + голос + говорящее лицо | Не наш кейс |

## 6. Топ-10 по пользе для нас

| # | Что | Почему | Как использовать | Риск |
|---|---|---|---|---|
| 1 | Встроенный агент Postiz (Mastra, 22 инструмента, `/agents`, MCP) | Pavel хочет, чтобы Postiz сам вёл разговор. Это уже есть в нашей v2.25.3 | Контракт инструментов берём для Telegram-агента. Сам агент включаем только после патча модели (env вместо `openai('gpt-5.2')`) и шлюза апрува перед `schedulePost` | Хардкод OpenAI, нет апрува, патч форка AGPL |
| 2 | `gitroomhq/postiz-agent` (CLI `postiz` + skill) | Официальный, 562★, умеет загрузку медиа | Слой публикации для наших агентов и воркеров вместо самописных HTTP-вызовов, где это проще | Ориентирован на Cloud, проверить self-hosted baseUrl |
| 3 | PromoClown (паттерн двух ботов) | Ровно наша модель: разговор с LLM отдельно, апрув без LLM отдельно, ключ Postiz только у паблишера, sync статуса | Архитектура intake-бот + approval-бот в content-factory | Без лицензии, только идеи |
| 4 | `wilshawdirect/telegram-ops-kit` | MIT, Python stdlib, закрывает грабли апрув-бота | Взять nonce/expiry/idempotency карточек, single-consumer polling, heartbeat в наш approval-слой | 0★, один автор, ревьюить перед копированием |
| 5 | `firstlinkai/content-machine` | Карусель + сторис + рилс из одной схемы, публикация через Postiz, проверено в проде | Рендер карусели для WWG (607 фото) и YourHelp | 0★, приватные части не в репо |
| 6 | `ourcaldo/postiz-telegram-bot` | Самый короткий рабочий путь "медиа в бот → Postiz" | Образец UX шагов и маппинга `post_type` для IG | Без лицензии, нет апрува, нет мульти-тенанта |
| 7 | `saifali-55/n8n-ai-newsroom` | Два гейта апрува, строгий JSON, идемпотентные флаги, метка AI-картинок | Правила гейтов и формат LLM-контракта в нашем planner | Без лицензии, n8n-формат |
| 8 | ConnectClips + sermon-shorts | Единственные зрелые блоки под служение | Модуль "проповедь → клипы" для тенанта служения, правило про музыку хвалы | Нужен GPU, MIT, 1-3★ |
| 9 | `solomonneas/postiz-mcp` | MIT, writes-off-by-default, rate-limit guard для self-hosted | MCP для агентов Pavel'я на наш Postiz без OAuth-брокера | 2★ |
| 10 | `lunev51/ai-smm-bot` + `mirasolutions06/ai-social-content-agent` | Источник "фото клиента в фирменной рамке" и правило "свои медиа раньше генерации" | Правила отбора медиа для WWG | ai-smm-bot без лицензии; mirasolutions MIT |

Запасной вариант вне топа: LangBot как готовый разговорный слой, если писать бота самим окажется дороже.

## 7. Открытые вопросы

1. Модель агента Postiz. Варианты: (а) патч `load.tools.service.ts` на env-провайдер (OpenAI-совместимый endpoint, пул Antigravity или Groq), это форк и ребейз на каждом релизе; (б) не включать агента Postiz, а строить свой Telegram-агент на Public API/MCP. Нужно решение Pavel'я.
2. Умеет ли инструмент `IntegrationSchedulePostTool` создавать draft, а не расписание. Не проверено, читать `integration.schedule.post.ts`.
3. Использует ли живой Postiz на S2 страницу `/agents` и задан ли там `OPENAI_API_KEY`. Не проверено (read-only проверка контейнера без печати значений).
4. GPU для клипов служения: на S2 не проверял. Без GPU ConnectClips работает медленно или не работает.
5. Лицензия Activepieces piece-postiz не проверена.
6. Поиск упёрся в лимит GitHub API без токена; при наличии токена стоит повторить запросы из раздела "Метод".
