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
