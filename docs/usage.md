# Usage

Commands live in Telegram's `/` menu (published on startup); `/help` prints the same list plus the preview buttons.

## How it works

1. You send a voice (or text) message to the bot.
2. Voice is transcribed with OpenAI Whisper.
3. The formatter generates a title, tags, and a lightly cleaned text candidate.
4. The bot shows a preview — generated title/tags, but the original transcription as the text.
5. Optionally **Format** to swap in the cleaned text (split into paragraphs); **↺ Original** restores it.
6. Optionally mark the entry as a highlight ⭐.
7. Press **Save** — the entry becomes its own row in your Notion database.

## Editing before saving

The processing reply turns into a single preview message you edit in place:

```
Generated title

Original transcribed text

Date: Today (YYYY-MM-DD)

Daily sport health

[ ✎ Title ]  [ ✎ Text ]  [ ✎ Tags ]
[              ✦ Format              ]
[        Date: Today (YYYY-MM-DD)        ]
[      Mark as Highlight ⭐       ]
[            🔥 Roast             ]
[            ✓ Save              ]
[            Cancel              ]
```

- **✎ Title / Text / Tags** — prompt you for a new value; the preview updates in place.
- **✦ Format** — replaces only the draft text with the formatter's cleaned version (semantic paragraphs, saved as separate Notion blocks). It fixes recognition/grammar slips without changing your wording or meaning. Becomes **↺ Original** so you can revert.
- **Date** — opens a 7-day picker. **Back to preview** keeps the date; **Cancel draft** discards.
- **Cancel** — discards the draft without saving.

Nothing is written to Notion until you press **Save**. If saving fails, the preview stays with the Save button so you can retry. If the bot recognizes an already-saved voice message, it warns you first and offers **Add anyway**.

## Highlights

**Mark as Highlight ⭐** flags the entry as a key moment of the week (toggle to unmark). Saved highlights get a `⭐` prefix on the Notion heading and are surfaced first in the weekly report.

## 🔥 Roast mode (разъёб)

**🔥 Roast** sends the current draft to a high-reasoning model that plays a blunt-but-caring street-bro: honest, on your side, teasing where it helps, never sugar-coating. The take is posted as a new reply — your draft is never modified.

Reply to any roast message to keep the thread going; the bot sends the whole prior chain plus your reply back to the model. Voice replies work too — they're transcribed first and never become a new diary entry. These conversations live in RAM only and are discarded on restart.

The button is available whenever the active AI provider's API key is set (see [Configuration](configuration.md)). The persona is built in but can be replaced with `ROAST_SYSTEM_PROMPT`; set `ROAST_LANGUAGE` to force a reply language regardless of the entry's language.

### Behavior rules — `/rules`

Separate from the profile, the bot keeps a short list of **behavior rules** — standing instructions on how it should act ("stop asking questions", "swear less", "be blunter about money"). They are injected at the end of the roast system prompt and **outrank the persona**: on conflict, the rules win.

There are two ways to change the list. Tell the bot in a roast reply how it should behave — or that it should forget a rule — and it edits the list itself. This works **in any turn**: the first roast, a follow-up, a voice reply. Each rule carries an id; the model appends operations addressing those ids (`create`, `modify`, `delete`) to the end of its answer behind an internal marker. The bot strips the marker, applies the operations locally, and posts a short `🧠 Memory updated` note with a `Rules:` block. When nothing should change the model sends no operations at all, so a normal reply costs nothing extra and **local state is never rewritten**. An unreadable block, or an operation aimed at an id that does not exist, is dropped and changes nothing.

Or edit the **`Memory — Bot rules`** page next to your diary database directly: add, reword, reorder, or delete a bullet and the bot adopts your version before its next roast — a page you touched by hand outranks what the bot stored. Emptying the page clears the rules.

