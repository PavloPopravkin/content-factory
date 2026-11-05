# Дизайн "глубокий форк": Postiz как сам продукт

Дата: 2026-11-05. Угол: всё живёт внутри форка Postiz (NestJS backend + Temporal orchestrator + Next.js frontend). Бот приёма, медиатека, куратор, очередь апрува, политика и шабат, GBP становятся модулями форка. Патчи держим upstream-friendly, ребейзим на релизы.
Источники: скаут-отчёты этой папки (`postiz-code.md`, `postiz-live.md`, `yourhelp-system.md`, `wwg-tenant.md`, `github-analogs.md`, `cf-core-fit.md`) и исходники v2.25.3 в `/tmp/claude-1003/postiz-src/postiz-app` (тег проверен `git describe`). Живые системы не трогал.
Метки: [проверено] = видел файл сам в этой сессии; [из отчёта] = взято у скаута; [не проверено] = вывод.

---

## 0. Вывод в пяти строках

1. Глубокий форк технически реализуем. В Postiz есть все нужные швы: activity-guard (`post.activity.ts:331`), DRAFT без workflow, MCP, агент с инструментом `draft|schedule|now`, меню одним массивом.
2. Цена высокая. Это переписывание проверенного Python-ядра (185 тестов, `cf-core-fit.md`) на TypeScript и вечный ребейз на upstream, который за один минорный релиз меняет `posts.service.ts` на 524 строки (`git diff --stat v2.24.0 v2.25.3`) [проверено].
3. Весь код фабрики внутри форка попадает под AGPL §13. Закрытого коммерческого ядра в этой схеме нет. Продаётся хостинг, настройка и поддержка, а не код.
4. Сегодняшнюю карусель WWG форк не публикует. Её уже ведёт `server-root/scripts/autopost` (слот `WWG-first-bathroom`, 05.11 11:00 Chicago) [из отчёта wwg-tenant.md:9]. Любая ручная публикация даст дубль.
5. Мой честный вердикт по углу: брать его только частично. Политика, апрув, админка и бот в форке оправданы. Куратор (headless Claude) и медиа-конвейер (ffmpeg) лучше держать воркерами рядом, вызываемыми из Temporal (см. §12).

---

## 1. Что противоречит этому углу и что нужно решить до кода

| Запись | Что говорит | Что делать |
|---|---|---|
| `server-root/DECISIONS.md:18-22` (2026-11-04) | Postiz отвергнут для клиентов: 20+ advisories, токены всех клиентов в одной веб-системе. Движок `scripts/autopost` | Новая запись в server-root/DECISIONS: "Postiz-форк = платформа, autopost = мост до cutover". Довод 04.11 про токены закрывается изоляцией из §9, а не исчезает |
| `content-factory/MANIFEST.md:12` | План владеет только фабрика, Postiz исполняет "сейчас" | Сохраняется: фабрика теперь внутри форка, но Post в Postiz остаётся DRAFT до допуска (§5) |
| `content-factory/MANIFEST.md` Non-goals "SPA-админка не нужна, хватит htmx" | | Перевернуть: админка = страницы `(site)/factory/*` форка |
| `content-factory/ARCHITECTURE.md:83` "Postiz не модифицируем" [из cf-core-fit.md] | | Отменить, зафиксировать список точек патча (§11) |
| `yourhelp/MANIFEST.md:77`, `yourhelp/DECISIONS.md:433` | Postiz в non-goals фонда | Не менять до фазы P5. Фонд работает на `slots.py`, пока форк не пройдёт shadow |

Без явного слова Pavel'я по первой строке код не начинать. Три движка параллельно (yourhelp, autopost, форк) = шабат и дубли чинятся в трёх местах (`yourhelp-system.md:151`).

---

## 2. Компоненты

