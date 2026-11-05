# Postiz: разбор исходников под "одну большую систему" (служение, благотворительность, коммерция)

Дата: 2026-11-05. Исходники: `git clone --filter=blob:none https://github.com/gitroomhq/postiz-app` в `/tmp/claude-1003/postiz-src/postiz-app`.
Читал тег **v2.25.3** (commit `a5affe62`, 2026-10-24). Это совпадает с живым инстансом на S2 и это **последний релиз** (GitHub `releases/latest` = v2.25.3, published 2026-10-24T14:16Z). На `main` после тега 10+ коммитов (HEAD `bd8353f0`, 2026-11-03: settings options, getPosts event loop fix, IG standalone token fix, invite fixes).
Живую систему не трогал. Пути ниже относительно корня репозитория, номера строк по v2.25.3.

Дополняет, а не повторяет `research/postiz-backend.md` (разделы 3-6 там уже покрывают providers IG/FB/TG/YT/TikTok/LinkedIn, multi-tenancy, ресурсы). Здесь новое: GMB, карусели FB, точки вставки политики, approval/preview, AI/MCP/чат, фронтенд, форк, AGPL.

---

## (a) Providers: GMB, карусели, reels, stories

Архитектура: каждый provider = класс `extends SocialAbstract implements SocialProvider` в `libraries/nestjs-libraries/src/integrations/social/*.provider.ts` (36 файлов). Контракт в `social.integrations.interface.ts:179-241`: `identifier`, `scopes`, `editor`, `dto` (class-validator настройки), `checkValidity()`, `post()`, опционально `postPending()` (двухфазная публикация с поллингом), `comment()`, `analytics()`, `mention()`, `customFields()`. Декоратор `@Rules("...")` даёт текстовые правила AI-агенту. UI настроек провайдера: `apps/frontend/src/components/new-launch/providers/<id>/`.

### Google Business Profile = `gmb.provider.ts` (650 строк). Есть, но базовый.
- `identifier='gmb'`, scope `business.manage` (`:47-51`), лимит текста 1500 (`:55-57`), `maxConcurrentJob=3`.
- Публикация: `POST https://mybusiness.googleapis.com/v4/{accounts/x/locations/y}/localPosts` (`:477`). Типы `topicType` STANDARD / EVENT / OFFER, CTA `callToActionType+Url`, поля event (title, даты, время) и offer (coupon, url, terms) (`:423-474`).
- **Медиа: только первый файл** (`firstPost.media[0]`, `:439-447`); `@Rules` прямо говорит "optionally one image" (`:39-41`). Карусели в GBP нет. Видео передаётся как `mediaFormat:'VIDEO'`, но принимает ли его Google Local Posts API, **не проверено**.
- Обрабатывает `state==='REJECTED'` (политика Google) и отсутствие `name` в ответе как BadBody (`:493-509`). Аналитика через Performance API (`:556`, `:640`).
- Нет `comment()` и нет ответов на отзывы (reviews). Отзывы GBP для WWG придётся делать своим адаптером.
- Locations выбираются на шаге `isBetweenSteps` (`:207-327`): account management v1 + business information v1.
- Вывод для WWG: для апдейтов и офферов с одной фото годится. Каденция GBP (1 фото + CTA "Book") ложится. Подключение требует своего Google Cloud app с одобренным доступом к Business Profile API (квоты по заявке Google; не проверено на нашем проекте).

### Facebook Page = `facebook.provider.ts`
- Обычный пост (`postNonStory`, `:825`): **если первый файл mp4, публикуется одно видео** через `/{page}/videos` (`:835-862`), ссылка строится как `/reel/{id}`. Иначе все фото загружаются `published:false` и прикрепляются `attached_media` к `/{page}/feed` (`:864-911`).
- Значит "карусель FB" = **мультифото-пост (сетка)**, не листаемая link-карусель (`child_attachments`) и не альбом (`/{page}/albums`). Микс фото+видео в одном посте не поддержан: видео берётся только если оно первое, остальное игнорируется.
- Stories: `post_type:'story'` (`facebook.dto.ts:102-104`, `checkValidity :51-60`), каждое медиа отдельной story (`postPending :565+`).
- Явного Reels-эндпоинта (`/video_reels`) нет (это уже отмечено в postiz-backend.md, остаётся в силе).
- Есть `comment()` (`:989`) и аналитика по видео/reels (`:1086-1240`).

