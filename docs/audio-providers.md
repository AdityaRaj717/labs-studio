# Audio providers (read from official docs, 2026-11-02)

## Fish Audio
- `POST https://api.fish.audio/v1/tts`; `Authorization: Bearer`, JSON, `model` header; body `text`, `format`, optional `reference_id`.
- Free: model `s2.1-pro-free`, $0, works on a $0 balance, no hard character cap, Fair Use Policy, no SLA, requests may be used to improve models. Fish's blog gives both Aug 31 and Nov 30, 2026 as the end of free access; the pricing page gives none. Products above $1M ARR must contact Fish.
- Paid: `s2.1-pro`, `s2-pro` $15 per million UTF-8 bytes; `s1` retires Dec 31, 2026.
- Errors: 401 key, 402 no credit (paid model), 400 bad voice or args, 429 limit (5 concurrent under $100 paid, no Retry-After: back off).
- Default stays on the free model; a paid model is only by explicit choice.

## Stable Audio 3
- `POST https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio`, multipart: `prompt` (max 10,000), `model` `stable-audio-3`, `duration` 1 to 380 (default 190: always send it), `seed`, `steps` 4 to 8, `cfg_scale` 1 to 25, `output_format` mp3 or wav.
- Returns 202 and `id`. Poll `GET /v2beta/audio/results/{id}`: 202 running, 200 audio (`accept: audio/*`), 404 expired; kept 24 hours, same key.
- 403 moderation and 422 (`invalid_language`, English only; `copyrighted_content`) are not charged.
- Not free: 8 credits ($0.08) per successful generation whatever the duration. New accounts get 25 free credits, so 3 generations. Credits cost $0.01 each.
- The Stable Audio consumer plan's free credits are not API credits. The open weights (Task 17) are the only free route past those 25.
