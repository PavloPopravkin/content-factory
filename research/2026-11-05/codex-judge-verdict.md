# Architecture verdict

**Winner: thin-fork hybrid, 75/100, conditional on the corrections below. None is production-ready as specified.** It best combines a genuine Postiz admin surface, Telegram continuity, Python reuse, and a bounded fork. Sidecar fails the mandatory enforcement requirement; deep fork buys integration by replacing working logic and expanding maintenance.

Assessment uses supplied documents only. No network, Docker, live-system access, or runtime verification. Citations are relative to this directory unless prefixed `../../`.

## Scores

Weighted points, not percentages within columns. Fatal requirements cannot be traded away by a high total.

| Design | Literal fit /20 | Maintenance /20 | Safety /25 | Reuse /15 | Commercial /5 | Phasing /10 | Accuracy /5 | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Deep fork | 19 | 7 | 13 | 7 | 3 | 5 | 3 | **57** |
| Sidecar | 9 | 16 | 4 | 14 | 2 | 5 | 3 | **53** |
| Thin-fork hybrid | 17 | 15 | 15 | 14 | 4 | 7 | 3 | **75** |

## Shared fatal acceptance gaps

**An entry guard is not yet a non-bypassable publication boundary.** Both forks guard the beginning of `postSocialInternal`. Scouts identify two-phase publishing, subsequent comments, and plugs, but do not establish that every externally visible operation traverses that guard (`postiz-code.md:13,43-61,104`). Require a call-path inventory covering finalization, retries, comments, reposts, and direct adapters. Check policy immediately before each publishing HTTP operation; bind admission to tenant, integration, immutable payload, approval version, and delivery attempt. Unknown/unmapped Postiz posts must be denied, not exempted. Guarding content reloaded from the database is insufficient unless those exact bytes are sent.

**Fact references do not validate prose.** All three allow generated captions while checking fact IDs, forbidden phrases, or numbers (`design-deep-fork.md:169-171`; `design-sidecar.md:155-160`; `design-thin-fork-hybrid.md:223`). A caption can cite an allowed fact and invent a nonnumeric guarantee. WWG needs approved claim templates/typed substitutions, provenance tied to the facts-file version, and rejection of unsupported claims, including text embedded in media (`wwg-tenant.md:55`). Owner approval remains additional, not a facts-policy override.

**Shabbat still has execution gaps.** Entry checks cannot stop an accepted remote job completing later; fixed 15/60-minute leads do not prove otherwise (`design-sidecar.md:172`; `../../DEBT.md`, “Открыто после phase 1”). Specify a conservative admission cutoff and the residual external-completion limitation. Stop automation beyond publishing: curators, reminders, summaries, and secondary actions. Unknown Spanish location must fail closed or use a demonstrated conservative policy, not guessed sunset.

## Deep fork: 57/100

Strongest literal integration, native admin, actor-aware approval, immutable derivatives, and dedicated commercial deployments (`design-deep-fork.md` §§3-5,8-9). But it ports tested Python policy, journal, and scheduling into TypeScript and introduces new Temporal workflows. Existing core has 185 passing tests but no publishing smoke evidence (`cf-core-fit.md:10-15`); a port loses reuse without supplying that missing evidence.

**FATAL as written:** delivery is marked pending before the provider, then completed through a post-publication webhook (`design-deep-fork.md:191`). This does not specify incremental external-ID checkpoints, ambiguous-outcome handling inside Temporal retries, or reconciliation when the webhook is lost. A factory fence cannot prevent retries performed inside Postiz. Require the transport state machine before launch (`../../MANIFEST.md:20-29`). Shared fatal gaps also apply.

The patch budget is internally implausible: every upstream edit supposedly stays under 20 lines, yet FB Reels/albums and possible token encryption are included (`design-deep-fork.md:214,246-258`). First WWG post requires P0-P2, **13-18 engineering days**, before OAuth delays; the suggested November 6-10 slots cannot serve that future cutover (`:229,282-284`).

## Sidecar: 53/100

Best reuse and easiest upstream image replacement. Preserving steward, command routing, Ukrainian summaries, and the existing core is sound.

