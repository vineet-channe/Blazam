Files prefixed `synthetic_` were NOT captured from live services: deliberately triggering
rate limits on free public APIs would be abusive. Each is written from the documented or
widely-reported error format:

- synthetic_deezer_quota.body: Deezer error envelope (observed shape, see deezer_track_notfound.body)
  with code 4 "Quota limit exceeded" (code as reported in public issue trackers; Deezer docs are login-gated).
- synthetic_lrclib_429.body: body copied verbatim from the LRCLIB docs "Rate Limiting" section.
- synthetic_musicbrainz_503.body: MusicBrainz documents HTTP 503 for throttled requests; body text is illustrative.
- synthetic_audd_901.body: AudD error envelope as observed in audd_bad_token.body, with code 901 from the AudD docs.

All other *.body/*.headers files are real responses recorded on 2026-09-29.
