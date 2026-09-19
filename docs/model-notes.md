# Model notes

Measurements, not opinions. Everything here came from
`scripts/compare_models.py` run against `examples/sample_notes.md` (four
sections, ~1.6k characters) on one Windows desktop. Times will differ on your
hardware; the schema and quality columns should not.

```console
$ python scripts/compare_models.py --models llama3.2 phi4-mini:3.8b --show-cards
```

## Results

| Model | Time | Cards | Honors `format` schema | Notes |
| --- | --- | --- | --- | --- |
| `llama3.2` (3B) | 81-112s | 20 | yes | The default. |
| `llama3.1:8b` | 161s | 21 | yes | Better coverage, writes list answers. |
| `phi4-mini:3.8b` | 142s | 18 | yes | Writes compound questions. |
| `qwen2.5-coder:7b` | ~26s/call | — | yes | Fine, slower, no quality gain. |
| `qwen3.5:4b` | 280s+/call | — | only while thinking | Impractical. |
| `qwen3.5:9b` | 280s+/call | — | only while thinking | Impractical. |
| `deepseek-r1:8b` | — | — | — | Reasoning model; same problem. |

## 3B against 8B

The automated counters cannot separate these two: both scored zero yes/no,
zero compound, zero wordy. The difference only shows up reading the cards.

`llama3.1:8b` covers the material more completely. It picked up the location
of the Krebs cycle and the fact that active transport needs energy "usually
supplied by ATP", both of which the 3B model skipped.

But it also writes list answers, which is exactly what the prompt forbids:

> What are the products of one turn of the Krebs cycle?
> → Three NADH, one FADH2, and one ATP