**FATAL:** the 60-second sweeper is detection, not enforcement. Immediate publication bypasses it; a scheduled post due before the next sweep also escapes. Trusting Pavel's account cannot enforce mandatory owner approval or Shabbat (`design-sidecar.md:183-188,337-339`). Its own admission that `now` escapes is decisive. Recommending a guard only “if Pavel requires” it contradicts this task (`:276`).

Menu injection plus unverified cookie introspection is a fragile approximation of an admin inside Postiz (`:228-232`). Direct GBP, Telegram, and FB Reels remain parallel publishing paths (`:201-212`). One shared commerce instance does not eliminate cross-client token concentration (`:252`). The proposed four-to-six-week first publication is slower than its “start without a fork” framing suggests (`:329`).

## Thin-fork hybrid: 75/100

Correct division of ownership: Python policy and journal, Telegram gateway, Postiz UI/session bridge, fail-closed execution hook. Keeping the authoritative plan in Python is compatible with an embedded admin; `cf-core-fit.md:34-36` presents a false dichotomy when it equates that choice with an external admin.

**FATAL until repaired:** P1 lacks the complete payload/admission/attempt contract described above. GBP and FB Reels bypass Postiz indefinitely unless their cutover becomes mandatory (`design-thin-fork-hybrid.md:206-209`). That is an interim bridge, not literal completion of “through Postiz.” Move the already-existing GBP provider into the first WWG acceptance slice; make the Reels provider patch mandatory before offering Reels.

Migration M3 redirects intake before old publishing channels are retired, without specifying how their plan continues receiving new material (`:245-249`). Add an explicit shadow-output bridge and one active publisher per channel. First WWG publication is roughly **14.5-15.5 engineering days plus seven shadow days**, not the two-week admin milestone (`:312-317`). OAuth and GBP access belong in the first feasibility spike.

## Accuracy and licensing corrections

- All designs correctly reject native approval and a conversational Telegram provider (`postiz-code.md:65,83`). Hybrid/sidecar saying the agent simply schedules overlooks deep fork's claimed draft-tool support (`design-deep-fork.md:154`); scouts leave that capability unverified (`github-analogs.md:116`).
- Scouts conflict on GBP video: `postiz-code.md:18` describes VIDEO submission; `wwg-tenant.md:62` reports validation forbidding it. Do not advertise support. Deep fork also claims absent `OPENAI_API_KEY` from a scout that does not establish that absence (`design-deep-fork.md:173`; `cf-core-fit.md:12`).
- Hybrid incorrectly calls OurKids tokens definitively expired and YourCamp unmigrated ministry (`:104,253`): token usability is unverified, and YourCamp's Telegram channel already runs in the charity pipeline (`postiz-live.md:71`; `yourhelp-system.md:32,55`).
- AGPL permits commercial sale. Modified-network users need corresponding-source access; “all code must be public” overstates the supplied license analysis (`postiz-code.md:128`). HTTP/iframe separation is not a guaranteed licensing exemption. Sidecar's dismissal of dependency licenses because clients avoid the UI is unsupported (`design-sidecar.md:263`). Preserve notices, offer complete fork source/build material, and resolve Polotno before sale. No supplied evidence establishes a categorical trademark prohibition.

## Graft into the winner

From **deep fork**, take exact approval hashing of ordered derivative bytes, provider settings, integration IDs and scheduled time; dedicated commercial deployment; parallel intake shadowing (`§§4.4,9,10.2`).

From **sidecar**, take batch-scoped tenant selection, explicit expiry/reminder behavior, legacy approval/history import, and measurable shadow comparisons (`§§4,12-14`). Keep its sweeper only for diagnostics. Ship one manually prepared, owner-approved WWG post through Postiz with working embedded approval/journal screens before expanding the curator or media library.

**Release gate:** authenticated admission calls; wrong-tenant and unapproved native posts denied; edits after approval rejected; factory outage blocks delivery; delayed finalization crosses blackout safely; lost provider responses never trigger blind retries. Run that behavioral matrix after every upstream upgrade. Patch application and a successful build alone cannot establish safety (`postiz-code.md:117-119`).
