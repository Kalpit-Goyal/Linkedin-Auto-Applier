'''
Tests for reading one question and picking an answer for it (`runAiBot.py`).

Each of these covers a wrong answer that reached a real application:

- a character counter ("0/20") read as the question's text, so the field got the
  default that is meant for an unreadable question - and every unreadable field got
  the same default, which is what "it answers 1 in every field" looks like from
  outside
- a notice-period dropdown of days answered from its label alone: the label rule
  said "Yes", nothing in the dropdown matched, and one was taken at random - so
  someone available immediately was answered as "60 Days"
- a radio option whose label is not tied to its input by an id, so the option's own
  text could not be read and nothing could be matched onto it

The fakes below implement only the lookups the code under test actually makes, which
is also a record of those lookups: a new lookup has to be added here before it works
on a step nobody has captured yet.
'''

import contextlib
import io

with contextlib.redirect_stdout(io.StringIO()):
    import runAiBot


# ---------------------------------------------------------------- harness


class FakeLabel:
    '''A label element: its text, and nothing else.'''

    def __init__(self, text):
        self.text = text

    def find_element(self, by, xpath):
        raise LookupError(xpath)


class FakeControl:
    '''An input that reports the attributes a question is read from.'''

    def __init__(self, attributes=None):
        self.attributes = attributes or {}

    def get_attribute(self, name):
        if name == "value":
            return self.attributes.get("value", "")
        return self.attributes.get(name)

    def clear(self):
        self.attributes["value"] = ""

    def send_keys(self, value):
        self.attributes["value"] = str(value)


class FakeOption:
    '''A radio input whose label is linked to it by nothing but position.'''

    def __init__(self, attributes=None, around=None):
        self.attributes = attributes or {}
        self.around = around or {}

    def get_attribute(self, name):
        return self.attributes.get(name)

    def find_element(self, by, xpath):
        if xpath in self.around:
            return FakeLabel(self.around[xpath])
        raise LookupError(xpath)


class FakeQuestion:
    '''A question wrapper, as `answer_questions` sees one.'''

    def __init__(self, text="", label=None, control=None, preceding=None, following=None):
        self.text = text
        self.label = label
        self.control = control
        self.preceding = preceding
        self.following = following

    def find_element(self, by, xpath):
        found = self._lookup(xpath)
        if found is None:
            raise LookupError(xpath)
        return found

    def find_elements(self, by, xpath):
        found = self._lookup(xpath)
        return [] if found is None else [found]

    def _lookup(self, xpath):
        if self.label is not None and xpath.startswith(".//label"):
            return self.label
        if self.control is not None and xpath.startswith(".//input[@type='text'"):
            return self.control
        if self.preceding is not None and xpath.startswith("./preceding-sibling"):
            return FakeLabel(self.preceding)
        if self.following is not None and xpath.startswith("./following-sibling"):
            return FakeLabel(self.following)
        return None


class FakeModal:
    '''The dialog: it answers the wrapper query and nothing else.'''

    def __init__(self, questions):
        self.questions = questions

    def find_elements(self, by, xpath):
        if "easyApplyFieldFocus_" in xpath or "data-test-form-element" in xpath:
            return list(self.questions)
        return []


def answer(monkeypatch, question, work_location="New Delhi"):
    '''Runs `answer_questions` over one question with the outside world stubbed.'''
    messages, captured = [], []
    monkeypatch.setattr(runAiBot, "print_lg", lambda *args, **kwargs: messages.append(args))
    monkeypatch.setattr(runAiBot, "_capture_unreadable_form", lambda: captured.append(1))
    monkeypatch.setattr(runAiBot, "qa_find", lambda *args, **kwargs: None)
    monkeypatch.setattr(runAiBot, "driver", None, raising=False)
    result = runAiBot.answer_questions(FakeModal([question]), set(), work_location)
    return result, messages, captured


# ---------------------------------------------------------------- reading the question


def test_a_question_whose_text_cannot_be_read_is_left_alone(monkeypatch):
    '''
    The regression behind "it answers 1 in every field": a label that is only a
    character counter is not a question, and there is nothing else to read. Typing a
    default anyway puts an answer meant for something else into the field, so the
    field is reported instead and the step is saved for its markup.
    '''
    control = FakeControl()
    question = FakeQuestion(text="", label=FakeLabel("0/20"), control=control)

    result, messages, captured = answer(monkeypatch, question)

    assert control.attributes.get("value", "") == ""
    assert ("Unreadable question", "", "text", "") in result
    assert captured == [1]
    assert any("left unanswered" in str(message) for message in messages)


