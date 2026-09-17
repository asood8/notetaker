# notetaker

Feed it your notes, get back an Anki deck. Everything runs locally through
[Ollama](https://ollama.com), so your notes never leave your machine.

The idea is simple: making flashcards by hand is the most tedious part of
studying, and it's mostly mechanical. A model that can read a paragraph can
usually pull the handful of facts worth remembering out of it. This wraps that
into something you can point at a file.

> **Status:** early. The skeleton and CI are in place; the generation pipeline
> is being built out. See the [issues](https://github.com/asood8/notetaker/issues)
> for what's landed and what hasn't.

## How it will work

```console
$ notetaker cards notes/bio-ch3.md --deck "Bio::Ch3"

  reading   notes/bio-ch3.md  (12 sections, ~4.2k tokens)
  model     qwen3.5:9b
  generated 38 cards  (4 duplicates dropped)

  out/bio-ch3.apkg   double-click to import
  out/bio-ch3.tsv    or use File > Import
```

You get two files. The `.apkg` is a real Anki deck package — double-click it and
Anki takes care of the rest, keeping the note type and tags intact. The `.tsv`
is there for when you'd rather look over the cards in a spreadsheet and edit a
few before importing.

Cards get stable IDs derived from their question text, so if you revise your
notes and re-run, Anki updates the existing cards instead of giving you a second
copy of everything.

## Planned

- Markdown and plain text input, with headings becoming Anki tags
- Basic and cloze card types
- PDF input
- A small web UI for people who'd rather drag a file onto a page

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com), with at least one instruct model pulled

Model choice matters more than you'd expect. Anything around 8-9B does a decent
job; smaller models tend to produce cards that restate whole paragraphs instead
of isolating one fact. `qwen3.5:9b` is a reasonable default.

## License

MIT
