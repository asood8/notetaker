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
notetaker cards NOTES [OPTIONS]        # NOTES is .md, .txt or .pdf

  --out, -o PATH     Directory to write into          [default: out]
  --llm TEXT         Backend: 'ollama' or 'fake'      [default: ollama]
  --model TEXT       Ollama model tag                 [default: llama3.2]
  --style TEXT       Card style: 'basic' or 'cloze'   [default: basic]
  --max-cards INT    Cards per section                [default: 8]
  --chunk-chars INT  Characters of notes per call     [default: 4000]
  --num-ctx INT      Context window, in tokens        [default: 8192]
  --timeout FLOAT    Seconds to wait per call         [default: 180]
  --deck TEXT        Anki deck name                   [default: file name]
  --tag TEXT         Extra tag; repeatable
  --limit INT        Only use the first N sections
```

### Looking before you leap

A long set of notes takes a while, so it is worth seeing what you are in for:

```console
$ notetaker inspect lectures/neuro301.md

  reading   lectures/neuro301.md  (9 sections, 11,595 chars)

  [  1] Neuroscience_301                                 54 chars
  [  2] Neuroscience_301::Resting_Potential           1,678 chars
  [  3] Neuroscience_301::Action_Potentials             537 chars
  ...

  largest   2,492 chars
  estimate  roughly 2 min to 5 min to generate
```

`inspect` never calls a model. It shows how the file will be split, what each
section will be tagged, and warns about sections with no heading above them,
whose cards will carry no tags of their own. If the split looks wrong, adjust
`--chunk-chars` before spending twenty minutes on a run.

For a first pass at something long, `--limit 3` generates from the first three
sections only, so you can look at the cards before committing to the rest.

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
| `llama3.2` (3B) | ~13s | yes | Fast, good cards. The default. |
| `llama3.1:8b` | ~40s | yes | Better coverage; writes list answers. |
| `phi4-mini:3.8b` | ~20s | yes | Fine, but writes compound questions. |
| `qwen2.5-coder:7b` | ~26s | yes | Solid, slower for no real gain. |
| `qwen3.5:4b` / `qwen3.5:9b` | 280s+ | see below | Impractical here. |
| `deepseek-r1:8b` | — | — | Reasoning model; same problem. |

Full measurements, including the cards each model produced, are in
[docs/model-notes.md](docs/model-notes.md).

Bigger is not better for this task. Pulling facts out of a paragraph is not a
reasoning problem, and a 3B instruct model does it well. Going from 3B to 8B
bought slightly better coverage and cost 44% more time — a wash. If your
machine is quick enough not to care, `--model llama3.1:8b` is a fair choice.

Reasoning models are the trap. The qwen3.5 family spends minutes thinking before
answering — over four minutes per section on an already-loaded model, which
would make a normal set of lecture notes take an hour. The obvious fix, passing
`think: false`, backfires: those models then stop honoring the JSON schema
entirely and return markdown. Thinking levels don't help either — `think: "low"`
still blew past a 400-second timeout. So `notetaker` never sends `think`, and
simply recommends against reasoning models. If one times out, the error message
says so.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running, with a model pulled:

```console
$ ollama pull llama3.2
```

Set `OLLAMA_HOST` if your server isn't on `localhost:11434`.

## How it works

```
notes.md ─▶ chunk ─▶ [model, schema] ─▶ validate ─▶ filter ─▶ dedup ─┬─▶ .apkg
           (headings)     (Ollama)      (pydantic)  (quality)       └─▶ .tsv
```

Requests use Ollama's `format` parameter with a JSON schema generated from the
pydantic model, so the output is constrained during decoding rather than parsed
hopefully afterwards. `num_ctx` is always set explicitly — the default is small
and truncates silently, which looks like the model ignoring your notes rather
than like a setting you need to change.

## Development

```console
$ pip install -e ".[dev,web,ocr]"
$ pytest                  # offline, no Ollama needed
$ pytest -m integration   # hits a real local model
$ ruff check . && ruff format --check .
```

To compare models yourself:

```console
$ python scripts/compare_models.py --models llama3.2 phi4-mini:3.8b --show-cards
```

`LLMClient` is a small protocol, so the tests drive the whole pipeline with
stubs and a mocked HTTP transport. Only the tests marked `integration` need
Ollama, and CI never runs those.

Cards carry a GUID derived from their question text, and the deck gets an ID
derived from its name. That means re-running after editing your notes updates
the cards already in Anki rather than leaving you with two near-identical copies
of your deck. Changing a question creates a new card; changing only the answer
updates the existing one.

## A page instead of a terminal

```console
$ pip install "notetaker[web]"
$ notetaker serve

  notetaker is at http://127.0.0.1:8000
