from notetaker.chunking import Chunk, chunk_markdown

NESTED = """\
# Biology

Intro text.

## Cell Cycle

Mitosis is division of the nucleus.

### Prophase

Chromosomes condense.

# Chemistry

Atoms bond.
"""


def test_heading_path_follows_nesting() -> None:
    chunks = chunk_markdown(NESTED)
    paths = [chunk.heading_path for chunk in chunks]
    assert paths == [
        ("Biology",),
        ("Biology", "Cell Cycle"),
        ("Biology", "Cell Cycle", "Prophase"),
        ("Chemistry",),
    ]


def test_a_deeper_heading_does_not_leak_into_the_next_top_level_section() -> None:
    chunks = chunk_markdown(NESTED)
    assert chunks[-1].heading_path == ("Chemistry",)


def test_tag_is_a_hierarchical_anki_tag() -> None:
    chunk = Chunk(text="x", heading_path=("Cell Biology", "The Cell Membrane!"))
    assert chunk.tag == "Cell_Biology::The_Cell_Membrane"


def test_headings_inside_a_code_fence_are_not_treated_as_headings() -> None:
    text = "# Real\n\n```python\n# not a heading\nx = 1\n```\n\nmore text\n"
    chunks = chunk_markdown(text)
    assert [chunk.heading_path for chunk in chunks] == [("Real",)]
    assert "# not a heading" in chunks[0].text


def test_sections_without_a_heading_get_an_empty_path() -> None:
    chunks = chunk_markdown("Loose text with no heading.\n")
    assert chunks[0].heading_path == ()
    assert chunks[0].tag == ""


def test_empty_sections_are_dropped() -> None:
    chunks = chunk_markdown("# A\n\n# B\n\nMitosis divides the nucleus.\n")
    assert len(chunks) == 1
    assert chunks[0].heading_path == ("B",)


def test_sections_too_small_to_hold_a_fact_are_dropped() -> None:
    # Slide decks produce these: the title becomes the heading, and a stray
    # character is all that is left underneath it.
    notes = "## Telomeres\n\n.\n\n## Centromeres\n\nThey join sister chromatids.\n"
    assert [chunk.heading_path for chunk in chunk_markdown(notes)] == [("Centromeres",)]


def test_a_terse_but_real_fact_is_kept() -> None:
    assert len(chunk_markdown("## Bonding\n\nAtoms bond.\n")) == 1


def test_oversized_sections_are_split_on_paragraph_boundaries() -> None:
    para = "word " * 40
    text = "# Big\n\n" + "\n\n".join([para.strip()] * 6) + "\n"
    chunks = chunk_markdown(text, max_chars=400)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 400 for chunk in chunks)
    assert all(chunk.heading_path == ("Big",) for chunk in chunks)


def test_a_single_huge_paragraph_is_still_split() -> None:
    text = "# Big\n\n" + ("Sentence number one here. " * 60) + "\n"
    chunks = chunk_markdown(text, max_chars=300)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 300 for chunk in chunks)


def test_nothing_is_lost_when_splitting() -> None:
    chunks = chunk_markdown(NESTED)
    joined = " ".join(chunk.text for chunk in chunks)
    assert "Mitosis is division of the nucleus." in joined
    assert "Atoms bond." in joined
