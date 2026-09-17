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
| `llama3.2` (3B) | 81s | 20 | yes | Best of the set. The default. |
| `phi4-mini:3.8b` | 142s | 18 | yes | Writes compound questions. |
| `qwen2.5-coder:7b` | ~26s/call | — | yes | Fine, slower, no quality gain. |
| `qwen3.5:4b` | 280s+/call | — | only while thinking | Impractical. |
| `qwen3.5:9b` | 280s+/call | — | only while thinking | Impractical. |
| `deepseek-r1:8b` | — | — | — | Reasoning model; same problem. |

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

## Reproducing

```console
$ python scripts/compare_models.py --models <model> [<model> ...] --show-cards
```

The script counts what can be counted — time, schema failures, yes/no
questions, compound questions, paragraph-length answers — and prints the cards
so you can judge the rest yourself.