def test_a_control_that_states_its_own_question_is_answered_from_it(monkeypatch):
    '''
    The location typeahead has no label element at all - the question is only on the
    control - so a missing label must fall through to it instead of ending in
    "Unknown", which is how the field used to be skipped or guessed at.
    '''
    control = FakeControl({"placeholder": "How many years of work experience do you have?"})
    question = FakeQuestion(text="", control=control)
    monkeypatch.setattr(runAiBot, "years_of_experience", "7")

    result, messages, captured = answer(monkeypatch, question)

    assert control.attributes["value"] == "7"
    assert ("how many years of work experience do you have?", "7", "text", "") in result
    assert not captured


def test_a_character_counter_is_skipped_so_the_real_question_is_read(monkeypatch):
    '''
    The counter sits above the question inside the same wrapper, so the first line of
    the wrapper's text used to be "0/20" and the field was answered as if that had
    been asked.
    '''
    control = FakeControl()
    question = FakeQuestion(text="0/20\nWhat is your notice period?", control=control)
    monkeypatch.setattr(runAiBot, "notice_period", "30")

    result, messages, captured = answer(monkeypatch, question)

    assert control.attributes["value"] == "30"
    assert ("what is your notice period?", "30", "text", "") in result


def test_the_question_sitting_beside_a_counter_only_wrapper_is_used():
    '''A wrapper that holds nothing but the counter still has the question next to it.'''
    question = FakeQuestion(text="0/20", preceding="How many years of experience?")
    assert runAiBot._question_text(question) == "How many years of experience?"


def test_a_control_that_says_nothing_leaves_the_question_empty():
    '''
    Empty rather than some guess: the caller reports an empty read, and a guess is
    exactly what must not happen here.
    '''
    assert runAiBot._question_text(FakeQuestion(text="0/20")) == ""


def test_the_control_is_asked_before_the_wrapper():
    assert runAiBot._question_text(FakeQuestion(text="0/20"), FakeControl({"aria-label": "City"})) == "City"


def test_counters_in_every_shape_are_recognised():
    assert runAiBot._COUNTER_LINE.match("0/20")
    assert runAiBot._COUNTER_LINE.match("0/2000 of 200 characters")
    assert runAiBot._COUNTER_LINE.match("6 of 100 characters")
    assert not runAiBot._COUNTER_LINE.match("What is your notice period?*")
    assert not runAiBot._COUNTER_LINE.match("Location (city)*")


# ---------------------------------------------------------------- choosing an answer


def test_an_answer_the_dropdown_does_not_list_lands_on_the_closest_option():
    '''
    A notice period of 0 days and a dropdown starting at "Less than 15 Days" mean the
    same thing, and taking anything else at random answers "60 Days" for someone who
    can join immediately.
    '''
    days = ["Select an option", "Less than 15 Days", "15 Days", "30 Days", "45 Days", "60 Days", "90 Days"]
    assert runAiBot._closest_option("0", days) == "Less than 15 Days"
    assert runAiBot._closest_option("30", days) == "30 Days"


def test_numbers_in_the_answer_and_the_options_are_compared_without_their_grouping():
    '''`3,00,000` and `300000` are the same salary, and both are written both ways.'''
    assert runAiBot._closest_option("300000", ["₹3,00,000", "₹5,00,000"]) == "₹3,00,000"


def test_an_answer_with_no_number_in_it_has_no_closest_option():
    '''Nothing to be close to: the caller falls back to its own reporting.'''
    assert runAiBot._closest_option("Yes", ["Agree", "Disagree"]) is None


def test_a_radio_option_is_read_from_the_label_the_input_sits_in():
    '''
    The SDUI form ties an option to its label by position rather than by id, so
    looking only for `label[@for=id]` leaves every option "Unknown" and no answer can
    be matched onto any of them.
    '''
    option = FakeOption(around={"./ancestor-or-self::label[1]": "Yes"})
    assert runAiBot._radio_option_label(FakeQuestion(), option) == "Yes"


def test_a_radio_option_with_no_readable_label_says_so_rather_than_becoming_empty():
    assert runAiBot._radio_option_label(FakeQuestion(), FakeOption()) == "Unknown"
