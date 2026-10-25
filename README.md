# Content Factory

Self-hosted content factory for nonprofits and small companies. Contributors drop photos, videos and voice
notes into a Telegram bot or an upload link; an AI curator, following each organization's own instructions,
picks the material, cuts reels and stories with subtitles, writes captions in the brand voice and publishes
on schedule to every channel. One install serves many organizations.

**Status:** design stage. See [ARCHITECTURE.md](ARCHITECTURE.md) (in Russian for now) and [research/](research/).

## How it fits together

```
contributors -> intake (bot / link) -> AI curator (sandboxed) -> planner (limits, blackout, approval, media QA)
             -> publisher: Postiz API for most networks, direct Telegram and Meta adapters where needed
```

- The factory owns the schedule; the publishing backend only executes "publish now".
- Every record is bound to an organization (tenant); social credentials live only in the publisher.
- Delivery journal is written before any external call; a lost response becomes `unknown`, never a blind retry.

## License

MIT. Postiz is a separate AGPL-3.0 project used through its public API, not modified or bundled.
