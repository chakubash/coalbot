# Coalbot instructions for Codex

This is a production Telegram bot for monitoring the Chinese coal market.

Critical rules:
- Do not commit secrets, tokens, .env files, subscribers, browser profiles, logs, runtime state, cache, or data_runs.
- Do not enable a second Telegram polling bot. Only coalbot.service should poll Telegram.
- coalbot-reports.service must remain disabled/masked because it conflicts with coalbot.service getUpdates.
- Weekly/monthly reports must be sent via one-shot scripts/timers, not via a second polling bot.
- Browser/CDP ports:
  - Mysteel: 127.0.0.1:9222
  - SXCoal: 127.0.0.1:9223
- Main service: coalbot.service.
- Browser keepalive service: coalbot-browser-keepalive.service.

Report style:
- Morning report: market picture, key events, market map, what to watch until evening.
- Evening report: day picture, key events, market map, what changed after morning, what matters tomorrow.
- Do not include status/debug blocks in user-facing Telegram summaries.
- Do not label key events with importance tags.
- Do not add long analysis after each news item.
- Do not include empty market-map lines such as "no significant signals".
- China coal mine accidents, illegal mines, fatalities, safety inspections, shutdowns and industrial-safety policy are high priority and must not be filtered out.
- If an accident happened at an illegal mine, direct price impact may be limited, but it must still be included as an industrial-safety market event.

Before changes:
- Inspect the pipeline before patching.
- Prefer small patches.
- Run py_compile on edited files.
- Do not change scheduling, timers, Telegram token handling, or systemd units unless explicitly requested.
