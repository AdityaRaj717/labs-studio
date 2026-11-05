# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

Windows desktop app. PySide6 (Qt 6.12), no web view for the UI. Minimum window 900x600.

## Users

A solo video producer making YouTube and episodic content. They run long batches of image and video shots through Google Flow, often supervising agents, and spend hours at a time in the app.

## Product Purpose

Labs Studio turns lists of prompts into finished stills and animations, saved to disk, using the producer's own Google Flow subscription in their own Chrome. Success is a batch of shots the producer has looked at and approved, with no surprise spend.

## Positioning

A local production desk over Google Flow. One engine owns Chrome, the queue, the credit ledger and the files; the app and any agent are clients of it. Characters and scenes stay consistent across shots through reference images. Credit spend is gated, never implied.

## Operating Context

- The main activity is reviewing results: scanning takes, then approve, reject, retry or modify.
- Queue and settings support that review. Prompts come from text or xlsx files, paste, or an agent.
- Productions created by agents appear in the same tables as the producer's own rows.
- Batches run for a long time, one job at a time with gaps, so the app is often open and glanced at.
- Generated images are the content. Their colours must be judged accurately.

## Capabilities and Constraints

- Pages: Flow Image, Flow Video, Projects, Characters, Scenes, Webhook API, Detailed Log, Settings (Web Sessions, API keys), Help. Every feature and setting stays.
- Screens may be restructured. The engine, queue, providers and storage do not change.
- Terms come from GLOSSARY.md: Production, Item, Take, Reference, Still, Animation, Run, Engine, Ledger, Gate.
- UI text goes through `src/i18n.py` and `src/languages/`.
- Offline test suites stay offline. Live Flow is touched only through the engine.
- Keys live in Windows Credential Manager, never in files.
- Dark and light modes both exist and persist.
- The help guide's screenshots are generated from the real window by `tools/make_help_screenshots.py` and address widgets by attribute path.

## Evidence on Hand

No customers, testimonials or benchmarks exist; none may be invented. Demo data for screenshots is synthetic and lives in `tools/make_help_screenshots.py`.

## Product Principles

1. The picture comes first. The interface recedes so the producer can judge the work.
2. Spend is never a surprise. Anything that costs credits says so before it happens.
3. State at a glance. A long run must be readable from across the room.
4. Agent work and human work share one desk, and origin is always visible.
5. Nothing destructive or spending happens from one stray click.