### Instagram (FB-linked) = `instagram.provider.ts`
- Карусель до 10 элементов (`checkValidity :60-62`), дочерние элементы `is_carousel_item=true` (`:753`), финал `media_type=CAROUSEL&children=` (`:986`). Фото+видео в карусели можно.
- Reels: одно mp4 + `post_type:'post'` даёт `media_type=REELS` с `cover_url`/`thumb_offset` (`:760-768`). Trial reels (`is_trial_reel`), музыка (`audio`, `audioSearch :1257`), collaborators (`:734-746`).
- Stories фото/видео (`:758`, `:772`).
- Вывод: IG закрывает карусели WWG полностью. FB-карусель в смысле "листаемая" придётся делать своим Meta-адаптером или жить с мультифото-постом.

---

## (b) Жизненный цикл поста и Temporal: куда вставить политику

Схема: `Post.state` = `QUEUE | PUBLISHED | ERROR | DRAFT` (`schema.prisma:1773-1778`). `CreationMethod` WEB/MCP/API/AUTOPOST/CLI (`:1814`).

Путь:
1. `POST /public/v1/posts` или UI → `PostsService.createPost` (`posts.service.ts:1148`), `type` = `draft|schedule|now|update` (`create.post.dto.ts:100-101`).
2. `startWorkflow` (`posts.service.ts:937`): гасит запущенные workflow этого поста, **для DRAFT выходит без запуска** (`:964-966`), иначе стартует `postWorkflowV112` с `workflowId=post_{id}` (`:972-975`).
3. Workflow `apps/orchestrator/src/workflows/post-workflows/post.workflow.v1.1.2.ts`:
   - `getPost` и проверка `state==='QUEUE'` (`:153-164`);
   - **`sleep` до `publishDate`** (`:167-173`) — workflow просто спит, никакой проверки политики после пробуждения нет;
   - `getPostsList` (`:182`), проверки `refreshNeeded` и `disabled` канала (`:190-227`);
   - публикация `postSocialPending` (`:442`) → activity `postSocialInternal` (`post.activity.ts:331`);
   - комментарии, затем `sendWebhooks` (`:596`) и plugs (`:603-637`).
4. Смена статуса `PUT /public/v1/posts/:id/status` → `changePostStatus` (`posts.service.ts:1384-1407`): draft ↔ schedule, при schedule заново стартует workflow.

Точки вставки pre-publish политики (шабат, апрув, лимиты):

| Вариант | Где | Цена и риск |
| --- | --- | --- |
| **0. Без форка** (текущее решение DECISIONS 2026-10-25) | Фабрика держит план; в Postiz пост живёт как DRAFT; в слот фабрика проверяет шабат+апрув+лимиты и делает `type:'now'` или `status→schedule` | Ноль кода в Postiz. Не защищает от человека, который нажмёт "Add to calendar" прямо в UI Postiz. |
| 1. Guard в activity | В начале `postSocialInternal` (`post.activity.ts:331`) вызвать policy-сервис; при запрете бросить `BadBody` | Activity-код можно менять без новой версии workflow: upstream так и делает, комментарий `post.activity.ts:274-278` ("rethrow as BadBody so every workflow version - frozen once on main - treats it as a terminal error"). Минус: пост уйдёт в `ERROR`, а не "отложен". Нужен второй шаг: фабрика переносит его на исход субботы. |
| 2. Guard при планировании | В `createPost`/`changeDate`/`changePostStatus` (`posts.service.ts:1148`, `:1409`, `:1384`) отклонять `publishDate` в окне шабата или без апрува | Ловит всё, что идёт через UI/API/MCP. Не ловит уже спящие workflow, если правило поменялось. Конфликты при rebase: `posts.service.ts` самый горячий файл (45 коммитов с мая). |
| 3. Новый шаг в workflow | Activity `checkPolicy` после `sleep` (`:173`) с циклом "ждать до разрешённого окна" | Правильнее всего семантически (отложить, а не ошибка), но меняет детерминизм: нужен новый файл `post.workflow.v1.1.3.ts` и перенос при каждом upstream-изменении workflow (13 коммитов в каталоге с мая, 12 версий файлов по 400-730 строк). Дорого держать в форке. |

