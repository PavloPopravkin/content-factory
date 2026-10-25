# Postiz как publishing backend контент-фабрики

Проверено 25.10.2026 через `curl` к GitHub API, raw.githubusercontent.com и официальным docs. Релизный код зафиксирован на `v2.25.3`, commit `a5affe62c74e39c1e7ac960d50d8418b807d532c`; исходная `v2.21.10` имеет commit `4cfe33d100db79d06702d859c2dd5ca0e03b721e`. Все ссылки на код ниже закреплены за этими commit. [Релиз][release], [сравнение][compare].
Статическая проверка исходников и документации. Публикации на реальных аккаунтах, апгрейд двух установок и замеры RAM не выполнялись. Наличие ветки кода ниже не означает успешный production smoke-test.

## 1. Версия, безопасность, апгрейд

**Последний опубликованный стабильный релиз `v2.25.3`, 24.10.2026 14:16:43 UTC. Оставаться на `2.21.10` нельзя.** В частности, её затрагивают чтение файлов при local storage, предсказуемые credentials и повторная проблема подписывания произвольных JWT; последний дефект закрыт только в `2.25.3`. [Релиз][release], [GHSA traversal][traversal], [GHSA RNG][rng], [PSA JWT][jwt-psa].

Срез опубликованных GitHub advisories, затрагивающих семейство `2.21.x`; статус именно `2.21.10` выделен отдельно. Диапазоны GHSA местами ошибочны, поэтому границы ниже сверены с текстами и кодом. [Security API][security-api].

| Advisory / проблема | Исправление / отношение к `2.21.10` |
| --- | --- |
| [GHSA-vj2p-7pgw-g2wf](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-vj2p-7pgw-g2wf), SSRF Next.js | `2.21.1`; исправлено к `2.21.10`. |
| [GHSA-89v5-38xr-9m4j](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-89v5-38xr-9m4j), SSRF webhooks/RSS/URL loader | `2.21.2`; исправлено к `2.21.10`. |
| [GHSA-89vp-m2qw-7v34](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-89vp-m2qw-7v34) и [GHSA-mv6h-v3jg-g539](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-mv6h-v3jg-g539), SSRF upload-from-url / public stream | `2.21.3`; исправлено к `2.21.10`. |
| [GHSA-wc9c-7cv8-m225](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-wc9c-7cv8-m225), webhook SSRF; [GHSA-34w8-5j2v-h6ww](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-34w8-5j2v-h6ww), redirect bypass | `2.21.4` / `2.21.5`; исправлено к `2.21.10`. |
| [GHSA-44wg-r34q-hvfx](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-44wg-r34q-hvfx), MIME spoofing / stored XSS | `2.21.6`; исправлено к `2.21.10`. |
| [GHSA-hhxq-3wg7-4rj8](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-hhxq-3wg7-4rj8), XSS публичного preview | `2.21.7`; исправлено к `2.21.10`. |
| [GHSA-j77w-h625-56q2](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-j77w-h625-56q2), Skool JWT takeover; [GHSA-j7rp-5mgj-qgg9](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-j7rp-5mgj-qgg9), Nowpayments; [GHSA-v4wr-4j8g-4hfj](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-v4wr-4j8g-4hfj), billing bypass | `2.21.8`; старые варианты исправлены, но это не закрывает новый [PSA JWT][jwt-psa]. |
| [GHSA-5m7p-wphr-xjp7](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-5m7p-wphr-xjp7), подделка lifetime-кодов | `2.21.10`; именно это исправлял исходный релиз, преимущественно для Stripe-установок. |
| [GHSA-4hgh-5rhf-4qpm][traversal], critical, чтение файлов через `/uploads` | **`2.21.10` уязвима при `STORAGE_PROVIDER=local`**; fixed `2.22.1`; возможны утечка env/JWT_SECRET и захват установки. |
| [GHSA-4hw5-43cf-g9wp][rng], critical, credentials через `Math.random()` | **`2.21.10` использует слабый генератор**; релиз `2.24.0` содержит исправление. GHSA ошибочно пишет `<2.4.0`, а текст указывает affected до `2.23.0`; старый код и новый `crypto.randomInt` подтверждены. [Старые ключи][old-org], [старый генератор][old-id], [новый генератор][secure-id], [release 2.24][r224]. |
| [GHSA-629m-99qx-356r](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-629m-99qx-356r), enterprise provisioning / lifetime | **В `2.21.10` есть vulnerable endpoint**; эффект billing существенен со Stripe. Исправление в `2.24.0`, поле GHSA `<2.4.0` противоречит references на `2.24.0`. [Старый controller][old-enterprise], [r2.24][r224]. |
| [GHSA-f7jj-p389-4w45](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-f7jj-p389-4w45), DNS rebinding / SSRF TOCTOU | GHSA не указывает fixed version. DNS-pinning dispatcher уже есть в `2.21.10`; в latest есть safe undici и axios. Нельзя по незаполненному GHSA объявить latest уязвимым либо доказать защиту всех call sites. [Старый dispatcher][old-ssrf], [latest][ssrf]. |
| [GHSA-jxg2-2cmf-h66m](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-jxg2-2cmf-h66m), bcrypt hash в JWT | GHSA пишет `>=2.21.16`, без fixed version; **в проверенных `2.21.10` и latest `jwt()` удаляет password**, latest middleware повторно читает роль из БД. Текст advisory не соответствует этим путям кода; runtime repro не делался. [Старый auth][old-auth], [новый auth][auth], [middleware][session-auth]. |