```
                    Telegram (Женя, Иванка, волонтёры)
                               │ webhook
┌──────────────────────────────▼─────────────────────────────────────────┐
│ ФОРК POSTIZ (один docker-образ, наш registry)                          │
│                                                                        │
│ apps/backend (NestJS)                                                  │
│  ├─ upstream: auth, orgs, integrations, posts, media, public API, MCP  │
│  └─ libraries/factory  ← НОВОЕ                                          │
│      ├─ tenant-profile   (вид тенанта, tz, политика, факты)            │
│      ├─ policy           (шабат NOAA, лимиты, окна, admit())           │
│      ├─ approval         (хеш контента, карточки, журнал решений)      │
│      ├─ assets           (медиатека исходников, sha256, согласия)      │
│      ├─ intake-bot       (grammY, мульти-тенант роутинг)               │
│      ├─ planner          (слоты, promote DRAFT→QUEUE)                  │
│      ├─ delivery-journal (fence tenant×slot×channel, unknown)          │
│      └─ factory.controller (REST /factory/*, только для своих ролей)   │
│                                                                        │
│ apps/orchestrator (Temporal)                                           │
│  ├─ upstream post workflows (не трогаем версии)                        │
│  ├─ post.activity.ts: 1 вызов policy.guard() в postSocialInternal       │
│  └─ factory task queue ← НОВОЕ: promoteWorkflow, curateWorkflow,        │
│      mediaWorkflow, digestWorkflow, shabbatSweepWorkflow               │
│                                                                        │
│ apps/frontend (Next 16)                                                │
│  └─ (site)/factory/{inbox,library,plan,approvals,tenants,policy,audit} │
│     + 1 строка в top.menu.tsx                                          │
└──────────────┬───────────────────────────────┬─────────────────────────┘
               │ Temporal activity (HTTP)      │ Postgres
     ┌─────────▼──────────┐          ┌─────────▼────────────────────┐
     │ curator-runner     │          │ public.*  (Prisma Postiz)    │
     │ (контейнер, без    │          │ factory.* (наша схема,       │
     │ ключей соцсетей)   │          │  свои миграции)              │
     │ headless Claude /  │          └──────────────────────────────┘
     │ LLM-пул            │
     │ media-runner       │
     │ (ffmpeg, Pillow)   │
     └────────────────────┘
```

Почему curator и media вынесены в runner, хотя угол "всё в форке". Headless Claude по подписке и ffmpeg не живут в NestJS-процессе нормально: CLI, долгие задачи, память. Логика (что курировать, какие правила, какой JSON-контракт) живёт в форке, runner только исполняет задачу и возвращает JSON. Это сохраняет инвариант MANIFEST.md:13 "AI-куратор без ключей, в песочнице".

---

## 3. Модель данных

Тенант = `Organization` Postiz. Пользователи и каналы остаются в upstream-таблицах. Всё своё лежит в Postgres-схеме `factory` со своим Prisma-клиентом (`libraries/factory/prisma/factory.prisma`, `datasource url = ...?schema=factory`).
Почему не в общем `schema.prisma`. Postiz при каждом старте делает `prisma db push` по своей схеме (`package.json:18,34`) [проверено]. Свои модели в upstream-файле = конфликт ребейза в самом горячем файле. Отдельная схема Postgres не видна push'у upstream [не проверено: нужно подтвердить на стенде, что `db push` без `multiSchema` не трогает `factory.*`].

Ключевые таблицы (все с `org_id`, составные FK `(org_id, id)` как в SQLite-ядре, `MANIFEST.md` правило про составные ключи):