`/rules` prints the current numbered list, pulling from Notion first. Rules persist in local state, sync both ways with the page, and are fed into every roast — see [Configuration](configuration.md#memory-pages).

### Author profile

The bot keeps an **author profile** — short one-sentence facts about who you are — refreshed from **every diary message** (best-effort, in the background). It accumulates: the list is meant to grow and get more detailed over time. It covers durable, decision-shaping context across the board — long-term traits, biases and habitual reactions, values, drivers and fears, recurring behavior and decision patterns, key relationships, work, money and big goals, body and routine, skills, and your current life phase (medium-term, not day-to-day). One-off detail is not stored, but a durable pattern behind it is.

A fact is only ever removed when it stopped being true or when it folds into a duplicate — never for looking small, weak, or unrelated to today's note. Nothing has to be re-confirmed to survive.

Under the hood each fact carries an id, and the model answers with operations against those ids (`create`, `modify`, `delete`) — never the profile itself. So the request cost stays flat however large the profile grows, a fact the model does not mention cannot be dropped, and an operation aimed at an unknown id is skipped instead of hitting the wrong fact. An unusable response leaves the accumulated profile intact. Facts persist in local state and are fed back as background context on the next roast. Editing the Notion page by hand works too: a bullet whose text you left alone keeps its id, a reworded one becomes a new fact. Pick the model with `OPENAI_PROFILE_MODEL` (defaults to `OPENAI_SUMMARY_MODEL`).

What an entry taught is reported the same way as a rule change: a `🧠 Memory updated` note under the preview, with an `About you:` block listing the facts gained (`+`) and lost (`−`). A reworded fact shows as both. Reply to the note to discuss it — it continues as a normal roast thread. An entry that taught nothing sends nothing.

The profile also lives on a **`Memory — Author profile`** page sitting next to your diary database, so you can read what the bot knows in the same place as your notes — and correct it: edit the bullets and the bot adopts your version, same as with the rules page — see [Configuration](configuration.md#memory-pages).

### Rebuilding the profile retrospectively — `/memory`

`/memory` walks your whole diary history and rebuilds the profile from it, in two steps:

1. **Focus** — the bot asks what should drive this pass (what matters most, what to keep, what to drop). Reply with text or a voice message; send `-` to rebuild without extra focus. The reply is only ever read as focus, never saved as a diary note.
2. **Confirm** — the bot echoes the focus and the current fact count, then waits for **✓ Confirm** or **✗ Cancel**. Nothing runs until you confirm.

On confirm the bot walks every Notion note **oldest-first, one at a time** — one AI request per note, each fed the profile accumulated so far, exactly like the per-message refresh. Existing facts seed the pass and get corrected as it goes; an empty profile is built from scratch. Focus steers what gets pulled out and how known facts are reframed, and is never stored as a fact itself.

The status message shows a live progress bar (throttled to stay inside Telegram's edit rate limits) and the running fact count, and the final message reports the fact delta plus any skipped or failed notes.

The pass is built to be dull and safe:

- **Sequential** — never concurrent, with a short pause between notes so Notion and the AI provider aren't hammered.
- **Single-flight** — a second `/memory` run is refused while one is in flight.
- **Fault-isolated** — a note that can't be read or extracted is counted and skipped; accumulated facts are untouched.
- **Circuit-broken** — the pass aborts once notes fail back-to-back instead of burning one doomed request per remaining note.
- **Incrementally saved** — facts are persisted after every note, so an abort or a restart never loses the pass.

## Tags

The `Daily` tag is always added. Additional tags can be:

- **Extracted by the formatter** — mention them naturally: _"went for a run today. Tags: sport, health"_.
- **Edited manually** — click **✎ Tags** and send them comma-separated: `sport, health, work`.

## Summaries

Every day at 21:00 (your timezone) the bot posts a summary of that day's entries, or a friendly reminder if there were none. Daily and weekly summaries include a small stats block (entry count, saved audio minutes, and the busiest day for weekly reports). Use `/weekly` to generate the weekly highlight report on demand.

`/stat` shows total saved audio time, minutes for each of the last 7 days, and monthly totals for the last 6 months — computed from saved Notion rows with `Audio Duration` filled in.

Date-picker defaults and summaries respect `DIARY_DAY_START_HOUR`: with `DIARY_DAY_START_HOUR=4`, entries before 04:00 belong to the previous diary date.
