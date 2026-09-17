# notetaker

Feed it your notes, get back Anki flashcards. Everything runs locally through
[Ollama](https://ollama.com), so your notes never leave your machine.

The idea is simple: making flashcards by hand is the most tedious part of
studying, and it's mostly mechanical. A model that can read a paragraph can
usually pull the handful of facts worth remembering out of it. This wraps that
into something you can point at a file.

> **Status:** working, but young. Generation and both export formats are done.
> Cloze cards and better prompts are next.

## Usage

```console
$ notetaker cards examples/sample_notes.md --model llama3.2

  reading   examples/sample_notes.md  (4 sections, 1568 chars)
  model     ollama/llama3.2

  [1/4] Cell_Biology::The_Cell_Membrane  ->  8 cards
  [2/4] Cell_Biology::Transport  ->  5 cards
  [3/4] Cellular_Respiration::Glycolysis  ->  4 cards
  [4/4] Cellular_Respiration::The_Krebs_Cycle  ->  2 cards

  generated 19 cards  (2 duplicate dropped)

  out/sample_notes.apkg   double-click to import
  out/sample_notes.tsv    or use File > Import
```

That run took about a minute. You get two files. The `.apkg` is a real Anki
deck package — double-click it and Anki handles the rest, keeping the note type
and tags intact. The `.tsv` is there for when you'd rather look the cards over
in a spreadsheet and fix a few before importing.

A sample of what came out:

| Question | Answer | Tags |
| --- | --- | --- |
| Where does glycolysis take place? | The cytoplasm | `Cellular_Respiration::Glycolysis` |
| What molecule helps keep the membrane fluid at low temperatures? | cholesterol | `Cell_Biology::The_Cell_Membrane` |
| How many sodium ions are moved out for every two potassium ions brought in by the sodium-potassium pump? | Three | `Cell_Biology::Transport` |

Your markdown headings become hierarchical Anki tags, so a deck stays organized
the way your notes already were.

```
notetaker cards NOTES [OPTIONS]

  --out, -o PATH     Directory to write into          [default: out]
  --llm TEXT         Backend: 'ollama' or 'fake'      [default: ollama]
  --model TEXT       Ollama model tag                 [default: llama3.2]
  --max-cards INT    Cards per section                [default: 8]
  --chunk-chars INT  Characters of notes per call     [default: 4000]
  --num-ctx INT      Context window, in tokens        [default: 8192]
  --timeout FLOAT    Seconds to wait per call         [default: 180]
  --deck TEXT        Anki deck name                   [default: file name]
  --tag TEXT         Extra tag; repeatable
```

Notes are split at heading boundaries, and any section too large for the
context window is split again at paragraph boundaries. Duplicate questions are
dropped across the whole document, and a section the model mishandles is
skipped and reported rather than taking the run down with it.

## Trying it without downloading a model

```console
$ notetaker cards examples/sample_notes.md --llm fake
```

The `fake` backend isn't a model at all — it's a sentence matcher that picks out
`X is Y` and `X: Y` definitions. It exists so the test suite can run in CI
without Ollama, and so you can see the shape of the output before committing to
a multi-gigabyte download.

## Choosing a model

Model choice matters more here than you'd expect, and not in the direction you'd
guess. Rough numbers from one machine, one short prompt, so treat them as a
starting point rather than a benchmark:

| Model | Per call | Schema honored | Notes |
| --- | --- | --- | --- |
| `llama3.2` (3B) | ~13s | yes | Best cards of the set. The default. |
| `phi4-mini:3.8b` | ~20s | yes | Fine, but writes compound questions. |
| `qwen2.5-coder:7b` | ~26s | yes | Solid, slower for no real gain. |
| `qwen3.5:4b` / `qwen3.5:9b` | 280s+ | see below | Impractical here. |
| `deepseek-r1:8b` | — | — | Reasoning model; same problem. |

Bigger is not better for this task. Pulling facts out of a paragraph is not a
reasoning problem, and a 3B instruct model does it well.

Reasoning models are the trap. The qwen3.5 family spends minutes thinking before
answering — over four minutes per section on an already-loaded model, which
would make a normal set of lecture notes take an hour. The obvious fix, passing
`think: false`, backfires: those models then stop honoring the JSON schema
entirely and return markdown. So `notetaker` never sends `think`, and simply
recommends against reasoning models. If one times out, the error message says so.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running, with a model pulled:

```console
$ ollama pull llama3.2
```

Set `OLLAMA_HOST` if your server isn't on `localhost:11434`.

## How it works

```
notes.md ──▶ chunk ──▶ [model, JSON schema] ──▶ validate ──▶ dedup ──┬─▶ .apkg
            (headings)      (Ollama)            (pydantic)          └─▶ .tsv
```

Requests use Ollama's `format` parameter with a JSON schema generated from the
pydantic model, so the output is constrained during decoding rather than parsed
hopefully afterwards. `num_ctx` is always set explicitly — the default is small
and truncates silently, which looks like the model ignoring your notes rather
than like a setting you need to change.

## Development

```console
$ pip install -e ".[dev]"
$ pytest                  # offline, no Ollama needed
$ pytest -m integration   # hits a real local model
$ ruff check . && ruff format --check .
```

`LLMClient` is a small protocol, so the tests drive the whole pipeline with
stubs and a mocked HTTP transport. Only the tests marked `integration` need
Ollama, and CI never runs those.

Cards carry a GUID derived from their question text, and the deck gets an ID
derived from its name. That means re-running after editing your notes updates
the cards already in Anki rather than leaving you with two near-identical copies
of your deck. Changing a question creates a new card; changing only the answer
updates the existing one.

## Planned

- Cloze cards
- Better prompts — the current ones still allow the occasional yes/no card
- PDF input
- A small web UI

## License

MIT
