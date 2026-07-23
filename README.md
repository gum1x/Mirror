# Mirror

[![CI](https://github.com/gum1x/Mirror/actions/workflows/ci.yml/badge.svg)](https://github.com/gum1x/Mirror/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A framework that trains an AI to speak, answer, and "think" like you.

Mirror pulls your real conversations out of the apps you already use: iMessage, WhatsApp, Telegram, Gmail, Slack, Discord, Instagram, SMS. It works out how you actually write, down to message length, punctuation, emoji, slang, and the way you explain things. Then it picks a training method that fits your data and your privacy comfort, trains, and scores the result on conversations it never saw. What you end up with answers the way you would, grounded in things you've actually said. Not a generic chatbot wearing your name.

Nine skills, twenty-two scripts, and a core pipeline that runs on the Python standard library alone.

> Built with AI assistance. Everything has been reviewed and tested. Nevertheless, Please read the code before running it on your own data, and treat the privacy notes as guidance, not as a guarantee.


## How it works

```
/mirror
   │
   ▼
interview ........ goals, use case, privacy, budget
   │
   ▼
connectors ....... imessage, whatsapp, telegram, gmail, slack, discord, instagram, sms
   │               each app's own export in, one unified JSONL out
   ▼
data-formatting .. normalize, scrub PII (locally), build the dataset
   │
   ▼
persona .......... your voice, distilled into a style card
   │
   ▼
model-selection .. Path A: Claude persona + RAG
   │               Path B: OpenAI fine-tune (SFT, DPO)
   ▼               Path C: local LoRA (Llama / Qwen)
training ──▶ evaluation ──▶ deploy
                 ▲             │
                 └── iterate ──┘
```

## Privacy and safety

- Local by default. parsing, scrubbing, and dataset building all happen on your machine. nothing leaves until you pick a path that needs it.
- You're told before data leaves. Path A sends retrieved snippets plus your style card to Anthropic, Path B uploads your dataset to OpenAI, Path C sends nothing. Mirror says which one applies and asks first.
- PII scrubbing runs before any upload (`scripts/format/pii_scrub.py`): emails, phone numbers, cards, SSNs, IPs, basic street addresses, and any custom terms you add. It is regex-based and best-effort, so look at the output and add your own terms for names and anything unusual.
- Consent matters. Group chats contain other people's words. Mirror only trains on your messages; everyone else is context. Don't point it at a real conversation to deceive someone.
- Only your own accounts. Export from accounts you own and control.


## Prior art

Cloning yourself from chat history is well-trodden ground, and Mirror leans on a lot of work that came before it:

| Project | Source(s) | Method | Eval | Notes |
|---------|-----------|--------|------|-------|
| [WeClone](https://github.com/xming521/WeClone) (~17k stars) | WeChat, Telegram | LoRA SFT (LLaMA-Factory) | demo UI + fixed question file | The popular one; also scrubs PII with Presidio |
| [ai-clone-whatsapp](https://github.com/kinggongzilla/ai-clone-whatsapp) | WhatsApp | QLoRA (ShareGPT) | none | Clean single-source reference |
| [WhatsApp-Llama](https://github.com/Ads97/WhatsApp-Llama) | WhatsApp | QLoRA | informal Turing test (caught 2/20) | The "Show HN" build |
| [doppelganger](https://github.com/furiousteabag/doppelganger) | Telegram | LoRA | none | 10-min session windowing |
| [imessage-lm](https://github.com/Dynosol/imessage-lm) | iMessage | LoRA (Unsloth) | none | MIT |
| [lad-gpt](https://github.com/bernhard-pfann/lad-gpt) | WhatsApp | transformer from scratch | informal | nanoGPT-style |
| [Izzy Miller, "robo-boys"](https://www.izzy.co/blogs/robo-boys.html) | iMessage (488k msgs) | Alpaca full fine-tune | informal | 4-hr session windowing |
| [Edward Donner, 240k msgs](https://edwarddonner.com/2024/01/02/fine-tuning-an-llm-on-240k-text-messages/) | iMessage + WhatsApp | QLoRA | informal | writes up the "mundane loop" failure mode |

Most of these build on [Unsloth](https://github.com/unslothai/unsloth), [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory), or [Axolotl](https://github.com/axolotl-ai-cloud/axolotl).

Where Mirror differs: it reads from several apps into one schema instead of a single source, it picks a training method from your answers instead of defaulting to a 7B LoRA, and it reports a style match score on a held out set instead of relying on an eyeball check. The trade off is more moving parts. If you only care about one source and one model, one of the projects above is probably the simpler choice.

Things it borrows from the field and the wider community: time gap session windowing (like doppelganger and Izzy Miller), keeping train and eval separate, dataset cards for provenance, seeded splits, merging consecutive messages into one turn, and ShareGPT / OpenAI-chat / ChatML / DPO output formats. The reasoning behind the defaults is in `skills/mirror-model-selection/references`.


## License

MIT. See [LICENSE](LICENSE).