```

Drop a file on the page, pick a style and a model, and watch it work. The wait
is the interesting part of this interface: every section of your notes is
listed as soon as the file is read, and each one fills in with its tag and card
count as the model finishes with it. A progress bar would tell you less.

The server binds to localhost, writes only to a temporary directory it owns,
and deletes that directory when it stops. The page itself loads no fonts,
scripts or styles from anywhere — the point of this tool is that your notes
stay on your machine, and a stylesheet fetched from a CDN would quietly leak
the fact that you are using it.

## PDF notes

```console
$ notetaker cards lectures/week3.pdf --deck "Bio::Week 3"
```

PDFs have no headings in the markup sense, but they usually have them visually:
a short line on its own above a paragraph. Those are recovered and used for
tags, the same as markdown headings, so a slide deck or lecture handout still
comes out organized. What is not recovered is nesting — every heading found in
a PDF is treated as a sibling, because guessing at levels from extracted text
gets it wrong more often than not.

Text is extracted in layout mode, which keeps the blank lines between
paragraphs; without it a whole page collapses into one run-on block and the
model gets fragments instead of sentences.

### Scans

A PDF that is photographs of pages has no text to extract. Passing `--ocr`
renders each page and reads it with a local vision model, so scans stay as
private as everything else:

```console
$ notetaker cards lectures/scan.pdf --ocr
```

It is off by default for two reasons, and both are worth knowing before you
rely on it.

**It needs a GPU.** A vision model has to fit in video memory to be practical.
On the machine this was built on it did not, and Ollama loaded it into system
memory instead — a single page then took over four minutes, and dropping the
resolution from 150 DPI to 72 changed nothing at all, because the bottleneck
was never the image size. Run `ollama ps` while it works: if `size_vram` is 0,
the model is on the CPU and you should expect minutes per page.

**A vision model can be confidently wrong.** Traditional OCR produces obvious
garbage when it fails. A vision model produces a plausible wrong word instead,
and a flashcard built on a misreading teaches you the mistake. Read what comes
out before you study it.

Scans are handled by the CLI only — the web page does not offer it, because a
feature that can silently take twenty minutes does not belong behind a button
that looks instant.

## Cloze cards

```console
$ notetaker cards notes/bio-ch3.md --style cloze
```

Instead of question-and-answer pairs you get sentences with the key term
hidden, which Anki turns into fill-in-the-blank cards:

> Glycolysis is the breakdown of one glucose molecule into two molecules of
> {{c1::pyruvate}}, taking place in the cytoplasm.

Basic cards are still the default. Cloze asks more of the model, and small ones
produce a fair number of unusable sentences — hiding a word that is printed
again in the same sentence, or stopping mid-clause. Those are filtered out, but
the filter throws away real work, so expect fewer cards per section than you get
with `--style basic`. Cloze suits notes already written as complete sentences.

## Card quality

Two things are dropped automatically. Cards that duplicate an earlier one are
removed, including inverted pairs — asking "Where are peripheral proteins
attached?" and "What is attached to the surface?" is one fact asked twice.
Cards that can be answered by guessing are removed too: yes/no questions,
questions asking two things at once, and paragraph-length answers.

That last one is enforced in code rather than in the prompt, because asking
politely didn't work. `llama3.2` produced four yes/no cards from the sample
notes despite the prompt explicitly forbidding them, with an example. Small
models are bad at negative instructions. With the filter, the same run produces
zero.

## Planned

- Scans in the web UI, once they are fast enough to be worth waiting for

## License

MIT
