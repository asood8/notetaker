from notetaker.dedup import Deduper
from notetaker.models import Card


def card(question: str, answer: str) -> Card:
    return Card(question=question, answer=answer)


def test_the_first_card_is_always_kept() -> None:
    assert Deduper().add(card("What is ATP?", "Adenosine triphosphate")) is True


def test_an_identical_question_is_rejected() -> None:
    deduper = Deduper()
    deduper.add(card("What is ATP?", "Adenosine triphosphate"))
    assert deduper.add(card("What is ATP?", "Adenosine triphosphate")) is False


def test_case_and_punctuation_differences_are_still_duplicates() -> None:
    deduper = Deduper()
    deduper.add(card("What is ATP?", "Energy"))
    assert deduper.add(card("what IS atp", "Energy")) is False


def test_a_reordered_question_with_the_same_answer_is_a_duplicate() -> None:
    deduper = Deduper()
    deduper.add(card("Where does glycolysis occur?", "The cytoplasm"))
    assert deduper.add(card("Glycolysis occurs where?", "The cytoplasm")) is False


def test_an_inverted_pair_is_caught() -> None:
    # Both of these came out of a real run over the same section.
    deduper = Deduper()
    deduper.add(card("Where are peripheral proteins attached?", "the surface of the membrane"))
    assert (
        deduper.add(card("What is attached to the surface of the membrane?", "peripheral proteins"))
        is False
    )


def test_two_facts_that_differ_by_one_word_are_kept() -> None:
    # Regression: a similarity threshold used to merge these two. Both are real
    # cards from the sample notes, and both have the answer "Two".
    deduper = Deduper()
    assert deduper.add(card("How many NADH are produced during glycolysis?", "Two")) is True
    assert deduper.add(card("How many ATP are produced during glycolysis?", "Two")) is True


def test_unrelated_cards_are_all_kept() -> None:
    deduper = Deduper()
    assert deduper.add(card("Where does glycolysis occur?", "The cytoplasm")) is True
    assert deduper.add(card("What is oxidized in the Krebs cycle?", "Acetyl-CoA")) is True
    assert deduper.add(card("What is ATP?", "Adenosine triphosphate")) is True


def test_a_short_answer_does_not_trigger_the_inverse_rule() -> None:
    # "two" appearing inside another question must not collapse unrelated cards.
    deduper = Deduper()
    deduper.add(card("How many ions move out?", "Two"))
    assert deduper.add(card("Two of what are brought in?", "Potassium ions")) is True


def test_the_same_question_with_a_different_answer_is_still_a_duplicate() -> None:
    # The question is the identity of a card; a second answer for it is a conflict,
    # not a new card.
    deduper = Deduper()
    deduper.add(card("What is ATP?", "Adenosine triphosphate"))
    assert deduper.add(card("What is ATP?", "The energy currency of the cell")) is False