[GHSA-v975-9h5p-xhm4](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-v975-9h5p-xhm4) относится к CI upstream (`pull_request_target` / Dockerfile PR), а не к HTTP-эксплуатации установленной `2.21.10`. [GHSA-48c8-25jq-m55f](https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-48c8-25jq-m55f) исправлена ещё в `1.62.3`.
Дополнительно последние release notes ссылаются на maintainer advisories вне текущего списка GHSA: [CVE-2026-107761 / утечки API key и токенов](https://gadvisory.org/advisories/PSA-2026-4QX1WG), affected `>=0`, fixed `2.25.1`; [CVE-2026-115931 / произвольный вызов методов](https://gadvisory.org/advisories/PSA-2026-JNXM56), affected `>=2.23.0`, fixed `2.25.2`; [CVE-2026-115932 / local media traversal](https://gadvisory.org/advisories/PSA-2026-E9AHFV), affected `>=2.23.0`, fixed `2.25.3`; [CVE-2026-115933 / JWT cross-tenant takeover][jwt-psa], affected `>=2.15.0`, fixed `2.25.3`. Первое и последнее затрагивают `2.21.10`; два средних появились позже. [Релизы][releases].

Что включает upgrade `2.21.10 → 2.25.3`, без обещания безопасного rollback поверх изменённой БД:
1. Сделать backup Postiz DB, Temporal DB/visibility, uploads и конфигурации; проверить восстановление на копии. Сохранить volumes и `JWT_SECRET` при первом upgrade: общий auth helper использует его также для AES. При подозрении на компрометацию отдельно спланировать ротацию JWT_SECRET и зависящих encrypted данных. [Compose][compose], [auth helper][auth-helper].
2. **Temporal остаётся обязательным**, уже используется начиная с `2.12.0`; переход с `2.21.10` не является новой миграцией BullMQ → Temporal. Обновить приложение вместе с orchestrator, сохранив Temporal state: `2.23` ввёл workflow v1.0.6, `2.24` добавил v1.0.7-v1.1.2/heartbeats и media/clipping workflows; текущие исполнения остаются на своих версиях. [Requirements][requirements], [r2.23][r223], [r2.24][r224], [workflows][workflow].
3. Применить Prisma schema changes: `Clipping`/`ClippingClip`/`mastra_*`, затем `Comments`, `OAuthSelfHostedAuthorization`, индексы. Официальный Docker запускает `prisma-db-push`; отдельная source-установка должна выполнить `pnpm run prisma-db-push`. Не запускать `prisma-reset`. Новые Apple/TikTok Business/RunPod/Deepgram/RevenueCat/relay env опциональны для соответствующих функций. [r2.24][r224], [r2.25][r225], [startup scripts][package].
4. Учесть изменения поведения: Meta Graph `v20 → v25`; повторная публикация требует `republish:true`; schedule с прошлой датой, удалённые каналы и Slack video отвергаются; TikTok `UPLOAD` означает inbox, для автопубликации нужен `DIRECT_POST`. Протестировать существующие API payloads и OAuth reconnect; после исправления RNG заменить org API keys, OAuth secrets/authorizations, проверить social connections. [r2.24][r224], [r2.22.1][r222], [GHSA RNG][rng].

## 2. Public API и внешний AI-конвейер

В bundled Docker base URL `https://HOST/api/public/v1`; прямой Nest backend использует `/public/v1`, Cloud `https://api.postiz.com/public/v1`. Заголовок **`Authorization: KEY` без `Bearer`**. Ключ хранится у Organization, общий для workspace; middleware назначает ему org `SUPERADMIN`. OAuth-токены `pos_...` тоже принимаются в этом заголовке и в этом middleware получают широкие org-права. API key нельзя выдавать волонтёру как ограниченный доступ. [Controller][api], [public auth][public-auth], [schema][schema], [nginx][nginx].

| Метод и путь относительно base | Контракт |
| --- | --- |
| `POST /upload` | `multipart/form-data`, поле `file`; ответ содержит `id`, `path`, status. |
| `POST /upload-from-url` | JSON `{"url":"https://...","adjust":false}`; backend скачивает и сохраняет медиа. |
| `POST /posts` | Создание/расписание/черновик; см. payload ниже; ответ массив `{postId,integration}`, а не подтверждение публикации в соцсети. |
| `GET /posts?startDate=ISO&endDate=ISO` | `{posts:[...]}`, в том числе `state`, curated `error`, `releaseId`, `releaseURL`, `group`; необязательный фильтр `customer`. |
| `DELETE /posts/:id`, `DELETE /posts/group/:group` | Удаляется вся группа в Postiz, scheduler workflows прекращаются; **опубликованный объект в соцсети не удаляется**. |
| `GET /integrations`, `GET /groups` | Каналы организации, optional `?group=...`; группы клиентов служат фильтрами. |
| `GET /integration-settings/:id` | DTO schema, ограничения, tools для конкретного канала; использовать для генерации payload. |
| `PUT /posts/:id/settings`, `PUT /posts/:id/status` | Правка settings непубликовавшегося поста; смена `draft`/`schedule`. |

Источники всей таблицы: [controller][api], [service и response][posts-service], [repository и soft-delete][posts-repo], [query DTO][get-posts].

Для `upload-from-url` источник должен быть доступен backend без авторизации; безопаснее заранее копировать файл в Postiz, чем оставлять будущую публикацию на истекающем внешнем URL. [URL upload](https://docs.postiz.com/public-api/uploads/upload-from-url).
Поток `upload → {id,path} → posts[].value[].image[]`: массив называется `image` и для MP4. `type` = `schedule`/`now`/`draft`; дата ISO обязательна DTO даже для `now`, хотя фактический срок тогда текущий. Один запрос может содержать много каналов, но дату public controller делает общей для запроса. `settings.__type` желательно передавать явно; server дополнительно выводит его из integration. [DTO][create-dto], [mapTypeToPost/createPost][posts-service], [controller][api].
Пример тела `POST /posts` для одной IG Story, после загрузки файла; заменить дату будущей, IDs и URL реальными. [IG DTO][ig-dto], [Create API][create-doc].
```json
{"type":"schedule","date":"2026-10-26T10:00:00Z","shortLink":false,"tags":[],"posts":[{"integration":{"id":"IG_CHANNEL_ID"},"value":[{"content":"","image":[{"id":"MEDIA_ID","path":"https://HOST/uploads/story.jpg"}]}],"settings":{"__type":"instagram","post_type":"story"}}]}
```
Upload API проверяет реальный MIME; JPEG/PNG/GIF/WebP/AVIF/BMP/TIFF до 10 MiB, MP4 до 1 GiB; PDF/audio не принимает. Ограничения самого соцпровайдера могут быть ниже. `adjust=true` опционально нормализует медиа через настроенный processor; ждать `GET /media/:id/status` до `ready`, проверять warning, иначе публикация может взять оригинал. `adjust` в текущей реализации требует Cloudflare storage + RunPod; без них это не замена собственному ffmpeg. [Upload factory][upload-factory]. [Upload validation][upload-validation], [media service][media-service], [upload docs][upload-doc].
**Rate limit по коду**: `API_LIMIT` запросов за час, default **90**, счётчик по `org.id`, Redis; env общий для инстанса, бюджет у каждой организации свой. Bundled compose задаёт **30**, docs overview говорит 90/Cloud 100, embedded OpenAPI местами ещё пишет 30 для всего API. Guard ограничивает POST с URL, содержащим `/public/v1/posts`, а не uploads/list/delete; квоты самих соцсетей независимы. [Guard][throttle], [app.module][app], [compose приложения][app-compose], [overview][api-doc].
**Официальные инструменты есть**: MCP внутри backend, n8n community node `n8n-nodes-postiz` в [gitroomhq/postiz-n8n](https://github.com/gitroomhq/postiz-n8n), Node SDK `@postiz/node` (`1.0.8` в source), CLI `postiz`. В bundled nginx MCP будет `/api/mcp` или `/api/mcp/:key`; docs пример `/mcp` требует соответствующего proxy routing. [MCP source][mcp], [setup](https://docs.postiz.com/mcp/setup), [SDK][sdk], [SDK package][sdk-package], [CLI](https://docs.postiz.com/cli/introduction).
SDK тонкий: post/postList/upload/integrations/deletePost, без проверок `response.ok`; `upload()` назначает JPEG MIME всем неизвестным extensions, включая mp4. Для конвейера рекомендую прямой HTTP adapter с собственными timeout/retry/error handling, а не слепое использование SDK video upload. [SDK source][sdk].

## 3. Что реально публикуют providers

| Provider / `settings.__type` | Типы и необходимые настройки по коду |
| --- | --- |
| Instagram `instagram` | Feed photo, carousel из фото/видео, Reel из одного MP4, **image/video Stories**. Обязателен `post_type:"post"` или `"story"`; `reel` невалидно. Один MP4 + `post` превращается в `media_type=REELS`; >1 media + `post` в `CAROUSEL`; `story` в `STORIES`. FB-linked validator ограничивает набор 10 media. [Provider][ig], [DTO][ig-dto]. |
| Instagram `instagram-standalone` | Те же publishing methods с `graph.instagram.com`, тот же DTO; нужен professional account. Standalone валидатор не повторяет лимит 10, поэтому конвейеру нужен свой единый предел. `audio` поддержан только у FB-linked Reels; optional `is_trial_reel`, `graduation_strategy`, `collaborators:[{label}]`, media `thumbnail`/`thumbnailTimestamp`. [Standalone][igs], [IG][ig], [setup][ig-setup]. |
| Facebook Page `facebook` | Text/link, одно/несколько фото через unpublished photos + feed; видео через `/{page}/videos`; **фото- и видеосторис** через `photo_stories` / `video_stories`. `post_type:"story"` включает stories, иначе обычный post; optional `url`, video `title`, text `text_format_preset_id`. Каждый attachment Story публикуется отдельно. [Provider][fb], [DTO][fb-dto]. |
| Telegram `telegram` | Текст, фото, MP4, **альбом фото/видео** через `sendMediaGroup`; только `{"__type":"telegram"}`. Назначение задано integration, а не settings. Несколько медиа в **одном** `value[].image[]`; код режет по 10, caption только у первого элемента первой пачки. [Provider][tg], [API docs](https://docs.postiz.com/public-api/providers/telegram). |
| YouTube `youtube` | Загрузка одного видео, включая будущие Shorts, через resumable `videos.insert`; отдельного `shorts` флага нет. Обязательны `title` 2-100 символов и `type:"public"/"unlisted"/"private"`; optional `selfDeclaredMadeForKids:"yes"/"no"`, `tags:[{label,value}]`, `thumbnail`. Shorts классифицирует YouTube по квадратному/вертикальному видео до 3 минут. [Provider][yt], [DTO][yt-dto], [правило YouTube](https://support.google.com/youtube/answer/15424877?hl=en). |
| TikTok `tiktok` | Одно видео либо фото-пост/набор фото. DTO требует `privacy_level`, booleans `duet`, `stitch`, `comment`, `brand_content_toggle`, `brand_organic_toggle`, `autoAddMusic:"yes"/"no"`, **`content_posting_method:"DIRECT_POST"`**. `UPLOAD` отправляет в inbox для ручного завершения, не публикует; большинство settings тогда игнорируется. Optional `title`, video `video_made_with_ai`. [Provider][tt], [DTO][tt-dto]. |
| LinkedIn Page `linkedin-page` | Text, image/multi-image, один video; page-класс использует общий LinkedIn implementation с company author. Optional `post_as_images_carousel:true` конвертирует >=2 изображения в PDF document carousel, `carousel_name` задаёт заголовок. Прямой PDF upload через public API не поддержан. [Page][lip], [общий provider][li], [DTO][li-dto], [docs][li-setup]. |

**FB Reels требуют отдельной проверки.** Source строит URL `/reel/{videoId}`, но отправляет MP4 в `/videos`, не `/video_reels`, и не имеет `post_type:reel`. Meta объявила перевод всех новых видео в Reels, однако это не доказывает нужную дистрибуцию именно наших API-публикаций. До smoke-test на нужных Pages считать подтверждённой video-публикацию; если нужна явная Reels-семантика, оставить прямой Meta adapter. [Код][fb], [объявление Meta](https://about.fb.com/news/2025/06/making-it-easier-create-videos-facebook/).
**IG Stories не означают интерактивные stories.** В API Postiz нет link/poll stickers; текст/логотип/субтитры нужно рисовать в медиа. FB-linked Stories планировать для Business account: Meta отдельно ограничивает их Business, а Creator не обещать без проверки. Устаревшая `@Rules` строка Postiz говорит про одну картинку, фактический pending/finalize код отправляет и видео, и несколько отдельных stories. [IG setup][ig-setup], [Meta collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api), [код][ig].
**Telegram ограничения**: один `TELEGRAM_TOKEN` на установку, общий bot client для всех org; подключение проверяет admin бота через `/connect`. Несколько компаний могут использовать разные каналы одного бота, но собственный бот на компанию в этом provider не предусмотрен. Для одного альбома конвейеру держать 2-10 элементов и caption <=1024 символов после parsing; auto-chunk 11 файлов оставит невалидную одиночную группу. [Bot API](https://core.telegram.org/bots/api#sendmediagroup). У альбома сохраняется только первый `message_id`, у серий IG/FB stories возвращается один итоговый ID; полного ledger всех частей нет. Для полного удаления/редактирования нужен свой ledger/adapter. [Telegram][tg], [IG][ig], [FB][fb], [setup TG](https://docs.postiz.com/self-host/providers/telegram).
Self-host требует своих developer apps, OAuth permissions и approvals: Meta Live/Advanced Access для сторонних компаний, LinkedIn требуемые organization scopes, TikTok audit для публичного Direct Post. Это не снимается наличием Postiz. Новый отдельный `tiktok-business` использует TikTokDto, добавляет `music`/`location` и отдельные credentials; `privacy_level` для его видео API не передаёт, поэтому паритет с обычным `tiktok` не предполагать; выбирать по подключённой integration. [Meta setup][ig-setup], [LinkedIn][li-setup], [TikTok setup](https://docs.postiz.com/self-host/providers/tiktok), [Business provider][tt-business], [r2.24][r224].

## 4. Multi-tenancy и доступ участников

- **Логическая multi-tenancy есть.** Organization владеет integrations/posts/media; UserOrganization задаёт membership/role, пользователь может состоять в нескольких org и переключаться. Public API извлекает org из ключа и передаёт org ID в queries; это shared DB/processes, не отдельная инфраструктура компании. [Schema][schema], [session auth][session-auth], [public auth][public-auth], [posts repo][posts-repo].
- Для неродственных компаний создавать **отдельные Organization и ключи**, а не Customer/groups внутри одной org. Customer API только группирует и фильтрует каналы; это не tenant boundary. Один инстанс подходит для управляемых оператором workspace, но строгую изоляцию недоверенных tenants source-review не доказал. [Controller][api], [schema][schema], [advisory JWT][jwt-psa].
- Роли `USER`, `ADMIN`, `SUPERADMIN` предусмотрены, Teams доступны self-host. По документации USER работает с каналами/постами, ADMIN управляет командой, SUPERADMIN billing; **нет роли upload-only / own-posts-only / отдельного канала** в показанной модели. Для простого добровольца это слишком широкий доступ. [Team docs](https://docs.postiz.com/general/settings/team), [schema][schema], [permissions][permissions].
- **Найденный source-level риск latest**: `PermissionsService.check()` при отсутствии `STRIPE_PUBLISHABLE_KEY` разрешает requested permissions до проверки ADMIN. `POST /settings/team` полагается на эту policy, `inviteTeamMember()` не проверяет роль повторно. Поэтому UI-скрытие Teams для USER не доказывает запрет приглашать ADMIN на обычном self-host. Нужен deny-тест и исправление owning permission layer, прежде чем выдавать ограниченные аккаунты; эксплуатация на живой установке не выполнялась. [Permissions][permissions], [settings controller][settings], [org service][org-service].
- Медиа local storage раздаётся по публичному URL без tenant auth. Postiz media library не использовать как закрытый архив исходников фонда; приватное intake/object storage и выдачу подготовленных publishing assets держать у фабрики. [Nginx][nginx], [local route][local-route], [TASK.md](TASK.md).

## 5. Ресурсы и эксплуатация

- Канонический [compose repo][compose] на commit `dd4969e...` содержит **9 сервисов**: Postiz, app PostgreSQL 17, Redis 7.2, Temporal 1.28.1, Temporal PostgreSQL 16, Elasticsearch 7.17.27, Temporal UI, admin-tools, Spotlight. Postiz включает frontend/backend/orchestrator через PM2. Отключение UI/admin-tools/Spotlight оставляет 6 сервисов той же архитектуры. [Compose][compose], [root scripts][package], [backend package][be-package], [frontend package][fe-package], [orchestrator package][or-package].
- Официальный floor **2 vCPU / 2 GB**, рекомендовано **4 vCPU / 8 GB**, диск 20 GB минимум / 50 GB + uploads. 2 GB описаны как single-user light use без запаса; для многих пользователей/workflows docs требуют >=4 GB. Это заявленные требования, не наши замеры и не sizing для установки с десятками каналов. Начинать нагрузочную проверку с 8 GB и реальной смесью видео/расписаний. [Requirements][requirements], [контекст](TASK.md).
- Elasticsearch используется Temporal visibility/search, не AI-поиском медиа. В canonical compose heap ограничен 256 MiB, в compose основного app repo такой настройки нет. ES **не принципиально обязателен**: Temporal поддерживает PostgreSQL advanced visibility с Server 1.20+, но это отдельная topology/migration, не простое удаление контейнера. Нужны custom search attributes Postiz и сохранение работающих запросов отмены/поиска workflows. [Canonical compose][compose], [app compose][app-compose], [Temporal docs](https://docs.temporal.io/self-hosted-guide/visibility), [attributes][attributes], [delete flow][posts-service].
- Операционная цена: backup/restore двух БД и медиа, сохранность Temporal visibility, регистрация новых workflow versions, наблюдение за зависшими/неподтверждёнными публикациями и OAuth reconnect. SQL-visibility уменьшит число компонентов, но я рекомендую сначала проверенный canonical stack и потом отдельно мерить/упрощать. В `2.23` streaming uploads снижает расход памяти на видео, но не даёт SLA всей фабрике. [Compose][compose], [r2.23][r223], [r2.24][r224], [workflow][workflow].

## 6. Вердикт и что остаётся фабрике

**Да, условно: Postiz подходит как scheduler + publishing backend за собственным сервисом фабрики.** Feed-посты, IG Reels, image/video IG/FB Stories и Telegram media groups имеют реальные API/provider пути. **Для единой готовой multi-company системы с ограниченными волонтёрами его недостаточно**: нужны контроль доступа фабрики, latest security fixes и проверка FB Reels/нужных аккаунтов. [API][api], [IG][ig], [FB][fb], [Telegram][tg], [permissions][permissions], [релиз][release].

Своими остаются следующие части, исходя из контракта и найденных границ Postiz:
1. Intake Telegram/ссылок/голоса, авторство/согласия, приватные оригиналы, brand instructions, AI-отбор, монтаж/субтитры/обложки/подготовка story. Postiz получать готовые derivatives. [Контракт](TASK.md), [upload contract][upload-validation], [media processor][media-service], [IG setup][ig-setup].
2. Сервис с tenant → org/key/channel mapping, секретами только на backend, upload-only интерфейсом волонтёра и собственным approval gate; patch и deny-тест self-host permissions до открытия Postiz UI таким людям. [Public auth][public-auth], [schema][schema], [permissions][permissions], [settings][settings].
3. Собственная idempotency по `factory_job_id`, reconciliation `postId → state/error/releaseId`, retries только после сверки результата. POST создаёт новые записи/запускает workflow без публичного idempotency key; workflow start error проглатывается, поэтому HTTP success не подтверждает даже успешный запуск. Provider pending-защита уменьшает дубли, но не делает повторный HTTP POST идемпотентным. [Create service][posts-service], [workflow][workflow].
4. Полный Telegram message ledger и собственные delete/edit уже опубликованного; при необходимости разные bot identities по организациям. До патча возвращаемых IDs это отдельный Telegram adapter. Для FB Reels держать существующий прямой Meta путь до успешной проверки нужного формата. [TG][tg], [delete flow][posts-service], [FB][fb].
5. Контроль медиа-лимитов, provider app approvals, токенов, ошибок, backup и нагрузочный мониторинг. Правило шабат-паузы закладывать во внешнем admission/schedule gate и учитывать уже созданные/повторяемые jobs: workflow спит до `publishDate`, специальной паузы по локальному закату в проверенном publishing workflow нет. [Setup][ig-setup], [TikTok](https://docs.postiz.com/self-host/providers/tiktok), [validation][upload-validation], [workflow][workflow].

**Критерий допуска**: на обновлённом staging одна отдельная org на компанию; API-цепочки upload/schedule/cancel, IG photo/carousel/reel/story, FB photo/video/story и фактический FB Reel, TG mixed album; отрицательные проверки чужого org/key и USER → team invite; рестарт перед временем публикации; затем проверка реальных release IDs в соцсетях. До этого primary signal **partial**: source/docs подтверждены, runtime publication и isolation не проверены. [Проверяемые контракты][api], [workflow][workflow], [permissions][permissions].

## Первичные исходники

[release]: https://github.com/gitroomhq/postiz-app/releases/tag/v2.25.3
[releases]: https://api.github.com/repos/gitroomhq/postiz-app/releases?per_page=100
[compare]: https://github.com/gitroomhq/postiz-app/compare/v2.21.10...v2.25.3
[security-api]: https://api.github.com/repos/gitroomhq/postiz-app/security-advisories?per_page=100
[traversal]: https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-4hgh-5rhf-4qpm
[rng]: https://github.com/gitroomhq/postiz-app/security/advisories/GHSA-4hw5-43cf-g9wp
[jwt-psa]: https://gadvisory.org/advisories/PSA-2026-YT2HMH
[r222]: https://github.com/gitroomhq/postiz-app/releases/tag/v2.22.1
[r223]: https://github.com/gitroomhq/postiz-app/releases/tag/v2.23.0
[r224]: https://github.com/gitroomhq/postiz-app/releases/tag/v2.24.0
[r225]: https://github.com/gitroomhq/postiz-app/releases/tag/v2.25.0
[requirements]: https://docs.postiz.com/self-host/installation/system-requirements
[api-doc]: https://docs.postiz.com/public-api/introduction
[create-doc]: https://docs.postiz.com/public-api/posts/create
[upload-doc]: https://docs.postiz.com/public-api/uploads/upload-file
[ig-setup]: https://docs.postiz.com/self-host/providers/instagram
[li-setup]: https://docs.postiz.com/self-host/providers/linkedin-page
[api]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/src/public-api/routes/v1/public.integrations.controller.ts
[public-auth]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/src/services/auth/public.auth.middleware.ts
[session-auth]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/src/services/auth/auth.middleware.ts
[auth]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/src/services/auth/auth.service.ts
[auth-helper]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/helpers/src/auth/auth.service.ts
[schema]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/database/prisma/schema.prisma
[permissions]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/src/services/auth/permissions/permissions.service.ts
[settings]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/src/api/routes/settings.controller.ts
[org-service]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/database/prisma/organizations/organization.service.ts
[posts-service]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/database/prisma/posts/posts.service.ts
[posts-repo]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/database/prisma/posts/posts.repository.ts
[get-posts]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/posts/get.posts.dto.ts
[create-dto]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/posts/create.post.dto.ts
[ig]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/instagram.provider.ts
[igs]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/instagram.standalone.provider.ts
[ig-dto]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/posts/providers-settings/instagram.dto.ts
[fb]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/facebook.provider.ts
[fb-dto]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/posts/providers-settings/facebook.dto.ts
[tg]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/telegram.provider.ts
[yt]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/youtube.provider.ts
[yt-dto]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/posts/providers-settings/youtube.settings.dto.ts
[tt]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/tiktok.provider.ts
[tt-business]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/tiktok.business.provider.ts
[tt-dto]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/posts/providers-settings/tiktok.dto.ts
[lip]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/linkedin.page.provider.ts
[li]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/integrations/social/linkedin.provider.ts
[li-dto]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/posts/providers-settings/linkedin.dto.ts
[upload-validation]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/upload/custom.upload.validation.ts
[media-service]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/database/prisma/media/media.service.ts
[app]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/src/app.module.ts
[app-compose]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/docker-compose.yaml
[package]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/package.json
[be-package]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/backend/package.json
[fe-package]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/frontend/package.json
[or-package]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/orchestrator/package.json
[workflow]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/orchestrator/src/workflows/post-workflows/post.workflow.v1.1.2.ts
[attributes]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/temporal/temporal.search.attribute.ts
[nginx]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/var/docker/nginx.conf
[local-route]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/frontend/src/app/%28app%29/api/uploads/%5B%5B...path%5D%5D/route.ts
[mcp]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/chat/start.mcp.ts
[sdk]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/sdk/src/index.ts
[sdk-package]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/apps/sdk/package.json
[ssrf]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/dtos/webhooks/ssrf.safe.dispatcher.ts
[secure-id]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/services/make.secure.id.ts
[old-org]: https://github.com/gitroomhq/postiz-app/blob/4cfe33d100db79d06702d859c2dd5ca0e03b721e/libraries/nestjs-libraries/src/database/prisma/organizations/organization.repository.ts
[old-enterprise]: https://github.com/gitroomhq/postiz-app/blob/4cfe33d100db79d06702d859c2dd5ca0e03b721e/apps/backend/src/api/routes/enterprise.controller.ts
[old-auth]: https://github.com/gitroomhq/postiz-app/blob/4cfe33d100db79d06702d859c2dd5ca0e03b721e/apps/backend/src/services/auth/auth.service.ts
[old-ssrf]: https://github.com/gitroomhq/postiz-app/blob/4cfe33d100db79d06702d859c2dd5ca0e03b721e/libraries/nestjs-libraries/src/dtos/webhooks/ssrf.safe.dispatcher.ts
[throttle]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/throttler/throttler.provider.ts
[compose]: https://github.com/gitroomhq/postiz-docker-compose/blob/dd4969e5e694cd009619a0d53cff14c21104580b/docker-compose.yaml
[old-id]: https://github.com/gitroomhq/postiz-app/blob/4cfe33d100db79d06702d859c2dd5ca0e03b721e/libraries/nestjs-libraries/src/services/make.is.ts
[upload-factory]: https://github.com/gitroomhq/postiz-app/blob/a5affe62c74e39c1e7ac960d50d8418b807d532c/libraries/nestjs-libraries/src/upload/upload.factory.ts