Рекомендация: **0 как основа + 1 как предохранитель** (fail-closed, если policy-сервис недоступен). 2 добавить только при открытии UI Postiz людям, которые сами ставят посты. 3 не делать.

**Нативного approval нет.** Поиск по фронту/бэку `approv` находит только OAuth approved-apps, Farcaster и `approvedSubmitForOrder` (это marketplace заказов, `schema.prisma:477`, `:1808`). Issue #1758 "Granular RBAC for Approval Workflow" закрыт **not_planned** 2026-11-03 (https://github.com/gitroomhq/postiz-app/issues/1758). Ждать от upstream бессмысленно.

**Нативный preview + комментарии есть, и это полезно для Жени:**
- Страница `/p/[id]` (`apps/frontend/src/app/(app)/(preview)/p/[id]/page.tsx`), кнопка "Share with a client" (`components/preview/copy.client.tsx:20`).
- Публичный API без авторизации: `GET /public/posts/:id`, `GET|POST /public/posts/:id/comments` (`apps/backend/src/api/routes/public.controller.ts:54-90`). Комментарии с якорем на фрагмент текста, ответы, resolve (`posts.service.ts:1606-1750`), recaptcha.
- `getPostsRecursively` не фильтрует state, поэтому превью DRAFT работает (по коду; **не проверено** на живом инстансе).
- Нет кнопки "Одобрить" и нет записи "кто одобрил". Апрув-по-хешу остаётся в фабрике; preview Postiz можно использовать как "посмотри, как будет выглядеть".

Webhooks (`Webhooks` модель `schema.prisma:662`) шлются только **после** публикации (`sendWebhooks`, `post.activity.ts:509`). Pre-publish webhook нет.

---

## (c) AI-агент, MCP, Telegram: можно ли уже "говорить с Postiz"

