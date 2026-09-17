# notetaker

Feed it your notes, get back an Anki deck. Everything runs locally through
[Ollama](https://ollama.com), so your notes never leave your machine.

The idea is simple: making flashcards by hand is the most tedious part of
studying, and it's mostly mechanical. A model that can read a paragraph can
usually pull the handful of facts worth remembering out of it. This wraps that
into something you can point at a file.

> **Status:** in progress. The pipeline works end to end and writes importable
> TSV, but the Ollama backend isn't wired up yet — right now the only backend
> is the offline `fake` one described below. Anki `.apkg` packages are next.

## Try it without downloading a model

```console
$ pip install -e .
$ notetaker cards examples/sample_notes.md

  reading   examples/sample_notes.md  (4 sections, 1568 chars)
  model     fake
  generated 11 cards

  out/sample_notes.tsv   File > Import in Anki
```

The `fake` backend isn't a model at all — it's a sentence matcher that picks out
`X is Y` and `X: Y` definitions. It exists so the test suite can run in CI
without Ollama, and so you can see the shape of the output before committing to
a download. It produces cards like:

| Question | Answer | Tags |
| --- | --- | --- |
| What is Osmosis? | the diffusion of water across a selectively permeable membrane, from an area of lower solute concentration to an area of higher solute concentration | `Cell_Biology::Transport` |
| What is Glycolysis? | the breakdown of one glucose molecule into two molecules of pyruvate, taking place in the cytoplasm | `Cellular_Respiration::Glycolysis` |

Your markdown headings become hierarchical Anki tags, so a deck stays organized
the way your notes already were.

## Where it's going

```console
$ notetaker cards notes/bio-ch3.md --llm ollama --model qwen3.5:9b --deck "Bio::Ch3"
```

That will produce two files. The `.apkg` is a real Anki deck package — double-click
it and Anki takes care of the rest, keeping the note type and tags intact. The
`.tsv` is there for when you'd rather look over the cards in a spreadsheet and
edit a few before importing.

Cards will get stable IDs derived from their question text, so if you revise your
notes and re-run, Anki updates the existing cards instead of giving you a second
copy of everything.

Also planned: cloze cards, PDF input, and a small web UI for people who'd rather
drag a file onto a page.

## Usage

```
notetaker cards NOTES [OPTIONS]

  --out, -o PATH     Directory to write into          [default: out]
  --llm TEXT         Backend: 'fake' or 'ollama'      [default: fake]
  --max-cards INT    Cards per section                [default: 8]
  --chunk-chars INT  Characters of notes per call     [default: 4000]
  --tag TEXT         Extra tag; repeatable
```

Notes are split at heading boundaries, and any section too large for the model's
context gets split again at paragraph boundaries. Duplicate questions are dropped
across the whole document, and a section the model mishandles is skipped and
reported rather than taking the run down with it.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) with an instruct model pulled — once that backend lands

Model choice matters more than you'd expect. Anything around 8-9B does a decent
job; smaller models tend to produce cards that restate a whole paragraph instead
of isolating one fact. `qwen3.5:9b` is a reasonable default. Reasoning models
that emit `<think>` blocks, such as `deepseek-r1`, are a poor fit for structured
output and aren't recommended here.

## Development

```console
$ pip install -e ".[dev]"
$ pytest
$ ruff check . && ruff format --check .
```

The whole suite runs offline. `LLMClient` is a small protocol, so the tests
drive the pipeline with stubs rather than a live model.

## License

MIT
