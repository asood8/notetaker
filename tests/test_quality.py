import pytest

from notetaker.models import Card
from notetaker.quality import rejection_reason


def card(question: str, answer: str = "a reasonable answer") -> Card:
    return Card(question=question, answer=answer)


# Every one of these came out of a real run over the sample notes.
@pytest.mark.parametrize(
    "question",
    [
        "Is the cell membrane a fixed structure?",
        "Does glycolysis require oxygen?",
        "Does cholesterol make the membrane rigid at high temperatures?",
        "Can substances freely pass through the cell membrane?",
        "Are integral proteins embedded in the bilayer?",
        "Has the acetyl-CoA been oxidized?",
        "Will the pump move sodium out?",
    ],
)
def test_yes_no_questions_are_rejected(question: str) -> None:
    assert rejection_reason(card(question)) == "yes/no question"


@pytest.mark.parametrize("answer", ["Yes", "no", "Yes, it does", "True", "No, it is selective"])
def test_yes_no_answers_are_rejected(answer: str) -> None:
    assert rejection_reason(card("What about the membrane?", answer)) == "yes/no answer"


def test_follow_up_questions_are_rejected() -> None:
    assert rejection_reason(card("Does it need energy? If so, what kind?")) is not None


def test_questions_about_the_document_are_rejected() -> None:
    reason = rejection_reason(card("What does this section cover?"))
    assert reason == "question about the document"


def test_a_paragraph_answer_is_rejected() -> None:
    assert rejection_reason(card("What is glycolysis?", "word " * 41)) == "answer too long"


@pytest.mark.parametrize(
    "question",
    [
        "What is the main component of the cell membrane?",
        "Where does glycolysis take place?",
        "How many sodium ions are moved out per cycle?",
        "Which stage of respiration does not require oxygen?",
        "What is oxidized in the Krebs cycle?",
        "Why does cholesterol stabilize the membrane?",
    ],
)
def test_good_cards_are_kept(question: str) -> None:
    assert rejection_reason(card(question)) is None


def test_a_normal_length_answer_is_kept() -> None:
    answer = "The diffusion of water across a selectively permeable membrane"
    assert rejection_reason(card("What is osmosis?", answer)) is None


def test_a_word_merely_starting_with_an_auxiliary_is_not_rejected() -> None:
    # "Doesn't" is a contraction, but "Isotopes" must not trip the `is` rule.
    assert rejection_reason(card("Isotopes of carbon differ in what way?")) is None


# --- failures found on real lecture notes ------------------------------------


@pytest.mark.parametrize("answer", ["Unknown", "unclear", "N/A", "None", "not specified"])
def test_a_non_answer_is_rejected(answer: str) -> None:
    assert rejection_reason(card("What is the focus of this handout?", answer)) is not None


def test_a_truncated_one_word_answer_is_rejected() -> None:
    # Real output: "What is the main focus of biochemical genetics? -> how"
    assert rejection_reason(card("What is biochemical genetics?", "how")) == "no real answer"


@pytest.mark.parametrize("answer", ["Two", "ATP", "X", "10-12%", "Pyruvate"])
def test_short_but_real_answers_are_kept(answer: str) -> None:
    assert rejection_reason(card("How many, or what, is it?", answer)) is None


def test_a_card_that_answers_itself_is_rejected() -> None:
    # Real output from a slide on the history of genetics.
    question = "Which movement of the 1900s was based on eugenics?"
    assert rejection_reason(card(question, "Eugenics")) == "answer is in the question"


def test_a_shared_word_is_not_treated_as_a_giveaway() -> None:
    question = "What is the study of the structure and function of genes?"
    assert rejection_reason(card(question, "Molecular genetics")) is None


@pytest.mark.parametrize(
    "question",
    [
        "What is the focus of this handout?",
        "What does this lecture cover?",
        "What is shown on this slide?",
        "What does the handout say about genetics?",
    ],
)
def test_questions_about_the_teaching_material_are_rejected(question: str) -> None:
    # The answer deliberately shares no word with the question, so this tests
    # the meta rule rather than the one about a card answering itself.
    assert rejection_reason(card(question, "Several subjects")) == "question about the document"


# --- course admin, reported from a real run -----------------------------------


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("When is Exam 1 scheduled?", "Thursday, February 19th"),
        ("What day is staff giving support on Exam 1 review?", "Wed"),
        ("Which section gets additional Engagement Points?", "The one with the highest score"),
        ("When are office hours?", "Monday at 3pm"),
        ("What is the due date for homework 2?", "March 4"),
        ("How many points is the final worth?", "30"),
    ],
)
def test_course_admin_is_not_study_material(question: str, answer: str) -> None:
    reason = rejection_reason(card(question, answer))
    assert reason == "course admin, not course material"


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("When is ATP produced during respiration?", "In oxidative phosphorylation"),
        ("What type of numbers can be signed or unsigned?", "Integers"),
        ("When does the cell enter prophase?", "After interphase"),
        ("What day-neutral process breaks down glucose?", "Glycolysis"),
    ],
)
def test_real_facts_that_mention_time_are_kept(question: str, answer: str) -> None:
    assert rejection_reason(card(question, answer)) is None


@pytest.mark.parametrize(
    "heading",
    [("Logistics",), ("Announcements",), ("Course Logistics",), ("Syllabus",), ("Reminders",)],
)
def test_admin_sections_are_recognised(heading: tuple[str, ...]) -> None:
    from notetaker.quality import is_admin_section

    assert is_admin_section(heading)


@pytest.mark.parametrize(
    "heading",
    [
        ("Bit Operations",),
        ("Biology", "Sleep Schedule"),
        ("Pathology", "Tumour Grading"),
        ("Statistics", "Logistic Regression"),
        ("Cell_Biology", "Transport"),
    ],
)
def test_subject_matter_is_not_mistaken_for_admin(heading: tuple[str, ...]) -> None:
    # Each of these contains a word that looks administrative out of context.
    from notetaker.quality import is_admin_section

    assert not is_admin_section(heading)