- **Встроенный агент есть.** Mastra Agent `postiz` (`libraries/nestjs-libraries/src/chat/load.tools.service.ts:60-130`), инструкции `:67-115`, **модель захардкожена `openai('gpt-5.2')`** (`:116`), память Mastra в Postgres (`:118`, таблицы `mastra_*` в `schema.prisma:756-1610`). 22 инструмента в `chat/tools/` (schedule post, posts list, delete, settings, media list, upload from URL, generate image/video, clipping). Агент сам требует подтверждение перед публикацией (инструкция `:96`).
- UI: страница `/agents` (`(site)/agents/page.tsx`, пункт меню "Agent" `top.menu.tsx:46-61`) через CopilotKit; бэкенд `copilot.controller.ts:42-115` (`/copilot/chat`, `/copilot/agent`, адаптер `OpenAIAdapter` с `gpt-4.1` `:62-63`, `:108-109`). Без `OPENAI_API_KEY` чат не работает (`:54`, `:81`).
- Отдельный LangGraph-агент генерации постов (`libraries/nestjs-libraries/src/agent/agent.graph.service.ts:25-33`: `gpt-4.1`, `chatgpt-image-latest`).
- **MCP-сервер есть** (`chat/start.mcp.ts`, `MCPServer` из `@mastra/mcp` `:150`): пути `/mcp`, `/mcp/:id`, `/sse/:id`, OAuth-варианты `/mcp-oauth-claude`, `/mcp-oauth-chatgpt`, `/mcp-oauth-dynamic` (`:206-286`), relay `psh_`-токенов на self-hosted (`mcp.relay.service.ts`). То есть Claude/ChatGPT уже могут планировать посты в наш Postiz через MCP.
- **Telegram в Postiz = только канал публикации.** `telegram.provider.ts:19` создаёт один глобальный `TelegramBot(process.env.TELEGRAM_TOKEN)`, подключение через `getUpdates` и команду `/connect <word>` (`:85-130`). Нет входящего диалога, нет intake, нет webhook-режима. **Важно:** `getUpdates` несовместим с webhook на том же боте, поэтому токен @croscor_bot или любого диалогового бота туда класть нельзя; для Postiz нужен отдельный бот-паблишер.
- Ответ на вопрос: **говорить с Postiz через Telegram-бота сейчас нельзя.** Можно в веб-чате `/agents` и через MCP. Наш Telegram-бот (как у YourHelp) должен быть отдельным сервисом фабрики, который ходит в Postiz через Public API или MCP.
- Ограничения агента для нас: только OpenAI, модель в коде (нарушает наше правило "ID модели не хардкодить"); поддерживает ли `@ai-sdk/openai` переменную `OPENAI_BASE_URL` для подмены на совместимый шлюз, **не проверено** (node_modules не ставил). Агент не знает шабат, апрув и факты из `approved-business-facts.json`: дать ему доступ людям = обход политики (см. вариант 2 выше).

---

## (d) Multi-org, customers, роли, white-label

- Organization → много Integration/Post/Media; `UserOrganization` с `role` USER/ADMIN/SUPERADMIN (`schema.prisma:142-156`, enum `:1802-1806`), пользователь в нескольких org. `User.isSuperAdmin` (`:89`) = админ инстанса (страницы `/admin/stats`, `/admin/errors`).
- `Customer` (`:355-366`) = просто группировка каналов внутри org ("groups (customers)" в инструкциях агента), не граница тенанта.
- Права: CASL `PermissionsService` (`apps/backend/src/services/auth/permissions/permissions.service.ts`), секции `Sections` (`permission.exception.class.ts:3-15`) про лимиты тарифа, не про роли в workflow. **Без `STRIPE_PUBLISHABLE_KEY` разрешается всё запрошенное до проверки ADMIN** (`permissions.service.ts:49-61`) — риск из postiz-backend.md §4 в v2.25.3 **остаётся**.
- Ролей "автор", "одобряющий", "только загрузка" нет; issue #1758 отклонён.
- White-label: нет. Логотип `/postiz.svg` захардкожен (`(preview)/p/[id]/page.tsx:63`), заголовки "Postiz"/"Gitroom" по `isGeneralServerSide()` (`admin/errors/page.tsx:7`). Есть `DISABLE_REGISTRATION` (`.env.example:43`) и logo для OIDC-кнопки (`:182`). Ребрендинг = правка в форке (картинки, title, тексты i18n 15 локалей) с конфликтами в `translation.json` (самый горячий путь: 725 изменений файлов с мая).
- Billing: Stripe-тарифы встроены (`billing.controller.ts`, `stripe.controller.ts`), включаются `STRIPE_PUBLISHABLE_KEY`. Для коммерции теоретически можно продавать тарифы самим Postiz-биллингом, но планы/лимиты зашиты под их продукт (**не изучал глубже**).

---

## (e) Фронтенд: сложность новых админ-страниц

