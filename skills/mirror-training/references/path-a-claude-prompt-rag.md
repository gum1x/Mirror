# Path A — Claude persona + RAG

No weights are trained. The Mirror is **the style card (system prompt) + retrieval
over the user's real messages**, running on Claude. This is the fastest path and
the best one for "answers and thinks like me."

## Why this is a real clone, not a shortcut

- **Voice** comes from the style card in the system prompt (measured + enriched
  by `mirror-persona-analysis`).
- **Knowledge & positions** come from RAG: at query time you retrieve the user's
  own past messages on the topic and give them to Claude as "here's how you've
  actually talked about this." The answer is grounded in their real words, not
  hallucinated.
- **Reasoning** comes from the frontier model itself, steered by the style card's
  REASONING section and Claude's adaptive thinking.

## Build the retrieval index

Two options (the serve script supports both):

- **Keyword (zero deps):** TF-IDF / token overlap over `data/scrubbed.jsonl`.
  Good enough for many users, instant, fully local index.
- **Semantic (recommended):** embed each of the user's messages with a local
  `sentence-transformers` model; cosine-similarity search. Better recall on
  paraphrases. Local — embeddings never leave the machine; only the *retrieved
  text* goes to Claude at query time.

Index the user's own messages (and optionally a turn of surrounding context so
retrieved snippets read naturally). Store alongside `data/`.

## Assemble the request (what mirror_chat.py does)

```
system  = persona/style_card.md
         + "Below are things YOU have actually said. Use them to answer in your
            real voice and with your real views. If they don't cover it, reason
            as yourself; don't invent facts."
         + <top-k retrieved past messages for this query>
messages = <recent conversation> + <user's new message>
model    = claude-opus-4-8        # or sonnet-4-6 / haiku-4-5 for cost
thinking = {"type": "adaptive"}   # lets Opus reason in-character on hard asks
```

Use the project's `claude-api` skill conventions: default `claude-opus-4-8`,
adaptive thinking, stream long replies. Keep the style card first in `system`
(stable prefix → prompt caching), put the volatile retrieved snippets after it.

## Tuning knobs

- **k (retrieved snippets):** 4–8. Too many dilutes the voice and costs tokens.
- **Retrieval scope:** restrict to one surface (only texts, or only email) when
  the Mirror targets that surface — keeps the register consistent.
- **Style-card strength:** if replies drift toward "helpful assistant," make the
  NEVER section sharper and add 2–3 few-shot exemplars (real (prompt → your
  reply) pairs) into the system prompt.
- **Model:** Opus 4.8 for thought-partner/knowledge; Haiku 4.5 for cheap
  autoreply.

## Privacy

- The index and embeddings are **local**.
- At inference, only the **style card + the few retrieved snippets + the current
  conversation** go to Anthropic — not the whole corpus. Tell the user this.
- Scrub the corpus first if it contains secrets you don't want in any prompt.

## Then

Go to `mirror-evaluation` (holdout style score + side-by-sides), then
`mirror-deploy` (`scripts/serve/mirror_chat.py --path A`). You can have a working
Mirror in minutes here.
