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

## Reproducing

```console
$ python scripts/compare_models.py --models <model> [<model> ...] --show-cards
$ python scripts/compare_models.py --models llama3.2 --style cloze --show-cards
```

The script counts what can be counted — time, schema failures, yes/no
questions, compound questions, paragraph-length answers — and prints the cards
so you can judge the rest yourself.