- Стек: Next.js 16.4.2, React 19.2.4, Tailwind 3.4.17, SWR, Mantine 5 (`package.json:62-65`, `:193`, `:204`, `:235-237`). 52k строк TS/TSX во `apps/frontend`, 30 каталогов компонентов.
- Роутинг App Router: `apps/frontend/src/app/(app)/(site)/<name>/page.tsx`, страница = тонкая обёртка над компонентом (пример `admin/errors/page.tsx:1-22`). Меню одним массивом с `role`, `hide`, `requireBilling` (`components/layout/top.menu.tsx:10-216`). Upstream-правила кода в `CLAUDE.md` репо: свои компоненты без npm-UI, SWR-хук на каждый запрос через `useFetch`, бэкенд строго DTO → Controller → Service → Repository.
- **Плагинной системы для UI нет.** "Plugs" (`@Plug` декоратор, 7 штук в providers) = автодействия после публикации (авторепост/автокомментарий по порогу лайков), не расширения интерфейса. "Third-party" = интеграции генерации (HeyGen и т.п.). "Sets" = шаблоны поста. "Webhooks" = после публикации.
- Оценка добавления страниц inbox / медиатека / очередь апрува / редактор политики тенанта:
  - Фронт: новый каталог `(site)/factory/*` + `components/factory/*` + 1 строка в `top.menu.tsx` (5 коммитов в файле с мая, конфликт редкий и тривиальный). Порядка 1.5-3k строк на 4 страницы (оценка, не замер).
  - Бэк: новый Nest-модуль `apps/backend/src/api/routes/factory.controller.ts`, который проксирует в API фабрики (авторизация и org берутся из сессии Postiz через `@GetOrgFromRequest`). Регистрация модуля = 1-2 строки в `api.module.ts`.
  - **Данные фабрики не класть в `schema.prisma`**: Postiz применяет схему через `prisma db push` при старте (`package.json` скрипты `pm2-run`, `prisma-db-push`), миграций нет, файл меняется часто (18 коммитов с мая). Свои таблицы держать в БД фабрики.
- Итог: "админка внутри Postiz" реальна как **тонкий UI-слой в форке поверх API фабрики**. Логика (intake, апрув по хешу, шабат, факты, журнал) остаётся в content-factory; форк содержит только страницы и прокси. Это минимизирует rebase-боль и держит AGPL-периметр узким.

---

## (f) Сборка, релизы, поддержка форка

- Монорепо pnpm 10.6.1, Node 22.23.4 (`package.json`), приложения `frontend`, `backend`, `orchestrator` (Temporal worker), `extension`, `commands` (CLI), `sdk` (`@postiz/node` 1.0.8). Код: ~129k строк TS/TSX без переводов (frontend 52k, nestjs-libraries 56k, orchestrator 8.6k, backend 7.2k), 1035 файлов в git.
- Образ: `Dockerfile.dev` — один контейнер, внутри nginx + pm2 с тремя приложениями, `pnpm install && pnpm run build` (4 GB heap). CI `.github/workflows/build-containers.yml` по git-тегу собирает `ghcr.io/gitroomhq/postiz-app:<ver>-amd64/-arm64` и манифест. Форк собирается тем же Dockerfile в свой registry; при старте `prisma db push`.
- Темп: коммитов в месяц 2026-05: 86, 06: 69, 07: 85, 08: 135, **09: 316, 10: 300**. Октябрь +16.7k/-10.8k строк. Diff v2.24.0 → v2.25.3 (1 месяц): 315 файлов, +19.3k/-9.8k. Релизы примерно раз в 2-4 недели (v2.24.0 09-22, v2.25.0 10-02, v2.25.1 10-09, v2.25.2/3 10-24). Основные авторы с августа: Gilad Resisi 459, Nevo David 212, Enno Gelhaus 56.
- Горячие точки конфликтов (коммитов с 2026-05-05): `posts.service.ts` 45, `new-launch/*` (редактор поста) 53, `post.activity.ts` 23, `schema.prisma` 18, workflows 13, `facebook.provider.ts` 29, `instagram.provider.ts` 34, переводы ~48 на локаль.
- Стратегия форка: ветка `wwg/main` = upstream-тег + стопка из 3-5 маленьких коммитов (новые каталоги + 1-строчные регистрации + guard в `postSocialInternal`). Rebase на каждый тег, CI-скрипт проверяет, что патч применился и `pnpm build` прошёл. Правки в горячих файлах (posts.service, new-launch, providers) **не делать**; нужное поведение providers (FB-карусель, GBP-отзывы) делать адаптерами фабрики, а не патчем provider. Ожидаемая цена: 0.5-2 ч на rebase раз в 2-4 недели (оценка).
- Альтернатива "upstream-first": guard-hook и pre-publish webhook предложить PR'ом в upstream. Понадобится CLA (`ICLA.md`, исключительная лицензия на вклад в пользу Gitroom, `:45-49`). Шанс принятия **не оценён**.