| Таблица | Поля | Зачем |
|---|---|---|
| `tenant_profile` | org_id PK, kind `ministry\|charity\|commerce`, locale_ui, locale_content, tz, require_approval bool, shabbat_profile_id NOT NULL, daily_limits jsonb, donation_auto bool=false, facts_source | Флаги тенанта. Фонд: require_approval=false (решение Pavel'я 21.10/25.10, `yourhelp-system.md`). WWG: true |
| `shabbat_profile` | id, locations[] (lat, lon, tz), pre_minutes ≥30, post_minutes ≥70, mode `union` | Шабат как обязательная ссылка, не опция. Валидация на старте: нет профиля = backend не стартует (fail-fast) |
| `member` | org_id, tg_user_id, postiz_user_id?, role `contributor\|approver\|editor\|owner`, lang | Свои роли, не трогаем enum `Role` USER/ADMIN/SUPERADMIN (`schema.prisma:1802-1806` [из отчёта]) |
| `bot_binding` | org_id, bot_id, chat_id, kind `dm\|group\|channel`, purpose `intake\|approval\|digest` | Мульти-тенант роутинг бота |
| `asset` | org_id, sha256 UNIQUE(org_id,sha256), kind, source (`tg\|icloud\|import\|social`), taken_at, w, h, duration, codec, consent `ok\|faces_unknown\|no_kids\|blocked`, tags[], storage_key, origin_ref | Медиатека исходников (607 iCloud-файлов WWG) |
| `asset_derivative` | asset_id, preset (`ig_4x5`, `reel_9x16_h264`, `gbp_1x1`), sha256, storage_key, immutable | Апрув точных байтов (правило MANIFEST про неизменяемые derivatives) |
| `intake_item` | org_id, member_id, tg_message_id, asset_id?, text, voice_transcript, received_at, batch_id | Сырьё как пришло |
| `slot` | org_id, id, planned_at, channels[], format `carousel\|reel\|story\|single\|gbp_update\|gbp_offer`, caption per channel, derivative_ids[], fact_ids[], status `draft\|awaiting_approval\|approved\|promoted\|published\|missed\|failed\|unknown`, postiz_group | План. Postiz Post создаётся как DRAFT с этим `group` |
| `approval` | slot_id, content_hash, decision `approve\|reject\|edit_requested`, actor member_id, via `telegram\|web`, nonce, decided_at | Закрывает дыру `storage.py:186` "approve() не пишет кто" (cf-core-fit.md) |
| `delivery` | UNIQUE(org_id, slot_id, channel), state `pending\|sent\|unknown\|failed\|deferred`, external_id, next_attempt_at | Fence против дублей. Исправляет дубль-риск `slots.py:226-230` |
| `approved_fact` | org_id, fact_id, text, allowed bool, source_ref | WWG: импорт `approved-business-facts.json`. Куратор цитирует только fact_id |
| `policy_event` | org_id, slot_id, check, verdict, reason, at | Аудит каждого допуска и отказа |

---

## 4. Telegram-бот: разговор и мульти-тенант роутинг

### 4.1 Какой бот

- Встроенный `telegram.provider.ts` Postiz = только канал публикации с одним `TELEGRAM_TOKEN` и `getUpdates` (`telegram.provider.ts:19,85-130` [из отчёта]). Для разговора не годится.
- Модуль `intake-bot` форка работает на webhook, токены ботов хранит в `bot` (шифрованно, ключ из env). Поддерживает N ботов: платформенный и белые метки коммерческих клиентов.
- @croscor_bot в P1-P4 НЕ переносится. Это бот steward (guard.py, учёт дел, сводки), webhook уже занят (`postiz-code.md`, открытый вопрос 2). Steward вызывает API форка вместо записи в `~/yourhelp-intake/inbox`: `team-tool social send` → `POST /factory/intake` с service-токеном тенанта. Люди не замечают смены.
- Свой бот форка появляется для тенантов вне команды (коммерция, другие церкви). Тот же код intake-модуля, просто другой транспорт.

### 4.2 Роутинг

1. `tg_user_id` → `member[]`. Одна организация → сразу она.
2. Несколько → последняя использованная, в каждом ответе строка "организация: WWG WOW", кнопка "сменить".
3. Групповой чат → `bot_binding` чата фиксирует организацию, личные членства не нужны.
4. Незнакомец → ответ "напишите владельцу организации", ничего не сохраняется (как guard.py у steward).

### 4.3 Сценарии (паритет с тем, чем реально пользуется Иванка)

Иванка за историю: ~18 `send`, ~15 `plan`, 0 `cancel`, 0 `text` (`yourhelp-system.md`). Значит MVP = три вещи.

- Принято: на альбом/файлы ответ "прийнято N файлів" одним сообщением после паузы 30 с, а не на каждый файл.
- Сводка: после сборки "что выйдет, что не взяли и почему" на языке участника.
- План: "Попереду N" со списком слотов, дата в tz тенанта.

### 4.4 Апрув для Жени в чате

Карточка (паттерн `telegram-ops-kit`, MIT, `github-analogs.md` п.4):

```
[sendMediaGroup: 7 фото карусели в реальном порядке]
WWG WOW · IG + FB + Google · пт 06.11 10:00 Chicago
Текст IG: "...."
Факты: F03 (insured), F07 (since 2019)
[✅ Одобрить] [✏️ Текст] [🖼 Фото] [🕒 Время] [❌ Нет]
```

- В `callback_data` лежит `nonce`, не id слота. Nonce одноразовый, срок 72 ч, повторное нажатие = "уже решено".
- Решение пишется в `approval` с `content_hash`. Хеш = sha256 канонического JSON: тексты по каналам, sha256 каждого derivative по порядку, id интеграций, settings провайдеров, planned_at с точностью до минуты.
- Любая правка после апрува (в Postiz-редакторе или ботом) меняет хеш → старый апрув не действует → новая карточка.
- "Текст" открывает диалог: Женя пишет что поменять словами, куратор переписывает, приходит новая карточка.
- Карточка приходит не в шабат (digestWorkflow тоже уважает окно) и не ночью по tz одобряющего.
- Веб-дубль: страница `/factory/approvals` и публичное превью Postiz `/p/[id]` с комментариями (`public.controller.ts:54-90` [из отчёта]) как "посмотреть на телефоне, как будет".

---

## 5. Где стоят политика, апрув и шабат

Три слоя, все fail-closed.

1. **Допуск при promote.** Слот живёт в Postiz как `DRAFT`, а DRAFT вообще не стартует workflow (`posts.service.ts:964` [из отчёта]). `promoteWorkflow` (наша очередь Temporal) в момент слота вызывает `policy.admit(slot)`: шабат, апрув по хешу, лимиты дня, интервалы, donation-guard. Да → перевод в QUEUE с `publishDate = now + 60s`. Нет → `deferred` с причиной, следующий допустимый слот или `missed` после 3 ч (правило YourHelp).
2. **Guard в activity.** В начале `postSocialInternal` (`apps/orchestrator/src/activities/post.activity.ts:331`) [проверено строку] один вызов `factoryPolicy.guard(integration, posts)`. Проверяет то же самое заново по текущим строкам Post (хеш пересчитывается из БД). При запрете бросает `BadBody`, как upstream делает для Disconnect (`post.activity.ts:274-278`) [проверено]. Это ловит обходы: ручное "Add to calendar" в UI, Public API, MCP, агент.
3. **Агент и MCP.** Инструмент `schedulePostTool` уже умеет `draft` (`libraries/nestjs-libraries/src/chat/tools/integration.schedule.post.ts:115-116`) [проверено]. Патч: для организаций с `tenant_profile` тип принудительно `draft`. Тем самым ответ на открытый вопрос analogs №2: да, умеет.

Почему не новая версия workflow. Версии заморожены (`post.workflow.v1.1.2.ts`), upstream добавляет свои. Наша версия = конфликт на каждом релизе. Activity меняется без версий.

Шабат.
- Порт `solar.py:7-26` (NOAA) и `blackout_violations` (`planner.py:17-41`) на TS 1:1. Тестовые векторы выгружаем из Python-набора в JSON и гоняем в обеих реализациях до cutover.
- Окно = объединение по всем `locations` профиля: пятница закат −30 мин ... суббота закат +40 цеит +30 запас (≥70 мин). Неизвестный закат = блок.
- Профиль платформы по умолчанию (не отключаемый тенантом): Чикаго ∪ Киев ∪ Испания (когда Pavel назовёт город). Пока города нет, Испанию покрывает объединение Киев ∪ Чикаго: Киев начинает окно раньше любой точки Испании, Чикаго заканчивает позже (Испания лежит между ними по долготе, разница по широте даёт минуты) [вывод, расчётом не проверено].
- Последствие: рилс WWG `WWG-1106-sink` пт 06.11 10:00 Chicago с запасом 28 мин (`wwg-tenant.md:11`) при объединении с Киевом попадает в окно. Это касается движка autopost сегодня, не форка, решать Pavel'ю.
- Сводки, карточки апрува, бот-ответы в окне не отправляются. Бот принимает файлы молча и отвечает после исхода. Это предложение, подтвердить у Pavel'я: возможно, он хочет, чтобы бот вообще молчал.

---

## 6. Куратор (AI)

- `curateWorkflow` (Temporal) собирает пакет: новые `intake_item`, профиль тенанта, правила контента тенанта (файл-данные, не код), разрешённые факты, последние 30 постов, свободные слоты.
- Запускает curator-runner. Контракт строго JSON (паттерн n8n-ai-newsroom, `github-analogs.md` п.3): `slots[]` с format, channels, caption per channel, asset_ids, fact_ids, `rejected[]` с причиной.
- Валидатор в форке (детерминированно, не промпт): asset принадлежит org, consent не `blocked`, fact_id есть и allowed, лимиты текста канала (GBP 1500, `gmb.provider.ts:55-57`), IG ≤10 файлов, нет запрещённых формулировок тенанта (WWG: "200+ reviews"). Сейчас у YourHelp эти правила проверяет только промпт (`yourhelp-system.md` "Что зашито под фонд").
- Модель. Порядок по глобальному правилу: пул Antigravity → Groq/Cloudflare. Для фонда сохраняем headless Claude по подписке, как сейчас (`TASK-INTAKE.md`). Azure никогда. Имя модели из каталога + проба (правило "ID не хардкодить").
- Встроенный Mastra-агент с `openai('gpt-5.2')` (`load.tools.service.ts:116` [из отчёта]): в форке патч на модель из env через OpenAI-совместимый base URL. Работает ли `OPENAI_BASE_URL` в ai-sdk этой версии, [не проверено]. До патча агент выключен (нет ключа = не работает, на живом инстансе `OPENAI_API_KEY` не задан [из отчёта cf-core-fit]).
- Служение: правило из ConnectClips/sermon-shorts, музыку хвалы не публиковать (CCLI не покрывает соцсети, `github-analogs.md` п.5). Вырезка клипов проповеди требует GPU, есть ли на S2 [не проверено].

---

## 7. Публикация по каналам

| Канал | Что даёт Postiz v2.25.3 | Патч в форке | Upstream PR? |
|---|---|---|---|
| IG | Карусель до 10, Reels 1 mp4, Stories, collaborators (`instagram.provider.ts:60,986` [из отчёта]) | Нет | — |
| FB | mp4 первым = одно видео; иначе мультифото `attached_media`; Stories (`facebook.provider.ts:835,866-911`) | (a) Reels через `/{page}/video_reels` (порт `meta.py:73,109`); (b) настройка `fb_layout: grid\|album` (album через `/{page}/albums`) | Да, оба полезны всем |
| FB листаемая карусель `child_attachments` | Нет | Только если Pavel скажет "нужна" (открытый вопрос). Это link-карусель со ссылками, для фото-кейсов клининга мультифото-сетка честно ближе [вывод] | Возможно |
| GBP | v4 localPosts STANDARD/EVENT/OFFER, CTA, только первый файл, 1500 символов (`gmb.provider.ts:439-447,477`) | (a) guard: GBP-слот = ровно 1 фото, CTA Book; (b) отдельный модуль `gbp-reviews` (чтение отзывов + черновик ответа на апрув), отзывов в провайдере нет | (a) нет, (b) да |
| Telegram-канал (табор YourHelp) | Есть провайдер, но один глобальный бот через getUpdates | Отдельный бот-паблишер для `TELEGRAM_TOKEN` (не @croscor_bot, `postiz-code.md` вопрос 2) | — |
| YouTube Shorts / TikTok | Есть провайдеры (`research/postiz-backend.md` [из отчёта]) | Нет | — |

GBP-риск сейчас: публикатор ADS стоит с 03.11 на "unknown GBP POST outcome" 93 раза, тот же OAuth Pavel'я (`wwg-tenant.md:10`). В форке GBP подключается через Google-клиент с доступом к Business Profile API. Есть ли у проекта одобренный доступ, [не проверено]. Postiz сейчас берёт для gmb `YOUTUBE_CLIENT_ID` [из отчёта wwg-tenant.md].

Журнал доставки. Перед вызовом провайдера guard пишет `delivery(pending)`. Upstream после успеха пишет `releaseURL` в Post. Наш listener (Postiz Webhooks, таблица `Webhooks`, `schema.prisma:45,650` [проверено наличие]) переводит `delivery` в `sent` с external_id. Нет ответа = `unknown`, без повтора, разбор оператором (правило MANIFEST).

---

## 8. Админка внутри Postiz

Страницы `apps/frontend/src/app/(app)/(site)/factory/*`, тонкие обёртки, SWR через `useFetch`, свои компоненты без npm-UI (upstream `CLAUDE.md` репо [из отчёта]). Пункт меню "Factory" в `top.menu.tsx` видим при наличии `tenant_profile`.

- `inbox`: сырьё по участникам, статус "взято/отклонено/почему".
- `library`: медиатека с фильтрами (вертикальные видео, год, consent, использовано/нет), превью derivative.
- `plan`: неделя по tz тенанта, шабат-окна закрашены и некликабельны, слоты со статусом.
- `approvals`: очередь, diff хешей ("что изменилось после апрува").
- `tenants`, `policy` (только owner платформы): профили, шабат-профили, лимиты.
- `audit`: `policy_event` + `delivery`.

Мост для живого инстанса без пересборки: `postiz-fanout.service` (:8912) уже встраивает JS в HTML Postiz (`postiz-live.md` п.6). Его код root-only и я его не читал. В схеме глубокого форка он не нужен, страницы собираются в образ.

---

## 9. Безопасность и изоляция тенантов

- **Брешь прав.** Без `STRIPE_PUBLISHABLE_KEY` `PermissionsService` выдаёт все запрошенные способности (`apps/backend/src/services/auth/permissions/permissions.service.ts:49-61`) [проверено код]. Это ветка лимитов подписки; проверяются ли роли ADMIN отдельно до неё, [не проверено]. Действие: deny-тест в CI (USER не может удалить канал чужой организации и не может админ-действия своей) до выдачи любых логинов.
- **Наши эндпоинты** `/factory/*` проверяют `member.role` и `org_id` в каждом запросе репозитория (scope-guard в одном месте, не в контроллерах).
- **Токены соцсетей** лежат в `Integration.token` (`schema.prisma:377-380`) [проверено поле]. Шифруются ли на уровне приложения, [не проверено]. Если нет: патч шифрования at-rest ключом из env (upstream PR кандидат).
- **Коммерческие клиенты** = отдельный деплой того же образа (своя БД, свой домен), не организация на общем инстансе. Это прямо закрывает довод 04.11 "токены всех клиентов в одной системе" для коммерции. Служение и фонды Pavel'я делят один инстанс.
- **Регистрация** выключена `DISABLE_REGISTRATION` (`.env.example:43` [из отчёта]).
- **Security-ребейз**: upstream advisory → наш релиз за 72 ч. 4 advisory 02.11 закрыты в v2.25.3 (`postiz-live.md` п.1). Скорость upstream (6 релизов за 4 месяца, теги проверены) это позволяет при узком патче.
- **Секреты в compose 0644, temporal с дефолтным паролем** (`postiz-live.md` п.8): в форке `.env` 600 через vault (`inv-protect`), compose без значений.
- **Бэкап**: регулярного нет (`postiz-live.md` п.7). pg_dump `public`+`factory` + temporal + uploads, cron, с проверкой восстановления, до P2.

---

## 10. Миграция и запуск

### 10.1 WWG, первый прогон

1. Сегодня и до P2 WWG ведёт `scripts/autopost`. Одобренная карусель уходит оттуда 05.11 11:00 Chicago. Руками не дублировать (`wwg-tenant.md:9`).
2. P2: организация "WWG WOW" в форке на стенде, каналы через OAuth (клики Pavel'я или Жени), импорт `approved-business-facts.json` в `approved_fact`, импорт ledger autopost (`~/autopost/wwg/*`) в `delivery` как `sent`, чтобы форк знал уже вышедшее.
3. Первый пост через форк = следующий неодобренный слот из 4 (06-10.11, `wwg-tenant.md`), апрув Жени кнопкой в @croscor_bot через API форка. Публикация на тестовую страницу FB/IG, затем на живые.
4. Cutover WWG: крон `engine.py wwg tick` выключается в тот же ход, когда форк берёт тенант (иначе два движка на одних каналах).

### 10.2 YourHelp и YourCamp, не ломая рабочее

1. P5a shadow 2 недели: steward кладёт сырьё И в inbox, И в API форка. Форк планирует в режиме `dry_run`, публикации нет. Ежедневный diff планов `slots.json` против `slot` (что взяли, какие даты, шабат). Критерий: ≥90% совпадения отобранного сырья, 0 слотов в окне шабата, 0 расхождений в donation-guard.
2. P5b канал за каналом: сначала Telegram-канал табора, потом IG, потом FB. `slots.py` снимает канал из своего набора (`push-slots.sh`) в том же ходе.
3. Перенос сохраняет: план отдельно от состояния, ledger с external_id, `missed` после 3 ч, частичный успех по каналам, отсутствие апрува для фонда, сводку на украинском.
4. Чинится попутно: дубль между публикацией и записью состояния (`slots.py:226-230`), `failed` без повтора (`slots.py:228`), летнее окно шабата 21:00 Киев раньше исхода (`autopost.py:289-296`), шум "очередь пуста".
5. Не переносится: падение ночного забора из лички в 01:00 (`Node.js v20.20.2` в run.log) разбирается отдельно, это вход, не платформа.

---

## 11. Форк: поверхность патча и ребейз

Новые каталоги (конфликтов нет): `libraries/factory/**`, `apps/orchestrator/src/factory/**`, `apps/frontend/src/app/(app)/(site)/factory/**`, `apps/frontend/src/components/factory/**`.

Точки касания upstream-файлов (держать ≤10, каждая ≤20 строк, помечены `// FACTORY-PATCH`):

| Файл | Что | Churn v2.24→v2.25.3 |
|---|---|---|
| `apps/orchestrator/src/activities/post.activity.ts` | вызов guard | 41 строка [проверено] |
| `apps/backend/src/app.module.ts` | import FactoryModule | [не измерено] |
| `apps/orchestrator/src/app.module.ts` | factory worker | [не измерено] |
| `apps/frontend/src/components/layout/top.menu.tsx` | пункт меню | 91 строка [проверено] |
| `libraries/nestjs-libraries/src/chat/tools/integration.schedule.post.ts` | force draft | [не измерено] |
| `libraries/nestjs-libraries/src/chat/load.tools.service.ts` | модель из env | [не измерено] |
| `.../social/facebook.provider.ts` | reels, album | [не измерено], горячий |
| `.../social/gmb.provider.ts` | 1 фото guard | [не измерено] |
| branding (logo, title) | white-label | `translation.json` самый горячий (725 изменений с мая [из отчёта]) |

Не трогаем: `posts.service.ts` (524 строки churn), `schema.prisma`, версии workflow.

Процесс: ветка `factory` поверх тега, ребейз на каждый релиз, CI собирает образ, гоняет наши тесты + deny-тест + smoke на стенде. Еженедельный пробный ребейз на upstream `main` ловит конфликты заранее. Провайдерные патчи сразу отправляем upstream PR, чтобы они ушли из форка.

---

## 12. Коммерция и AGPL

- AGPL §13: изменённый Postiz как сетевой сервис обязан отдать пользователям исходник (`postiz-code.md`). В этой схеме фабрика = часть форка, значит весь код фабрики публичен. Закрытым можно держать только данные: промпты тенанта, правила контента, бренд-киты. Являются ли промпты, загружаемые как данные, частью Corresponding Source, юридически [не проверено].
- Имя "Postiz" продавать нельзя (`postiz-code.md`). Своё имя продукта, свой логотип, "based on Postiz" в About.
- Polotno (редактор картинок в Postiz) имеет свою лицензию, для коммерции [не проверено].
- Что продаём: хостинг на выделенном деплое, настройка тенанта (бот, правила, шабат-профиль, факты), куратор, поддержка, приоритетный security-ребейз. Для церквей и фондов: бесплатно/по себестоимости, это прямо служение.
- Альтернатива для закрытого ядра (если Pavel захочет): мозг отдельным сервисом за HTTP, это угол другого дизайна, не этого.

---

## 13. Фазы, оценки, критерии

Оценки в днях работы инженера (Claude + исполнители), календарно ×1.5-2 из-за апрувов и OAuth-кликов людей.

| Фаза | Объём | Дни | Критерий готовности (primary signal) |
|---|---|---|---|
| P0 Решения и стенд | DECISIONS (server-root, content-factory), MANIFEST правки, публичный репо форка, CI образа, **отдельный стенд Postiz на S2** (свой compose, порт, БД), бэкап прода Postiz | 2-3 | Образ форка = upstream v2.25.3 бит-в-бит по поведению, стенд поднят, бэкап восстановлен на стенде |
| P1 Ядро политики | `libraries/factory`, схема `factory`, порт solar/planner/admit/hash/journal на TS, guard в activity, promoteWorkflow | 5-7 | Векторы Python-набора проходят в TS 100%; на стенде с подменой часов пост в окне шабата не уходит ни одним из путей (UI, API, MCP, агент) |
| P2 Апрув + WWG | intake/approval API, карточки в @croscor_bot через steward, организация WWG, факты, импорт ledger autopost, GBP env | 6-8 | Женя одобряет кнопкой, пост выходит на тестовой странице, хеш-правка после апрува блокирует; затем 1 живой пост WWG; крон autopost WWG выключен |
| P3 Медиатека | assets, derivatives (media-runner), импорт 607 iCloud + ссылки на 62 IG / 44 FB, страница library | 5-7 | 607/607 импортировано, sha256 дедуп, reel-derivative проходит ffprobe-проверку (H.264, yuv420p, SAR 1:1) |
| P4 Куратор | curateWorkflow, runner, JSON-контракт, детерминированный валидатор, сводка | 6-10 | 2 недели WWG: 0 фактов вне `approved_fact`, ≥70% слотов Женя одобряет без правки |
| P5 YourHelp/YourCamp | shadow → поканальный cutover | 4-6 + 2 нед. shadow | Критерии §10.2; 0 пропущенных дней ленты фонда |
| P6 Коммерческая упаковка | white-label, свой бот на тенанта, выделенный деплой скриптом, deny-тесты, upstream PR провайдеров | 8-12 | Второй коммерческий тенант с нуля по README без личного окружения автора (критерий MANIFEST) |

Итого 36-53 инженерных дня, календарно 2.5-4 месяца. Шабат-пауза и OAuth-клики людей сюда не входят.

Делегирование: порт TS-ядра и валидаторов = Sonnet xhigh (инварианты, деньги/права), страницы админки и импорт медиатеки = Codex, архитектура, guard и финальная проверка = я.

---

## 14. Риски

1. **Переписывание проверенного.** Python-ядро и `slots.py` проверены жизнью (78 постов фонда). TS-порт может внести регресс в шабат. Митигация: общие тестовые векторы, shadow 2 недели.
2. **Upstream churn.** 300+ коммитов в месяц (`postiz-code.md`). Узкая поверхность патча + еженедельный пробный ребейз. Если поверхность разрастётся за 10 файлов, угол проиграл.
3. **Безопасность на нас.** Каждый advisory Postiz = наш релиз. История: 20+ advisories с марта (server-root DECISIONS 04.11).
4. **Temporal.** Ещё один stateful-компонент, наши workflow тоже требуют детерминизма и версий.
5. **AGPL** делает весь продукт открытым. Если Pavel хочет закрытое коммерческое ядро, угол не подходит.
6. **Одна БД для служения и фондов.** Компрометация Postiz = все каналы Pavel'я. Коммерция выделена, служение нет.
7. **Шабат.** Город в Испании неизвестен, правило "закат не угадывать". Объединение окон перекрывает это ценой большего простоя.
8. **Каналы на живом Postiz** имеют `tokenExpiration` 14-15.09 (`postiz-live.md` п.3), YourCamp/YourHelp/WWG/GBP/Telegram там нет. Переподключение руками людей.

---

## 15. Открытые вопросы

1. Pavel: отменяем запись server-root 04.11 и делаем форк платформой? (§1)
2. Pavel: шабат-профиль платформы = объединение Чикаго ∪ Киев ∪ город в Испании? Какой город?
3. Pavel: бот в шабат молчит полностью или принимает файлы молча?
4. Pavel: AGPL-открытый продукт устраивает для коммерции?
5. Pavel/Женя: нужна ли листаемая FB-карусель или хватает мультифото?
6. Pavel: какой Google Cloud-проект с доступом к Business Profile API?
7. Проверить на стенде: `prisma db push` не трогает схему `factory`; `OPENAI_BASE_URL` в ai-sdk; превью `/p/[id]` для DRAFT; шифрование `Integration.token`; порядок проверки ролей в `PermissionsService`.