`llama3.2` split that same fact into three separate cards, which is what a
flashcard should be. It has its own misses -- "How does the cell membrane move
laterally? → free to move" is close to meaningless -- and `llama3.1:8b`
produced one clumsy question ("What is osmosis the diffusion of across a
membrane?").

Call it a wash on quality, at 44% more time. `llama3.2` stays the default
because it is fast enough to iterate with and runs on modest hardware. On a
machine where 161 seconds is not a problem, `llama3.1:8b` is a reasonable
choice for its better coverage:

```console
$ notetaker cards notes.md --model llama3.1:8b
```

What is *not* worth doing is reaching further up the size ladder.

## Bigger is not better here

Turning a paragraph into flashcards is extraction, not reasoning. A 3B instruct
model does it about as well as a 7B one and several times faster. The clear
losers were the largest models tested, for a reason that has nothing to do with
their size.

## The reasoning-model trap

`qwen3.5:9b` spends minutes reasoning before answering. On an already-loaded
model, one four-sentence section took **281 seconds**. A normal set of lecture
notes would take the better part of an hour.

The obvious fix backfires. Passing `think: false` cuts that to ~33 seconds, but
the model then **stops honoring the `format` JSON schema entirely** and returns
markdown prose instead:

```
**Card 1**
**Question:** What is the primary structural composition of the cell membrane?
```

Thinking levels do not rescue it either — `think: "low"` still exceeded a
400-second timeout on `qwen3.5:9b`.

So `notetaker` never sends `think` at all, and recommends plain instruct
models. When a call does time out, the error message names this specifically
rather than saying "request timed out".

## Prompting alone does not enforce card quality

The system prompt asks, explicitly and with an example, for no yes/no
questions. `llama3.2` produced four of them anyway in a four-section document:

> Is the cell membrane a fixed structure? → no
> Does glycolysis require oxygen? → No

Small models are weak at negative instructions. The rule is now enforced in
code as well, in `notetaker/quality.py`, which is deterministic and unit-tested.
With the filter in place the same run produced 20 cards and zero flagged ones.

The prompt still asks, because it is cheaper to have the model not generate a
bad card than to generate and discard it. But the prompt is not what guarantees
it.

## An optional schema field is an escape hatch

`llama3.1:8b` answered the cloze prompt with a bare `{}`. The batch model gave
`cards` a default, so that validated cleanly as "zero cards" and the run
reported success having produced nothing. Silent, and the worst kind of bug.

Making `cards` a required field was supposed to turn that into a counted
invalid response. It did something better: the same model went from **0 cards
to 11**. The field is required in the JSON schema now, and Ollama constrains
decoding against that schema, so `{}` is no longer a reachable output. The
model had been taking the cheapest path the grammar allowed.

The lesson generalizes. Anything optional in a schema handed to a
grammar-constrained model is a way out that some model will eventually take.

## Cloze is harder than basic

Cloze quality is visibly worse than question-and-answer at this model size.
Real output from `llama3.2` before the cloze filters existed:

> The Krebs cycle is a series of reactions in the {{c1::mitochondrial matrix}} that

> Osmosis: the movement of water ... involving {{c1::osmosis}}

The first stops mid-clause. The second hides a word printed in plain sight two
inches to the left. Both are now rejected by rules in `quality.py`, along with
deletions that swallow the whole sentence. On the sample notes those filters
drop five to nine cards per run, which is a lot -- but the cards that survive
are ones worth reviewing.

Basic cards remain the better default. Cloze is worth it when your notes are
already written as complete, factual sentences.

## PDFs need layout-mode extraction

`pypdf`'s default extraction drops the blank lines between paragraphs. A whole
page comes back as one unbroken block, the chunker can no longer see paragraph
boundaries, and the model is handed run-on fragments. Passing
`extraction_mode="layout"` keeps them, and is the difference between a PDF
producing one shapeless chunk and producing properly tagged sections.

The same work surfaced a chunker bug worth recording. Heading depth was tracked
by list index, which assumes the document's top heading is `#`. Text recovered
from a PDF has no `#` at all, so every sibling heading nested under the first
one seen and whole sections were mislabelled. Heading levels are now tracked
explicitly.

## Vision models need the GPU, and nothing else helps

`--ocr` reads scanned PDFs with a local vision model. On the machine used for
every other measurement here, `qwen2.5vl:3b` could not finish a single page:

| Render | Image | Result |
| --- | --- | --- |
| 72 DPI | 596x842 | timed out at 240s |
| 110 DPI | 910x1287 | timed out at 240s |
| 150 DPI | 1241x1754 | timed out at 240s |

The flat result is the interesting part. Shrinking the image to a fifth of its
area changed nothing, which rules out image size as the cause. `ollama ps`
gave the real answer:

```json
{"name": "qwen2.5vl:3b", "size": 10794189504, "size_vram": 0}
```

`size_vram: 0` — the model was loaded entirely into system memory. The text
models used elsewhere in this project are small enough for the GPU and run in
seconds; the vision model is not, and falls back to the CPU, where it is
effectively unusable.

So the OCR code path is tested offline in full, but a successful transcription
has never been observed on this hardware. It should be quick on a machine
where the model fits in video memory. Treat that as untested rather than
proven, and check `ollama ps` before blaming the tool.

An image size cap is applied anyway -- pages are scaled to 1400px on the long
edge before being sent -- because a model gains nothing from detail beyond what
it can tokenize. It is a sensible default, not the fix for this.

## What real lecture notes broke

Everything above was measured on a tidy sample file written for the purpose.
The first real input -- a 588-page compilation of medical school lecture
slides -- broke four things that the sample never could.

**A footer became a heading, 93 times.** Every slide carried the lecturer's
name. A short unpunctuated line with prose beneath it is exactly what the
heading detector looks for, so the deck split at every slide boundary and
those sections were tagged `Dr_Sollars`. Removing lines that repeat across
pages fixed it, but the first attempt still missed: the threshold was a share
of the document, 30%, and the file turned out to be several courses bound
together, so that lecturer's footer covered only 93 of 588 pages -- 16%, well
under the bar. The count that matters is absolute. A line appearing verbatim
on eight separate pages is furniture whatever fraction that is.

**Sections of one and two characters.** A slide title became the heading and a
stray character was all that remained beneath it. Those cost a model call and
return nothing.

**Cards that were not cards.** A near-empty section produced "What is the focus
of this handout? -> Unknown", twice. Another slide produced "Which movement of
the 1900s was based on eugenics? -> Eugenics", where the answer sits in the
question -- a rule the cloze path had from the start and the basic path had
simply never been given. A references slide produced three citation cards.

**Text silently missing.** 16 pages contain rotated text that pypdf cannot
extract. It says so, once per page, as library noise that scrolls past. That is
now collected and reported once, in the tool's own words, because it means
cards are missing content.

Together these took the document from 570 sections to 497, and every remaining
tag names real subject matter.

### The one no filter can catch -- and the one thing that does

From a sparse overview slide, `llama3.2` produced:

> Which sex chromosome determines male characteristics? -> X

It is the Y chromosome. The slide had little on it, so the model filled the gap
from its own knowledge despite being told to use only what the notes state. The
card is well formed and plausible, so no rule about its shape will ever reject
it.

What does reject it is a different question. Not "is this true" -- asking that
sends the model back to the same memory that invented the card -- but "does
this passage say this", with the words quoted. Reading the card back against
its own section, `llama3.2` rejects it.

Run against that slide, the check rejected two of three cards:

| Card | Verdict |
| --- | --- |
| Which sex chromosome determines male characteristics? -> X | rejected |
| What is the role of genetics in medicine? -> ... | rejected |
| What is pharmacogenomics? -> ... | kept |

The second rejection is also right, and explains the whole section: that
passage is the **table of contents**. "Lecture 1 Introduction to Human
Genetics 1, Lecture 2 Human Chromosome Structure 11" and so on. There is no
material there to make cards from, which is exactly why the model invented
some.

The check is `--check`, and it is off by default because it costs about 70%
more time: 170 seconds against 282 for the same three sections. It rejected 7
of 15 cards there, which is a high rate, but those sections include the table
of contents -- a passage that supports almost nothing.

A note on measuring that. The first attempt put the cost at 7x, because the
242-test suite was running on the same machine at the time, and two sections
timed out under the load. Both numbers were artefacts of the measurement. Run
timings on an idle machine or do not report them. It fails open: an unreachable or incoherent checker
keeps every card, because a broken check must never be able to empty a deck.
It verifies fidelity to your notes, not truth -- notes that are wrong will
produce cards that pass.

## Reproducing

```console
$ python scripts/compare_models.py --models <model> [<model> ...] --show-cards
$ python scripts/compare_models.py --models llama3.2 --style cloze --show-cards
```

The script counts what can be counted — time, schema failures, yes/no
questions, compound questions, paragraph-length answers — and prints the cards
so you can judge the rest yourself.