---

## (g) AGPL-3.0 и коммерческий SaaS на форке

Не юридическая консультация; по тексту лицензии.
- Лицензия AGPL-3.0 (`LICENSE`, `package.json "license"`, GitHub API spdx `AGPL-3.0`). README: "We do not gate features" (`README.md:150`), отдельной коммерческой лицензии/EE-каталога в репо нет.
- §13 (`LICENSE:540-551`): если мы **модифицируем** Postiz и даём пользователям работать с ним по сети, обязаны **предложить всем таким пользователям исходник нашей версии** бесплатно (ссылка в UI на публичный репо форка). Продавать доступ можно, закрыть код форка нельзя.
- Немодифицированный Postiz как сервис: §13 не срабатывает (он про modified versions), но AGPL всё равно требует сохранять уведомления.
- Отдельный сервис фабрики (Python content-factory, Telegram-бот, policy-сервис), который общается с Postiz по HTTP API/MCP, — по общепринятому толкованию отдельная программа, а не производная работа: её код можно держать закрытым. Если же логику фабрики встроить в Nest-модули Postiz, она станет частью модифицированной версии и уйдёт под AGPL. Это ещё один довод держать в форке только тонкий UI/прокси, а логику — в фабрике.
- Бренд: "Postiz" — название продукта Gitroom. Для продажи клиентам переименовать UI (white-label в форке) и не называть продукт Postiz. Регистрацию товарного знака **не проверял**.
- Сторонние лицензии зависимостей (CopilotKit, Mastra, Polotno — `NEXT_PUBLIC_POLOTNO` в `.env.example:155`, Polotno коммерческий SDK) **не проверены**; Polotno для коммерческого SaaS, вероятно, требует своей лицензии.

---

## Итог для архитектуры

1. Postiz = публикатор + календарь + preview с комментариями + MCP. Апрува, шабата, intake-бота, медиатеки исходников, ролей "одобряющий" в нём нет и не будет (#1758 not_planned).
2. "Работать через Postiz" и "админка в Postiz" реализуемы так: content-factory остаётся мозгом (план, апрув по хешу, шабат, факты, журнал, Telegram-бот как YourHelp); форк Postiz получает страницы `/factory/*` + прокси-контроллер + guard в `postSocialInternal`. Ни одной правки в горячих файлах.
3. WWG: IG карусели/reels/stories полностью; FB = мультифото или одно видео (листаемой карусели нет); GBP = 1 фото + CTA/offer/event, отзывы не поддержаны.

## Открытые вопросы
- Нужна ли листаемая FB-карусель (child_attachments) или достаточно мультифото-поста? Если нужна — прямой Meta-адаптер фабрики.
- Отдельный бот-паблишер для `TELEGRAM_TOKEN` Postiz (не @croscor_bot).
- Встроенный агент `/agents` выключать (нет `OPENAI_API_KEY`) или заменять своим — иначе он обходит апрув и шабат.
- Google Business Profile API доступ для WWG-проекта Google Cloud: есть ли одобрение квоты? Не проверено.
- Видео в GBP localPosts, `OPENAI_BASE_URL` в ai-sdk, превью DRAFT на живом инстансе — не проверены.
- Лицензия Polotno при коммерческой продаже.
