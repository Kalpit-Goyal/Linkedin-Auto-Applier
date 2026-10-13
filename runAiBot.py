'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit
            
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    26.01.20.5.08
'''


# Imports
import os
import csv
import re
import time
import pyautogui

# Raise the CSV field-size cap so very long job descriptions don't trip the writer.
csv.field_size_limit(1000000)

from random import choice, shuffle, randint
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.select import Select
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, NoSuchWindowException, ElementNotInteractableException, WebDriverException

from config.personals import *
from config.questions import *
from config.search import *
from config.secrets import use_AI, username, password, ai_provider
from config.settings import *
from config.profile import email_address  # for answering module

from modules.open_chrome import *
from modules.helpers import *
from modules.clickers_and_finders import *
from modules.validator import validate_config
from modules.session import load_linkedin_cookies, save_linkedin_cookies, has_saved_cookies
from modules import newui, jobcard

from modules.question_store import record as qa_record, set_last_job_id, mark_job_answers_unverified
from modules.answering import resolve_answer, record_answer

if use_AI:
    from modules.ai.connections import create_ai_client, extract_skills, close_ai_client

from typing import Literal


pyautogui.FAILSAFE = False
# if use_resume_generator:    from resume_generator import is_logged_in_GPT, login_GPT, open_resume_chat, create_custom_resume


#< Global Variables and logics

if run_in_background == True:
    pause_at_failed_question = False
    pause_before_submit = False
    run_non_stop = False

first_name = first_name.strip()
middle_name = middle_name.strip()
last_name = last_name.strip()
full_name = first_name + " " + middle_name + " " + last_name if middle_name else first_name + " " + last_name

useNewResume = True

tabs_count = 1
easy_applied_count = 0
external_jobs_count = 0
failed_count = 0
skip_count = 0
dailyEasyApplyLimitReached = False

re_experience = re.compile(r'[(]?\s*(\d+)\s*[)]?\s*[-to]*\s*\d*[+]*\s*year[s]?', re.IGNORECASE)

desired_salary_lakhs = str(round(desired_salary / 100000, 2))
desired_salary_monthly = str(round(desired_salary/12, 2))
desired_salary = str(desired_salary)

current_ctc_lakhs = str(round(current_ctc / 100000, 2))
current_ctc_monthly = str(round(current_ctc/12, 2))
current_ctc = str(current_ctc)

notice_period_months = str(notice_period//30)
notice_period_weeks = str(notice_period//7)
notice_period = str(notice_period)

aiClient = None
about_company_for_ai = None  # filled in later, once we're processing a specific job

#>


#< Login Functions
def is_logged_in_LN() -> bool:
    '''
    Function to check if user is logged-in in LinkedIn
    * Returns: `True` if user is logged-in or `False` if not
    '''
    if driver.current_url == "https://www.linkedin.com/feed/": return True
    if try_linkText(driver, "Sign in"): return False
    if try_xp(driver, '//button[@type="submit" and contains(text(), "Sign in")]'):  return False
    if try_linkText(driver, "Join now"): return False
    print_lg("Didn't find Sign in link, so assuming user is logged in!")
    return True


def enable_keep_signed_in() -> None:
    '''
    Ticks LinkedIn's "Keep me signed in" box before signing in.
    Without it the auth cookie is a *session* cookie, which Chrome discards on
    exit - the main reason a login wouldn't still be there next run.
    Best effort: LinkedIn redesigns this form often, so any failure is logged
    and ignored rather than being allowed to break the login.
    '''
    candidates = (
        (By.ID, "rememberMe"),
        (By.CSS_SELECTOR, "input[type='checkbox'][name='rememberMe']"),
        (By.CSS_SELECTOR, "input[type='checkbox'][id*='remember']"),
        (By.XPATH, "//label[contains(., 'Keep me signed in')]//input[@type='checkbox']"),
        (By.XPATH, "//label[contains(., 'Keep me signed in')]"),
    )
    for by, selector in candidates:
        try:
            box = driver.find_element(by, selector)
            if box.tag_name.lower() == "input" and box.is_selected():
                print_lg("'Keep me signed in' was already ticked.")
            else:
                box.click()
                print_lg("Ticked 'Keep me signed in' so this login lasts to the next run.")
            return
        except Exception:
            continue
    print_lg("Couldn't find the 'Keep me signed in' box, skipping it. The saved cookie jar will keep the login instead.")


def login_LN() -> None:
    '''
    Function to login for LinkedIn
    * Tries to login using given `username` and `password` from `secrets.py`
    * If failed, tries to login using saved LinkedIn profile button if available
    * If both failed, asks user to login manually
    '''
    # Find the username and password fields and fill them with user credentials
    driver.get("https://www.linkedin.com/login")
    if username == "username@example.com" and password == "example_password":
        pyautogui.alert("User did not configure username and password in secrets.py, hence can't login automatically! Please login manually!", "Login Manually","Okay")
        print_lg("User did not configure username and password in secrets.py, hence can't login automatically! Please login manually!")
        manual_login_retry(is_logged_in_LN, 2)
        return
    try:
        wait.until(EC.presence_of_element_located((By.LINK_TEXT, "Forgot password?")))
        try:
            text_input_by_ID(driver, "username", username, 1)
        except Exception as e:
            print_lg("Couldn't find username field.")
            # print_lg(e)
        try:
            text_input_by_ID(driver, "password", password, 1)
        except Exception as e:
            print_lg("Couldn't find password field.")
            # print_lg(e)
        # Ask LinkedIn for a long-lived auth cookie, so this login is still
        # valid on the next run.
        enable_keep_signed_in()
        # Find the login submit button and click it
        driver.find_element(By.XPATH, '//button[@type="submit" and contains(text(), "Sign in")]').click()
    except Exception as e1:
        try:
            profile_button = find_by_class(driver, "profile__details")
            profile_button.click()
        except Exception as e2:
            # print_lg(e1, e2)
            print_lg("Couldn't Login!")

    try:
        # Wait until successful redirect, indicating successful login
        wait.until(EC.url_to_be("https://www.linkedin.com/feed/")) # wait.until(EC.presence_of_element_located((By.XPATH, '//button[normalize-space(.)="Start a post"]')))
        return print_lg("Login successful!")
    except Exception as e:
        print_lg("Seems like login attempt failed! Possibly due to wrong credentials or already logged in! Try logging in manually!")
        # print_lg(e)
        manual_login_retry(is_logged_in_LN, 2)


def restore_saved_login() -> bool:
    '''
    Try to reuse the login saved on a previous run by re-applying the exported
    cookie jar. The browser profile is already loaded by this point, so this is
    the second chance for a login that Chrome didn't keep.

    Returns True if it worked.
    '''
    if not keep_login_session or not has_saved_cookies(): return False
    print_lg("Trying the LinkedIn login saved on your last run...")
    if not load_linkedin_cookies(driver): return False
    # Cookies can only be re-applied from a page on the matching domain, and the
    # feed is the cheapest place to find out whether LinkedIn accepted them.
    driver.get("https://www.linkedin.com/feed/")
    if is_logged_in_LN():
        print_lg("Logged in using your saved session. No need to sign in again!")
        return True
    print_lg("The saved session was rejected by LinkedIn, so you'll need to log in again.")
    return False


def save_login_session() -> None:
    '''Remember this login for the next run. Best effort, never raises.'''
    save_linkedin_cookies(driver)
#>



def get_applied_job_ids() -> set[str]:
    '''
    Function to get a `set` of applied job's Job IDs
    * Returns a set of Job IDs from existing applied jobs history csv file
    '''
    job_ids: set[str] = set()
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                job_ids.add(row[0])
    except FileNotFoundError:
        print_lg(f"The CSV file '{file_name}' does not exist.")
    return job_ids



def set_search_location() -> None:
    '''
    Function to set search location
    '''
    if search_location.strip():
        try:
            print_lg(f'Setting search location as: "{search_location.strip()}"')
            search_location_ele = try_xp(driver, ".//input[@aria-label='City, state, or zip code'and not(@disabled)]", False) #  and not(@aria-hidden='true')]")
            text_input(actions, search_location_ele, search_location, "Search Location")
        except ElementNotInteractableException:
            try_xp(driver, ".//label[@class='jobs-search-box__input-icon jobs-search-box__keywords-label']")
            actions.send_keys(Keys.TAB, Keys.TAB).perform()
            actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
            actions.send_keys(search_location.strip()).perform()
            sleep(2)
            actions.send_keys(Keys.ENTER).perform()
            try_xp(driver, ".//button[@aria-label='Cancel']")
        except Exception as e:
            try_xp(driver, ".//button[@aria-label='Cancel']")
            print_lg("Failed to update search location, continuing with default location!", e)


def apply_filters() -> None:
    '''
    Function to apply job search filters
    '''
    set_search_location()

    try:
        recommended_wait = 1 if click_gap < 1 else 0

        wait.until(EC.presence_of_element_located((By.XPATH, '//button[normalize-space()="All filters"]'))).click()
        buffer(recommended_wait)

        wait_span_click(driver, sort_by)
        wait_span_click(driver, date_posted)
        buffer(recommended_wait)

        multi_sel_noWait(driver, experience_level) 
        multi_sel_noWait(driver, companies, actions)
        if experience_level or companies: buffer(recommended_wait)

        multi_sel_noWait(driver, job_type)
        multi_sel_noWait(driver, on_site)
        if job_type or on_site: buffer(recommended_wait)

        if easy_apply_only: boolean_button_click(driver, actions, "Easy Apply")
        
        multi_sel_noWait(driver, location)
        multi_sel_noWait(driver, industry)
        if location or industry: buffer(recommended_wait)

        multi_sel_noWait(driver, job_function)
        multi_sel_noWait(driver, job_titles)
        if job_function or job_titles: buffer(recommended_wait)

        if under_10_applicants: boolean_button_click(driver, actions, "Under 10 applicants")
        if in_your_network: boolean_button_click(driver, actions, "In your network")
        if fair_chance_employer: boolean_button_click(driver, actions, "Fair Chance Employer")

        wait_span_click(driver, salary)
        buffer(recommended_wait)
        
        multi_sel_noWait(driver, benefits)
        multi_sel_noWait(driver, commitments)
        if benefits or commitments: buffer(recommended_wait)

        show_results_button: WebElement = driver.find_element(By.XPATH, '//button[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "apply current filters to show")]')
        show_results_button.click()

        global pause_after_filters
        if pause_after_filters and "Turn off Pause after search" == pyautogui.confirm("These are your configured search results and filter. It is safe to change them while this dialog is open, any changes later could result in errors and skipping this search run.", "Please check your results", ["Turn off Pause after search", "Look's good, Continue"]):
            pause_after_filters = False

    except Exception as e:
        print_lg("Setting the preferences failed!")
        pyautogui.confirm(f"Faced error while applying filters. Please make sure correct filters are selected, click on show results and click on any button of this dialog, I know it sucks. Can't turn off Pause after search when error occurs! ERROR: {e}", ["Doesn't look good, but Continue XD", "Look's good, Continue"])
        # print_lg(e)



def get_page_info() -> tuple[WebElement | None, int | None]:
    '''
    Function to get pagination element and current page number
    '''
    try:
        pagination_element = try_find_by_classes(driver, ["jobs-search-pagination__pages", "artdeco-pagination", "artdeco-pagination__pages"])
        scroll_to_view(driver, pagination_element)
        current_page = int(pagination_element.find_element(By.XPATH, "//button[contains(@class, 'active')]").text)
    except Exception as e:
        print_lg("Failed to find Pagination element, hence couldn't scroll till end!")
        pagination_element = None
        current_page = None
        print_lg(e)
    return pagination_element, current_page



def get_job_main_details(job: WebElement, blacklisted_companies: set, rejected_jobs: set) -> tuple[str, str, str, str, str, bool]:
    '''
    # Function to get job main details.
    Returns a tuple of (job_id, title, company, work_location, work_style, skip)
    * job_id: Job ID
    * title: Job title
    * company: Company name
    * work_location: Work location of this job
    * work_style: Work style of this job (Remote, On-site, Hybrid)
    * skip: A boolean flag to skip this job
    '''
    skip = False
    job_details_button = job.find_element(By.TAG_NAME, 'a')  # job.find_element(By.CLASS_NAME, "job-card-list__title")  # Problem in India
    scroll_to_view(driver, job_details_button, True)
    job_id = job.get_dom_attribute('data-occludable-job-id')
    title = job_details_button.text
    title = title[:title.find("\n")]
    # company = job.find_element(By.CLASS_NAME, "job-card-container__primary-description").text
    # work_location = job.find_element(By.CLASS_NAME, "job-card-container__metadata-item").text
    other_details = job.find_element(By.CLASS_NAME, 'artdeco-entity-lockup__subtitle').text
    index = other_details.find(' · ')
    company = other_details[:index]
    work_location = other_details[index+3:]
    work_style = work_location[work_location.rfind('(')+1:work_location.rfind(')')]
    work_location = work_location[:work_location.rfind('(')].strip()
    
    # Skip if previously rejected due to blacklist or already applied
    if company in blacklisted_companies:
        print_lg(f'Skipping "{title} | {company}" job (Blacklisted Company). Job ID: {job_id}!')
        skip = True
    elif job_id in rejected_jobs: 
        print_lg(f'Skipping previously rejected "{title} | {company}" job. Job ID: {job_id}!')
        skip = True
    try:
        if job.find_element(By.CLASS_NAME, "job-card-container__footer-job-state").text == "Applied":
            skip = True
            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
    except: pass
    try: 
        if not skip: job_details_button.click()
    except Exception as e:
        print_lg(f'Failed to click "{title} | {company}" job on details button. Job ID: {job_id}!') 
        # print_lg(e)
        discard_job()
        job_details_button.click() # To pass the error outside
    buffer(click_gap)
    return (job_id,title,company,work_location,work_style,skip)


# Function to check for Blacklisted words in About Company
def check_blacklist(rejected_jobs: set, job_id: str, company: str, blacklisted_companies: set) -> tuple[set, set, WebElement] | ValueError:
    jobs_top_card = try_find_by_classes(driver, ["job-details-jobs-unified-top-card__primary-description-container","job-details-jobs-unified-top-card__primary-description","jobs-unified-top-card__primary-description","jobs-details__main-content"])
    about_company_org = find_by_class(driver, "jobs-company__box")
    scroll_to_view(driver, about_company_org)
    about_company_org = about_company_org.text
    about_company = about_company_org.lower()
    skip_checking = False
    for word in about_company_good_words:
        if word.lower() in about_company:
            print_lg(f'Found the word "{word}". So, skipped checking for blacklist words.')
            skip_checking = True
            break
    if not skip_checking:
        for word in about_company_bad_words: 
            if word.lower() in about_company: 
                rejected_jobs.add(job_id)
                blacklisted_companies.add(company)
                raise ValueError(f'\n"{about_company_org}"\n\nContains "{word}".')
    buffer(click_gap)
    scroll_to_view(driver, jobs_top_card)
    return rejected_jobs, blacklisted_companies, jobs_top_card



# Function to extract years of experience required from About Job
def extract_years_of_experience(text: str) -> int:
    # Extract all patterns like '10+ years', '5 years', '3-5 years', etc.
    matches = re.findall(re_experience, text)
    if len(matches) == 0: 
        print_lg(f'\n{text}\n\nCouldn\'t find experience requirement in About the Job!')
        return 0
    return max([int(match) for match in matches if int(match) <= 12])



def get_job_description(
) -> tuple[
    str | Literal['Unknown'],
    int | Literal['Unknown'],
    bool,
    str | None,
    str | None
    ]:
    '''
    # Job Description
    Function to extract job description from About the Job.
    ### Returns:
    - `jobDescription: str | 'Unknown'`
    - `experience_required: int | 'Unknown'`
    - `skip: bool`
    - `skipReason: str | None`
    - `skipMessage: str | None`
    '''
    # Initialise every return value before the try, so an early failure (e.g. the
    # description element not being found) can never leave them unbound.
    jobDescription = "Unknown"
    experience_required = "Unknown"
    skip = False
    skipReason = None
    skipMessage = None
    try:
        found_masters = 0
        jobDescription = find_by_class(driver, "jobs-box__html-content").text
        jobDescriptionLow = jobDescription.lower()
        for word in bad_words:
            if word.lower() in jobDescriptionLow:
                skipMessage = f'\n{jobDescription}\n\nContains bad word "{word}". Skipping this job!\n'
                skipReason = "Found a Bad Word in About Job"
                skip = True
                break
        if not skip and security_clearance == False and ('polygraph' in jobDescriptionLow or 'clearance' in jobDescriptionLow or 'secret' in jobDescriptionLow):
            skipMessage = f'\n{jobDescription}\n\nFound "Clearance" or "Polygraph". Skipping this job!\n'
            skipReason = "Asking for Security clearance"
            skip = True
        if not skip:
            if did_masters and 'master' in jobDescriptionLow:
                print_lg(f'Found the word "master" in \n{jobDescription}')
                found_masters = 2
            experience_required = extract_years_of_experience(jobDescription)
            if current_experience > -1 and experience_required > current_experience + found_masters:
                skipMessage = f'\n{jobDescription}\n\nExperience required {experience_required} > Current Experience {current_experience + found_masters}. Skipping this job!\n'
                skipReason = "Required experience is high"
                skip = True
    except Exception as e:
        if jobDescription == "Unknown":    print_lg("Unable to extract job description!")
        else:
            experience_required = "Error in extraction"
            print_lg("Unable to extract years of experience required!")
            # print_lg(e)
    return jobDescription, experience_required, skip, skipReason, skipMessage
        


# Function to upload resume
def upload_resume(modal: WebElement, resume: str) -> tuple[bool, str]:
    try:
        modal.find_element(By.NAME, "file").send_keys(os.path.abspath(resume))
        return True, os.path.basename(default_resume_path)
    except: return False, "Previous resume"

# Function to answer common questions for Easy Apply
def answer_common_questions(label: str, answer: str) -> str:
    if 'sponsorship' in label or 'visa' in label: answer = require_visa
    return answer


def _choice_group(container) -> WebElement | bool:
    '''
    The element holding one question's radio options, or False.

    The classic form marks that group with a fieldset carrying a data-test attribute,
    which the caller asks for first. The SDUI form marks nothing at all, so the group
    is recognised structurally: an element holding two or more of the question's
    radios. `container` itself is checked first because the wrapper this function is
    given *is* the group on the new form; only then is the search pushed down to the
    innermost matching descendant, which is what keeps a page-level wrapper from
    answering its first choice question and skipping the rest.
    '''
    try:
        if len(container.find_elements(By.XPATH, './/input[@type="radio"]')) >= 2:
            return container
        groups = container.find_elements(
            By.XPATH,
            './/div[count(.//input[@type="radio"]) >= 2 and not(div[count(.//input[@type="radio"]) >= 2])]',
        )
        return groups[0] if groups else False
    except Exception:
        return False


# LinkedIn puts a character counter next to a field ("0/20", "12 of 100") in the same
# place a question's text would sit. Reading it as the question is how a field ends up
# with an answer meant for something else, so any line that is only a counter is
# skipped wherever question text is read.
_COUNTER_LINE = re.compile(r"^\s*\d+\s*/\s*\d+(\s+\w.*)?$|^\s*\d+\s+of\s+\d+.*$")

# A step whose controls cannot be attributed to any known wrapper is written to disk
# at most once per run: that markup is the only way to teach this file a control it
# does not recognise, and the step is about to be answered from guesses anyway.
_form_captured = False


def _capture_unreadable_form() -> None:
    '''
    Saves the page, once per run, while a form step is open that could not be read.
    '''
    global _form_captured
    if _form_captured:
        return
    _form_captured = True
    try:
        newui.dump_page(driver, name="easy_apply_dump.html")
        print_lg("Saved the form step that could not be read to easy_apply_dump.html")
    except Exception as e:
        print_lg("Could not save the unreadable form step!", e)


def _question_text(container: WebElement, control: WebElement | None = None) -> str:
    '''
    The question a control belongs to, when no `<label>` element says it.

    The SDUI form spreads the question around rather than keeping it in one place: an
    aria-label or a placeholder on the control itself, a line of the wrapper's text, or
    a paragraph next to the wrapper. The control is asked first (a placeholder such as
    "Enter city or location" is a usable question), then the wrapper's own lines with
    the character counters skipped, then the nearest sibling on either side. Returns ""
    when nothing readable is found, so the caller can report the field instead of
    typing an answer meant for a question nobody could read.
    '''
    if control is not None:
        for attribute in ("aria-label", "placeholder", "title"):
            try:
                value = (control.get_attribute(attribute) or "").strip()
            except Exception:
                value = ""
            if value and not _COUNTER_LINE.match(value):
                return value
    try:
        lines = (container.text or "").splitlines()
    except Exception:
        lines = []
    for line in lines:
        line = line.strip()
        if line and not _COUNTER_LINE.match(line):
            return line
    for xpath in ("./preceding-sibling::*[normalize-space(.) != ''][1]",
                  "./following-sibling::*[normalize-space(.) != ''][1]"):
        try:
            value = (container.find_element(By.XPATH, xpath).text or "").strip()
        except Exception:
            value = ""
        if value and not _COUNTER_LINE.match(value):
            return value.splitlines()[0].strip()
    return ""


def _unattributed_controls(modal: WebElement) -> list:
    '''
    One container per form control, for a step that none of the wrapper rules claim.

    The rules are all-or-nothing: when none of them matches, every control on the step
    is skipped, a required one keeps Next on a validation error, and the application is
    discarded at the end of the step. Each control is instead attributed to the nearest
    ancestor that could hold its question - a radio's group, otherwise the closest
    ancestor with visible text, four levels up at most so the step heading is never
    mistaken for the question. The answer rules then run on those containers unchanged;
    only the wrapper is guessed.
    '''
    containers, seen = [], set()
    for control in modal.find_elements(By.XPATH, ".//input | .//select | .//textarea"):
        container = None
        if (control.get_attribute("type") or "").lower() == "radio":
            try:
                container = control.find_element(
                    By.XPATH, "./ancestor::*[count(.//input[@type='radio']) >= 2][1]")
            except Exception:
                container = None
        if container is None:
            try:
                node = control
                for _ in range(4):
                    node = node.find_element(By.XPATH, "..")
                    if (node.text or "").strip():
                        container = node
                        break
            except Exception:
                container = None
        if container is None:
            continue
        key = getattr(container, "id", None) or str(container)
        if key in seen:
            continue
        seen.add(key)
        containers.append(container)
    return containers


def _radio_option_label(group: WebElement, option: WebElement) -> str:
    '''
    The text of one radio option, whichever way the form ties it to its input.

    The classic markup links an option's input to its label with an id; the SDUI form
    has been seen without that link at all. Without the option's own text there is no
    way to match an answer onto it, which is how a choice question ends up answered at
    random, so the label is also looked for around the input itself.
    '''
    option_id = option.get_attribute("id")
    if option_id:
        label = try_xp(group, f'.//label[@for="{option_id}"]', False)
        if label is not None:
            text = (label.text or "").strip()
            if text:
                return text
    for xpath in ("./ancestor-or-self::label[1]", "./following-sibling::label[1]",
                  "./preceding-sibling::label[1]"):
        try:
            text = (option.find_element(By.XPATH, xpath).text or "").strip()
        except Exception:
            text = ""
        if text:
            return text.splitlines()[0].strip()
    return "Unknown"


def _closest_option(answer: str, options: list) -> str | None:
    '''
    The option whose number is nearest to the answer, when the answer is a number the
    dropdown does not offer verbatim.

    A notice period of 0 days and a dropdown starting at "Less than 15 Days" mean the
    same thing, and the shortest option is the honest reading; taking one at random
    instead answers "60 Days" for someone who can join immediately, which is a wrong
    answer rather than a harmless one. Returns None when neither side has a number.
    '''
    try:
        wanted = re.search(r"\d+(?:\.\d+)?", str(answer).replace(",", ""))
        if not wanted:
            return None
        wanted = float(wanted.group())
    except Exception:
        return None
    best, best_gap = None, None
    for option in options:
        try:
            number = re.search(r"\d+(?:\.\d+)?", str(option).replace(",", ""))
            if not number:
                continue
            gap = abs(float(number.group()) - wanted)
        except Exception:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = option, gap
    return best


# Function to answer the questions for Easy Apply - using resolve_answer pipeline
def answer_questions(modal: WebElement, questions_list: set, work_location: str, job_description: str | None = None ) -> set:
    from modules.answering import resolve_answer, record_answer
    from modules.question_store import set_last_job_id
    
    # Get all questions from the page
    # The classic form marked every question with `data-test-form-element`; the SDUI
    # form does not (a capture of the modal found none), so the new questions are
    # matched structurally. Four rules, each innermost-first so a page container never
    # answers a question and skips the rest:
    #   - a `easyApplyFieldFocus_*` wrapper, which the text fields carry
    #   - a label plus a dropdown, which the dropdowns carry without a wrapper
    #   - two or more radios, which is how a choice group is recognisable without
    #     the classic fieldset's data-test attribute
    #   - a label plus any input, the catch-all for a control this list has not seen
    # The classic attribute stays in the same walk so one pass covers either form.
    all_questions = modal.find_elements(By.XPATH, ".//div[@data-test-form-element"
                                                  " or starts-with(@componentkey, 'easyApplyFieldFocus_')"
                                                  " or (label[@for] and .//select and not(div[label]))"
                                                  " or (count(.//input[@type='radio']) >= 2"
                                                  "     and not(div[count(.//input[@type='radio']) >= 2]))"
                                                  " or (label[@for] and .//input"
                                                  "     and not(div[label[@for] and .//input]))]")
    if not all_questions:
        # Steps without questions are normal (the resume and review pages have none).
        # Controls that nobody claims are not: that means the wrapper moved again and
        # every question would be silently skipped until Next stopped working.
        try:
            controls = len(modal.find_elements(By.XPATH, ".//input|.//select|.//textarea"))
        except Exception:
            controls = 0
        if controls:
            print_lg(f"This step shows {controls} form controls but no known question wrapper; "
                     "the form's markup may have changed.")
            _capture_unreadable_form()
            # Answering from a guessed wrapper beats skipping a required field: the
            # rules below run unchanged and only the wrapper is a guess.
            all_questions = _unattributed_controls(modal)
    # all_questions = modal.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-element")
    # all_list_questions = modal.find_elements(By.XPATH, ".//div[@data-test-text-entity-list-form-component]")
    # all_single_line_questions = modal.find_elements(By.XPATH, ".//div[@data-test-single-line-text-form-component]")
    # all_questions = all_questions + all_list_questions + all_single_line_questions

    for Question in all_questions:
        # Detect control type and extract label/options
        select = try_xp(Question, ".//select", False)
        radio = try_xp(Question, './/fieldset[@data-test-form-builder-radio-button-form-component="true"]', False)
        if not radio:
            radio = _choice_group(Question)
        text = try_xp(Question, ".//input[@type='text' or @type='tel' or @type='email' or not(@type)]", False)
        text_area = try_xp(Question, ".//textarea", False)
        checkbox = try_xp(Question, ".//input[@type='checkbox']", False)
        
        question_type = None
        options = None
        label_org = "Unknown"
        control = None
        
        if select:
            question_type = "select"
            control = select
            options = [option.text for option in select.options]
            # Get label
            label = try_xp(Question, ".//label[@for]", False) or try_xp(Question, ".//label", False)
            if label:
                label_org = (label.text or "").strip()
                if not label_org or _COUNTER_LINE.match(label_org):
                    label_org = _question_text(Question, select)
            if not label_org or _COUNTER_LINE.match(label_org):
                label_org = "Unknown"
                
        elif radio:
            question_type = "radio"
            control = radio
            options = []
            for opt in radio.find_elements(By.XPATH, './/input[@type="radio"]'):
                opt_label = _radio_option_label(radio, opt)
                options.append(opt_label)
            # Get label
            label = try_xp(radio, './/span[@data-test-form-builder-radio-button-form-component__title]', False)
            try: label = find_by_class(label, "visually-hidden", 2.0)
            except: pass
            if label:
                label_org = label.text
            if not label_org or _COUNTER_LINE.match(label_org):
                label_org = _question_text(radio)
            if not label_org: label_org = "Unknown"
                
        elif text:
            question_type = "text"
            control = text
            # Get label
            label = try_xp(Question, ".//label[@for]", False) or try_xp(Question, ".//label", False)
            try: label = label.find_element(By.CLASS_NAME,'visually-hidden')
            except: pass
            if label:
                label_org = (label.text or "").strip()
            if not label_org or _COUNTER_LINE.match(label_org):
                label_org = _question_text(Question, text)
            if not label_org: label_org = "Unknown"
                
        elif text_area:
            question_type = "textarea"
            control = text_area
            # Get label
            label = try_xp(Question, ".//label[@for]", False)
            if label:
                label_org = label.text
            if not label_org or _COUNTER_LINE.match(label_org):
                label_org = _question_text(Question, text_area)
            if not label_org: label_org = "Unknown"
                
        elif checkbox:
            question_type = "checkbox"
            control = checkbox
            # Get label
            label = try_xp(Question, ".//span[@class='visually-hidden']", False)
            label_org = label.text if label else "Unknown"
        else:
            # Unknown question type - log and continue
            try: preview = " ".join(Question.text.split())
            except Exception: preview = "<unreadable>"
            print_lg(f"This question was not recognised and was left unanswered: {preview[:300]}")
            continue
        
        if not label_org or _COUNTER_LINE.match(label_org):
            label_org = "Unknown"
        
        # Resolve answer using the pipeline
        job_link = driver.current_url if driver else None
        answer, source = resolve_answer(
            label_org,
            question_type,
            options=options,
            job_description=job_description,
            job_link=job_link,
        )
        
        # Handle answer based on source
        if source == "skip":
            final_answer = ""
            print_lg(f"Skipping question (no answer): {label_org}")
        elif source == "pause":
            final_answer = None
            print_lg(f"Pause required for: {label_org}")
        else:
            final_answer = answer if answer else ""
            # Record the answer in the store
            record_answer(
                label_org,
                final_answer,
                question_type,
                options=options if question_type in ("select", "radio") else None,
                source=source,
                approved=(source in ("bank", "store_exact", "store_fuzzy", "profile_rule")),
            )
            print_lg(f"Answered '{label_org}' ({question_type}): {final_answer} [source: {source}]")
        
        # Fill the field
        if question_type == "select" and control:
            select = Select(control)
            selected_option = select.first_selected_option.text
            if overwrite_previous_answers or selected_option == "Select an option":
                if final_answer:
                    try:
                        select.select_by_visible_text(final_answer)
                    except NoSuchElementException:
                        # Try to match option
                        matched = _match_option_fallback(final_answer, [opt.text for opt in select.options])
                        if matched:
                            select.select_by_visible_text(matched)
                            final_answer = matched
            questions_list.add((f'{label_org} [ {", ".join(options) if options else ""} ]', final_answer or "Select an option", "select", None))
            
        elif question_type == "radio" and control:
            if final_answer:
                # Match and click the radio option
                matched_opt = None
                for opt in control.find_elements(By.XPATH, './/input[@type="radio"]'):
                    opt_label = _radio_option_label(control, opt)
                    if opt_label == final_answer:
                        matched_opt = opt
                        break
                if matched_opt:
                    actions.move_to_element(matched_opt).click().perform()
            questions_list.add((f'{label_org} ]', final_answer or "unanswered", "radio", None))
            
        elif question_type in ("text", "textarea") and control:
            if final_answer is not None:
                control.clear()
                control.send_keys(final_answer)
                # Handle location typeahead
                if final_answer and ('city' in label_org.lower() or 'location' in label_org.lower()):
                    from time import sleep
                    sleep(1)
                    actions.send_keys(Keys.ARROW_DOWN).send_keys(Keys.ENTER).perform()
            questions_list.add((label_org, final_answer or "", question_type, None))
            
        elif question_type == "checkbox" and control:
            if final_answer:
                if not control.is_selected():
                    actions.move_to_element(control).click().perform()
            questions_list.add((f'{label_org} ([X] {final_answer or "Unknown"})', bool(final_answer), "checkbox", None))
        
        # Record the job_id for this answer (for later verification)
        # Get job_id from current URL or context
        try:
            job_id_match = re.search(r'/jobs/view/(\d+)', driver.current_url)
            if job_id_match:
                job_id = job_id_match.group(1)
                set_last_job_id(label_org, job_id)
        except:
            pass
    
    return questions_list


def follow_company(modal: WebDriver = driver) -> None:
    '''
    Function to follow or un-follow easy applied companies based om `follow_companies`
    '''
    try:
        follow_checkbox_input = try_xp(modal, ".//input[@id='follow-company-checkbox' and @type='checkbox']", False)
        if follow_checkbox_input and follow_checkbox_input.is_selected() != follow_companies:
            try_xp(modal, ".//label[@for='follow-company-checkbox']")
    except Exception as e:
        print_lg("Failed to update follow companies checkbox!", e)
    


#< Failed attempts logging
def failed_job(job_id: str, job_link: str, resume: str, date_listed, error: str, exception: Exception, application_link: str, screenshot_name: str) -> None:
    '''
    Function to update failed jobs list in excel
    '''
    try:
        with open(failed_file_name, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['Job ID', 'Job Link', 'Resume Tried', 'Date listed', 'Date Tried', 'Assumed Reason', 'Stack Trace', 'External Job link', 'Screenshot Name']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if file.tell() == 0: writer.writeheader()
            record = {
                'Job ID': job_id, 'Job Link': job_link, 'Resume Tried': resume,
                'Date listed': date_listed, 'Date Tried': datetime.now(),
                'Assumed Reason': error, 'Stack Trace': exception,
                'External Job link': application_link, 'Screenshot Name': screenshot_name,
            }
            writer.writerow({key: truncate_for_csv(value) for key, value in record.items()})
            file.close()
    except Exception as e:
        print_lg("Failed to update failed jobs list!", e)
        pyautogui.alert("Failed to update the excel of failed jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")


def screenshot(driver: WebDriver, job_id: str, failedAt: str) -> str:
    '''
    Function to to take screenshot for debugging
    - Returns screenshot name as String
    '''
    screenshot_name = "{} - {} - {}.png".format( job_id, failedAt, str(datetime.now()) )
    path = logs_folder_path+"/screenshots/"+screenshot_name.replace(":",".")
    # special_chars = {'*', '"', '\\', '<', '>', ':', '|', '?'}
    # for char in special_chars:  path = path.replace(char, '-')
    driver.save_screenshot(path.replace("//","/"))
    return screenshot_name
#>



def submitted_jobs(job_id: str, title: str, company: str, work_location: str, work_style: str, description: str, experience_required: int | Literal['Unknown', 'Error in extraction'], 
                   skills: list[str] | Literal['In Development'], hr_name: str | Literal['Unknown'], hr_link: str | Literal['Unknown'], resume: str, 
                   reposted: bool, date_listed: datetime | Literal['Unknown'], date_applied:  datetime | Literal['Pending'], job_link: str, application_link: str, 
                   questions_list: set | None, connect_request: Literal['In Development']) -> None:
    '''
    Function to create or update the Applied jobs CSV file, once the application is submitted successfully
    '''
    try:
        with open(file_name, mode='a', newline='', encoding='utf-8') as csv_file:
            fieldnames = ['Job ID', 'Title', 'Company', 'Work Location', 'Work Style', 'About Job', 'Experience required', 'Skills required', 'HR Name', 'HR Link', 'Resume', 'Re-posted', 'Date Posted', 'Date Applied', 'Job Link', 'External Job link', 'Questions Found', 'Connect Request']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            if csv_file.tell() == 0: writer.writeheader()
            record = {
                'Job ID': job_id, 'Title': title, 'Company': company, 'Work Location': work_location,
                'Work Style': work_style, 'About Job': description, 'Experience required': experience_required,
                'Skills required': skills, 'HR Name': hr_name, 'HR Link': hr_link, 'Resume': resume,
                'Re-posted': reposted, 'Date Posted': date_listed, 'Date Applied': date_applied,
                'Job Link': job_link, 'External Job link': application_link,
                'Questions Found': questions_list, 'Connect Request': connect_request,
            }
            writer.writerow({key: truncate_for_csv(value) for key, value in record.items()})
        csv_file.close()
    except Exception as e:
        print_lg("Failed to update submitted jobs list!", e)
        pyautogui.alert("Failed to update the excel of applied jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")



# Function to discard the job application
def discard_job() -> None:
    actions.send_keys(Keys.ESCAPE).perform()
    wait_span_click(driver, 'Discard', 2)






# Function to apply to jobs
def apply_to_jobs(search_terms: list[str]) -> None:
    applied_jobs = get_applied_job_ids()
    rejected_jobs = set()
    blacklisted_companies = set()
    global current_city, failed_count, skip_count, easy_applied_count, external_jobs_count, tabs_count, pause_before_submit, pause_at_failed_question, useNewResume
    current_city = current_city.strip()

    if randomize_search_order:  shuffle(search_terms)
    for searchTerm in search_terms:
        driver.get(f"https://www.linkedin.com/jobs/search/?keywords={searchTerm}")
        print_lg("\n________________________________________________________________________________________________________________________\n")
        print_lg(f'\n>>>> Now searching for "{searchTerm}" <<<<\n\n')

        apply_filters()

        current_count = 0
        try:
            while current_count < switch_number:
                # Wait until job listings are loaded
                wait.until(EC.presence_of_all_elements_located((By.XPATH, "//li[@data-occludable-job-id]")))

                pagination_element, current_page = get_page_info()

                # Find all job listings in current page
                buffer(3)
                job_listings = driver.find_elements(By.XPATH, "//li[@data-occludable-job-id]")  

            
                for job in job_listings:
                    if keep_screen_awake: pyautogui.press('shiftright')
                    if current_count >= switch_number: break
                    print_lg("\n-@-\n")

                    job_id,title,company,work_location,work_style,skip = get_job_main_details(job, blacklisted_companies, rejected_jobs)
                    
                    if skip: continue
                    # Redundant fail safe check for applied jobs!
                    try:
                        if job_id in applied_jobs or find_by_class(driver, "jobs-s-apply__application-link", 2):
                            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
                            continue
                    except Exception as e:
                        print_lg(f'Trying to Apply to "{title} | {company}" job. Job ID: {job_id}')

                    job_link = "https://www.linkedin.com/jobs/view/"+job_id
                    application_link = "Easy Applied"
                    date_applied = "Pending"
                    hr_link = "Unknown"
                    hr_name = "Unknown"
                    connect_request = "In Development" # Still in development
                    date_listed = "Unknown"
                    skills = "Needs an AI" # Still in development
                    resume = "Pending"
                    reposted = False
                    questions_list = None
                    screenshot_name = "Not Available"

                    try:
                        rejected_jobs, blacklisted_companies, jobs_top_card = check_blacklist(rejected_jobs,job_id,company,blacklisted_companies)
                    except ValueError as e:
                        print_lg(e, 'Skipping this job!\n')
                        failed_job(job_id, job_link, resume, date_listed, "Found Blacklisted words in About Company", e, "Skipped", screenshot_name)
                        skip_count += 1
                        continue
                    except Exception as e:
                        print_lg("Failed to scroll to About Company!")
                        # print_lg(e)



                    # Hiring Manager info
                    try:
                        hr_info_card = WebDriverWait(driver,2).until(EC.presence_of_element_located((By.CLASS_NAME, "hirer-card__hirer-information")))
                        hr_link = hr_info_card.find_element(By.TAG_NAME, "a").get_attribute("href")
                        hr_name = hr_info_card.find_element(By.TAG_NAME, "span").text
                        # if connect_hr:
                        #     driver.switch_to.new_window('tab')
                        #     driver.get(hr_link)
                        #     wait_span_click("More")
                        #     wait_span_click("Connect")
                        #     wait_span_click("Add a note")
                        #     message_box = driver.find_element(By.XPATH, "//textarea")
                        #     message_box.send_keys(connect_request_message)
                        #     if close_tabs: driver.close()
                        #     driver.switch_to.window(linkedIn_tab) 
                        # def message_hr(hr_info_card):
                        #     if not hr_info_card: return False
                        #     hr_info_card.find_element(By.XPATH, ".//span[normalize-space()='Message']").click()
                        #     message_box = driver.find_element(By.XPATH, "//div[@aria-label='Write a message…']")
                        #     message_box.send_keys()
                        #     try_xp(driver, "//button[normalize-space()='Send']")        
                    except Exception as e:
                        print_lg(f'HR info was not given for "{title}" with Job ID: {job_id}!')
                        # print_lg(e)


                    # Calculation of date posted
                    try:
                        # try: time_posted_text = find_by_class(driver, "jobs-unified-top-card__posted-date", 2).text
                        # except: 
                        time_posted_text = jobs_top_card.find_element(By.XPATH, './/span[contains(normalize-space(), " ago")]').text
                        print("Time Posted: " + time_posted_text)
                        if time_posted_text.__contains__("Reposted"):
                            reposted = True
                            time_posted_text = time_posted_text.replace("Reposted", "")
                        date_listed = calculate_date_posted(time_posted_text.strip())
                    except Exception as e:
                        print_lg("Failed to calculate the date posted!",e)


                    description, experience_required, skip, reason, message = get_job_description()
                    if skip:
                        print_lg(message)
                        failed_job(job_id, job_link, resume, date_listed, reason, message, "Skipped", screenshot_name)
                        rejected_jobs.add(job_id)
                        skip_count += 1
                        continue

                    
                    if use_AI and description != "Unknown":
                        try:
                            skills = extract_skills(aiClient, description)
                            print_lg(f"Extracted skills using {ai_provider} AI")
                        except Exception as e:
                            print_lg("Failed to extract skills:", e)
                            skills = "Error extracting skills"

                    uploaded = False
                    # Detect whether this is an Easy Apply job, in three escalating checks.
                    is_easy_apply = try_xp(driver, ".//button[contains(@class,'jobs-apply-button') and contains(@class, 'artdeco-button--3') and contains(@aria-label, 'Easy')]")
                    # Check 2: an apply link carrying LinkedIn's in-app apply URL flag.
                    if not is_easy_apply:
                        try:
                            in_app_apply = driver.find_element(By.XPATH, ".//a[contains(@href, 'openSDUIApplyFlow=true')]")
                            if in_app_apply:
                                in_app_apply.click()
                                is_easy_apply = True
                                print_lg("Easy Apply detected from the in-app apply URL flag.")
                        except:
                            pass
                    # Check 3: click a generic apply button; an Easy Apply modal means yes,
                    # while a brand-new browser tab means it's an external application instead.
                    if not is_easy_apply:
                        try:
                            apply_button = driver.find_element(By.XPATH, ".//button[contains(@class,'jobs-apply-button')]")
                            if apply_button:
                                tabs_open = len(driver.window_handles)
                                apply_button.click()
                                buffer(click_gap)
                                if len(driver.window_handles) > tabs_open:
                                    # A new tab opened -> external apply. Close it and return to LinkedIn.
                                    driver.switch_to.window(driver.window_handles[-1])
                                    if close_tabs and driver.current_window_handle != linkedIn_tab:
                                        driver.close()
                                    driver.switch_to.window(linkedIn_tab)
                                    print_lg("A new tab opened - external application, skipping.")
                                else:
                                    try:
                                        find_by_class(driver, "jobs-easy-apply-modal")
                                        is_easy_apply = True
                                        print_lg("Easy Apply detected from the modal that opened.")
                                    except:
                                        # No modal appeared; dismiss whatever popped up.
                                        try: actions.send_keys(Keys.ESCAPE).perform()
                                        except: pass
                        except:
                            pass
                    if is_easy_apply:
                        try: 
                            try:
                                errored = ""
                                modal = find_by_class(driver, "jobs-easy-apply-modal")
                                wait_span_click(modal, "Next", 1)
                                # if description != "Unknown":
                                #     resume = create_custom_resume(description)
                                resume = "Previous resume"
                                next_button = True
                                questions_list = set()
                                next_counter = 0
                                while next_button:
                                    next_counter += 1
                                    if next_counter >= 15: 
                                        # The step that will not advance is captured before anything
                                        # else runs: its markup is the only way to teach this loop a
                                        # question it does not recognise.
                                        try:
                                            newui.dump_page(driver, name="easy_apply_dump.html")
                                        except Exception as dump_error:
                                            print_lg(f"Could not capture the step that would not advance: {dump_error}")
                                        if pause_at_failed_question:
                                            screenshot(driver, job_id, "Needed manual intervention for failed question")
                                            pyautogui.alert("Couldn't answer one or more questions.\nPlease click \"Continue\" once done.\nDO NOT CLICK Back, Next or Review button in LinkedIn.\n\n\n\n\nYou can turn off \"Pause at failed question\" setting in config.py", "Help Needed", "Continue")
                                            next_counter = 1
                                            continue
                                        if questions_list: print_lg("Stuck for one or some of the following questions...", questions_list)
                                        screenshot_name = screenshot(driver, job_id, "Failed at questions")
                                        errored = "stuck"
                                        raise Exception("Seems like stuck in a continuous loop of next, probably because of new questions.")
                                    questions_list = answer_questions(modal, questions_list, work_location, job_description=description)
                                    if useNewResume and not uploaded: uploaded, resume = upload_resume(modal, default_resume_path)
                                    try: next_button = modal.find_element(By.XPATH, './/span[normalize-space(.)="Review"]') 
                                    except NoSuchElementException:  next_button = modal.find_element(By.XPATH, './/button[contains(span, "Next")]')
                                    try: next_button.click()
                                    except ElementClickInterceptedException: break    # Happens when it tries to click Next button in About Company photos section
                                    buffer(click_gap)

                            except NoSuchElementException: errored = "nose"
                            finally:
                                if questions_list and errored != "stuck": 
                                    print_lg("Answered the following questions...", questions_list)
                                    print("\n\n" + "\n".join(str(question) for question in questions_list) + "\n\n")
                                wait_span_click(driver, "Review", 1, scrollTop=True)
                                cur_pause_before_submit = pause_before_submit
                                if errored != "stuck" and cur_pause_before_submit:
                                    decision = pyautogui.confirm('1. Please verify your information.\n2. If you edited something, please return to this final screen.\n3. DO NOT CLICK "Submit Application".\n\n\n\n\nYou can turn off "Pause before submit" setting in config.py\nTo TEMPORARILY disable pausing, click "Disable Pause"', "Confirm your information",["Disable Pause", "Discard Application", "Submit Application"])
                                    if decision == "Discard Application": raise Exception("Job application discarded by user!")
                                    pause_before_submit = False if "Disable Pause" == decision else True
                                    # try_xp(modal, ".//span[normalize-space(.)='Review']")
                                follow_company(modal)
                                if wait_span_click(driver, "Submit application", 2, scrollTop=True): 
                                    date_applied = datetime.now()
                                    if not wait_span_click(driver, "Done", 2): actions.send_keys(Keys.ESCAPE).perform()
                                elif errored != "stuck" and cur_pause_before_submit and "Yes" in pyautogui.confirm("You submitted the application, didn't you 😒?", "Failed to find Submit Application!", ["Yes", "No"]):
                                    date_applied = datetime.now()
                                    wait_span_click(driver, "Done", 2)
                                else:
                                    print_lg("Since, Submit Application failed, discarding the job application...")
                                    # if screenshot_name == "Not Available":  screenshot_name = screenshot(driver, job_id, "Failed to click Submit application")
                                    # else:   screenshot_name = [screenshot_name, screenshot(driver, job_id, "Failed to click Submit application")]
                                    if errored == "nose": raise Exception("Failed to click Submit application 😑")


                        except Exception as e:
                            print_lg("Failed to Easy apply!")
                            # print_lg(e)
                            critical_error_log("Somewhere in Easy Apply process",e)
                            failed_job(job_id, job_link, resume, date_listed, "Problem in Easy Applying", e, application_link, screenshot_name)
                            mark_job_answers_unverified(job_id)
                            failed_count += 1
                            discard_job()
                            continue
                    else:
                        # Case 2: Apply externally
                        skip, application_link, tabs_count = external_apply(pagination_element, job_id, job_link, resume, date_listed, application_link, screenshot_name)
                        if dailyEasyApplyLimitReached:
                            print_lg("\n###############  Daily application limit for Easy Apply is reached!  ###############\n")
                            return
                        if skip: continue

                    submitted_jobs(job_id, title, company, work_location, work_style, description, experience_required, skills, hr_name, hr_link, resume, reposted, date_listed, date_applied, job_link, application_link, questions_list, connect_request)
                    if uploaded:   useNewResume = False

                    print_lg(f'Successfully saved "{title} | {company}" job. Job ID: {job_id} info')
                    cooldown = randint(15, 30)
                    print_lg(f"Waiting {cooldown} seconds before the next application...")
                    sleep(cooldown)
                    current_count += 1
                    if application_link == "Easy Applied": easy_applied_count += 1
                    else:   external_jobs_count += 1
                    applied_jobs.add(job_id)



                # Switching to next page
                if pagination_element == None:
                    print_lg("Couldn't find pagination element, probably at the end page of results!")
                    break
                try:
                    pagination_element.find_element(By.XPATH, f"//button[@aria-label='Page {current_page+1}']").click()
                    print_lg(f"\n>-> Now on Page {current_page+1} \n")
                except NoSuchElementException:
                    print_lg(f"\n>-> Didn't find Page {current_page+1}. Probably at the end page of results!\n")
                    break

        except (NoSuchWindowException, WebDriverException) as e:
            print_lg("The browser window was closed or the session became invalid. Stopping.", e)
            raise e  # let the outer handler deal with it
        except Exception as e:
            print_lg("Could not read the job listings.")
            critical_error_log("In Applier", e)
            try:
                print_lg(driver.page_source, pretty=True)
            except Exception as dump_error:
                print_lg(f"Could not capture the page source; the browser may have crashed. {dump_error}")

        
# Function to blacklist a job using the new UI's own "About the company" block
def check_blacklist_on_details(rejected_jobs: set, job_id: str, company: str, blacklisted_companies: set, about_company: str) -> tuple[set, set]:
    '''
    Blacklists a job from the description pane's company blurb.

    Same rules and the same ValueError as check_blacklist(), but the blurb comes from a
    verified componentkey instead of the classic "jobs-company__box", so the caller's
    error handling does not need to know which UI produced it.
    '''
    text = (about_company or "").lower()
    if not text: return rejected_jobs, blacklisted_companies
    skip_checking = False
    for word in about_company_good_words:
        if word.lower() in text:
            print_lg(f'Found the word "{word}". So, skipped checking for blacklist words.')
            skip_checking = True
            break
    if not skip_checking:
        for word in about_company_bad_words:
            if word.lower() in text:
                rejected_jobs.add(job_id)
                blacklisted_companies.add(company)
                raise ValueError(f'"{about_company}"\n\nContains "{word}".')
    return rejected_jobs, blacklisted_companies



# Function to apply to the jobs in a search the user has already set up
def apply_to_current_results() -> None:
    '''
    Applies to the jobs in the search that is already on screen.

    The search itself, its filters and the Easy Apply filter are the user's to set: this
    walks the cards that are rendered and submits, and builds no search of its own.
    Two properties of the new UI shape the loop:

    - Cards are re-read from scratch on every pass. The list is virtualised, so card
      elements are recycled on scroll and a list held across a scroll would point at
      different jobs by the time it was used.
    - Every card's job id is checked against the details pane after the click. A click
      can land late or on a neighbouring row, and without that check the bot would
      submit to whichever job happened to be on screen.

    Only Easy Apply is driven here. Off-site jobs are reported and skipped rather than
    sent down external_apply(), whose tab handling was written for the classic UI.
    '''
    applied_jobs = get_applied_job_ids()
    rejected_jobs = set()
    blacklisted_companies = set()
    global current_city, failed_count, skip_count, easy_applied_count, external_jobs_count, tabs_count, pause_before_submit, useNewResume
    current_city = current_city.strip()

    if not newui.results_ready(driver, time=20):
        print_lg("Nothing to apply to. Set up your search first, then run the applier.")
        return

    uploaded = False
    current_count = 0
    try:
        while current_count < switch_number:
            buffer(3)
            # Re-read every pass on purpose: the list recycles its rows.
            cards = newui.list_cards(driver)
            print_lg(f"{len(cards)} job cards currently rendered.")
            if not cards:
                print_lg("No cards rendered; the list may have run out.")
                try:
                    newui.dump_page(driver)
                except Exception as _exc:
                    print_lg(f"Diagnostics failed: {_exc}")
                break

            for card in cards:
                if keep_screen_awake: pyautogui.press('shiftright')
                if current_count >= switch_number: break
                print_lg("\n-@-\n")

                card_data = jobcard.read_card(driver, card)
                job_id = card_data["job_id"]
                title = card_data["title"] or "Unknown"
                company = card_data["company"] or "Unknown"
                work_location = card_data["location"] or "Unknown"
                # The classic UI read the work style off the card's metadata row; the new
                # card does not expose one, so this stays Unknown rather than guessed.
                work_style = "Unknown"

                if not job_id:
                    skip_count += 1
                    print_lg('Skipping a card with no readable job id.')
                    continue
                job_link = f"https://www.linkedin.com/jobs/view/{job_id}"

                if job_id in rejected_jobs:
                    skip_count += 1
                    print_lg(f'Skipping previously rejected "{title} | {company}" job. Job ID: {job_id}!')
                    continue
                if company in blacklisted_companies:
                    skip_count += 1
                    print_lg(f'Skipping "{title} | {company}" job (Blacklisted Company). Job ID: {job_id}!')
                    continue
                if job_id in applied_jobs:
                    skip_count += 1
                    print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
                    continue

                # Opens the job and confirms the pane belongs to it.
                if not newui.select_card(driver, card):
                    skip_count += 1
                    print_lg(f'Could not open "{title} | {company}". Job ID: {job_id}!')
                    continue

                details = newui.read_details(driver)
                description = details["description"] or "Unknown"
                date_listed = newui.read_posted_date(driver)
                experience_required = extract_years_of_experience(description) if description != "Unknown" else 0

                try:
                    check_blacklist_on_details(rejected_jobs, job_id, company, blacklisted_companies, details["about_company"])
                except ValueError as e:
                    print_lg(e, 'Skipping this job!\n')
                    failed_job(job_id, job_link, "Pending", date_listed, "Found Blacklisted words in About Company", e, "Skipped", "Not Available")
                    skip_count += 1
                    continue

                hr_link = "Unknown"
                hr_name = "Unknown"
                connect_request = "In Development"
                skills = "Needs an AI"
                reposted = False
                resume = "Pending"
                questions_list = None
                screenshot_name = "Not Available"
                application_link = "Easy Applied"
                date_applied = "Pending"

                mode = newui.apply_mode(driver)
                if mode == newui.APPLY_NONE:
                    skip_count += 1
                    print_lg(f'No way to apply to "{title} | {company}" (it may be closed). Job ID: {job_id}!')
                    continue
                if mode == newui.APPLY_ALREADY:
                    applied_jobs.add(job_id)
                    skip_count += 1
                    print_lg(f'Already applied to "{title} | {company}". Job ID: {job_id}!')
                    continue
                if mode == newui.APPLY_EXTERNAL:
                    # Not driven here: external_apply() opens tabs and was written for
                    # the classic UI. Easy Apply should have been filtered out anyway.
                    skip_count += 1
                    print_lg(f'"{title} | {company}" is off-site only, skipping. Job ID: {job_id}!')
                    continue

                print_lg(f'Trying to Easy Apply to "{title} | {company}" job. Job ID: {job_id}')
                modal = None
                try:
                    errored = ""
                    modal = newui.open_easy_apply(driver)
                    if not modal:
                        raise Exception("The Easy Apply modal never opened.")
                    resume = "Previous resume"
                    questions_list = set()
                    next_counter = 0
                    next_button = True
                    while next_button:
                        next_counter += 1
                        if next_counter >= 15:
                            if pause_at_failed_question:
                                screenshot_name = screenshot(driver, job_id, "Needed manual intervention for failed question")
                                pyautogui.alert("Couldn't answer one or more questions.\nPlease click \"Continue\" once done.\nDO NOT CLICK Back, Next or Review button in LinkedIn.\n\n\n\n\nYou can turn off \"Pause at failed question\" setting in config.py", "Help Needed", "Continue")
                                next_counter = 1
                                continue
                            if questions_list: print_lg("Stuck for one or some of the following questions...", questions_list)
                            screenshot_name = screenshot(driver, job_id, "Failed at questions")
                            errored = "stuck"
                            raise Exception("Seems like stuck in a continuous loop of next, probably because of new questions.")
                        questions_list = answer_questions(modal, questions_list, work_location, job_description=description)
                        if useNewResume and not uploaded: uploaded, resume = upload_resume(modal, default_resume_path)
                        # The flow replaces the dialog between steps, so the handle taken
                        # at open time can be stale by now.
                        modal = newui.refind_modal(driver) or modal
                        try:
                            next_button = newui.advance(driver, modal, "Next")
                        except ElementClickInterceptedException:
                            # A click meant for Next can land on the company photos strip.
                            break
                        if not next_button: break
                        buffer(click_gap)

                    if questions_list and errored != "stuck":
                        print_lg("Answered the following questions...", questions_list)
                        print("\n\n" + "\n".join(str(question) for question in questions_list) + "\n\n")

                    cur_pause_before_submit = pause_before_submit
                    if cur_pause_before_submit:
                        decision = pyautogui.confirm('1. Please verify your information.\n2. If you edited something, please return to this final screen.\n3. DO NOT CLICK "Submit Application".\n\n\n\n\nYou can turn off "Pause before submit" setting in config.py\nTo TEMPORARILY disable pausing, click "Disable Pause"', "Confirm your information",["Disable Pause", "Discard Application", "Submit Application"])
                        if decision == "Discard Application": raise Exception("Job application discarded by user!")
                        pause_before_submit = False if "Disable Pause" == decision else True
                    follow_company(modal)

                    if newui.advance(driver, modal, "Submit application"):
                        date_applied = datetime.now()
                        if not newui.advance(driver, modal, "Done"):
                            try: actions.send_keys(Keys.ESCAPE).perform()
                            except: pass
                    else:
                        print_lg("Submit Application was not found, so the application is discarded rather than left open.")
                        raise Exception("Failed to click Submit application")

                except Exception as e:
                    print_lg("Failed to Easy Apply!")
                    # print_lg(e)
                    critical_error_log("Somewhere in Easy Apply process", e)
                    failed_job(job_id, job_link, resume, date_listed, "Problem in Easy Applying", e, application_link, screenshot_name)
                    mark_job_answers_unverified(job_id)
                    failed_count += 1
                    newui.discard_application(driver, root=modal, actions=actions)
                    continue

                submitted_jobs(job_id, title, company, work_location, work_style, description, experience_required, skills, hr_name, hr_link, resume, reposted, date_listed, date_applied, job_link, application_link, questions_list, connect_request)
                if uploaded:   useNewResume = False

                print_lg(f'Successfully saved "{title} | {company}" job. Job ID: {job_id} info')
                current_count += 1
                easy_applied_count += 1
                applied_jobs.add(job_id)
                cooldown = randint(15, 30)
                print_lg(f"Waiting {cooldown} seconds before the next application...")
                sleep(cooldown)

            if current_count >= switch_number: break

            # Work through the pages the user prepared, then stop.
            newui.close_details(driver)
            page = newui.current_page(driver)
            if page is None or not newui.go_to_next_page(driver, page):
                print_lg("\n>-> Reached the end of the results.\n")
                break

    except (NoSuchWindowException, WebDriverException) as e:
        print_lg("The browser window was closed or the session became invalid. Stopping.", e)
        raise e  # let the outer handler deal with it
    except Exception as e:
        print_lg("Could not read the job listings.")
        critical_error_log("In Applier", e)
        try:
            print_lg(driver.page_source, pretty=True)
        except Exception as dump_error:
            print_lg(f"Could not capture the page source; the browser may have crashed. {dump_error}")







def wait_for_manual_results() -> bool:
    """Manual search mode: poll for results and prompt the user to prepare search."""
    print_lg("Manual search mode: I will not build a search. Set it up in the LinkedIn window now.")
    while not newui.results_ready(driver, time=10):
        try:
            newui.dump_page(driver)
        except Exception as _exc:
            print_lg(f"Diagnostics failed: {_exc}")
        decision = pyautogui.confirm(
            "No job results found on screen yet.\n\n"
            "1. In the LinkedIn browser window, run your search (keywords / AI search / filters, incl. Easy Apply filter).\n"
            "2. Wait for the job cards to appear.\n"
            "3. Click 'Results ready'.\n\n"
            "Click 'Cancel' to stop this run.",
            "Manual search mode", ["Results ready"],
        )
        if decision is None:
            print_lg("Stopping: no results on screen (user cancelled).")
            return False
    return True
def run(total_runs: int) -> int:
    if dailyEasyApplyLimitReached:
        return total_runs
    print_lg("\n########################################################################################################################\n")
    print_lg(f"Date and Time: {datetime.now()}")
    print_lg(f"Cycle number: {total_runs}")
    if manual_search_mode:
        print_lg("Manual search mode: applying to the search YOU set up in the browser. No search will be built.")
    else:
        print_lg("Using the search already set up in the browser. Set the keywords, the filters and the Easy Apply filter there before running.")
    # The new UI builds its search through filter pills and URL parameters, and the
    # Easy Apply filter is the user's to set. The applier therefore starts from
    # whatever is on screen; apply_to_jobs() is kept for the classic search.
    if manual_search_mode and not wait_for_manual_results():
        return total_runs   # user cancelled; skip cycle, keep summary path intact
    apply_to_current_results()
    print_lg("########################################################################################################################\n")
    if not dailyEasyApplyLimitReached:
        print_lg("Sleeping for 10 min...")
        sleep(300)
        print_lg("Few more min... Gonna start with in next 5 min...")
        sleep(300)
    buffer(3)
    return total_runs + 1



chatGPT_tab = False
linkedIn_tab = False

def main() -> None:
    # Sponsor alert gated behind setting - set show_sponsor_alert = True in config to enable
    # pyautogui.alert("Please consider sponsoring this project at:\n\nhttps://github.com/sponsors/GodsScion\n\n", "Support the project", "Okay")
    total_runs = 1
    try:
        global linkedIn_tab, tabs_count, useNewResume, aiClient
        alert_title = "Error Occurred. Closing Browser!"
        validate_config()
        
        if not os.path.exists(default_resume_path):
            pyautogui.alert(text='Your default resume "{}" is missing! Please update it\'s folder path "default_resume_path" in config.py\n\nOR\n\nAdd a resume with exact name and path (check for spelling mistakes including cases).\n\n\nFor now the bot will continue using your previous upload from LinkedIn!'.format(default_resume_path), title="Missing Resume", button="OK")
            useNewResume = False
        
        # Login to LinkedIn. The browser profile and the saved cookie jar mean
        # this normally costs nothing - login_LN() is only reached on a genuine
        # first run, or once LinkedIn itself has expired the session.
        tabs_count = len(driver.window_handles)
        driver.get("https://www.linkedin.com/login")
        if not is_logged_in_LN(): restore_saved_login()
        if not is_logged_in_LN(): login_LN()
        save_login_session()
        
        linkedIn_tab = driver.current_window_handle

        # # Login to ChatGPT in a new tab for resume customization
        # if use_resume_generator:
        #     try:
        #         driver.switch_to.new_window('tab')
        #         driver.get("https://chat.openai.com/")
        #         if not is_logged_in_GPT(): login_GPT()
        #         open_resume_chat()
        #         global chatGPT_tab
        #         chatGPT_tab = driver.current_window_handle
        #     except Exception as e:
        #         print_lg("Opening OpenAI chatGPT tab failed!")
        if use_AI:
            aiClient = create_ai_client()

        # Start applying to jobs
        driver.switch_to.window(linkedIn_tab)
        if manual_search_mode:
            pyautogui.alert(
                "Manual search mode is ON - the bot will not run its own search.\n\n"
                "In the LinkedIn window that opened:\n"
                "1. Run your search (LinkedIn AI search or keywords).\n"
                "2. Apply your filters, including the Easy Apply filter.\n"
                "3. Wait for job cards to appear, then click OK.\n\n"
                "The bot starts applying as soon as results are on screen.",
                "Set up your search", "OK")
            driver.switch_to.window(linkedIn_tab)
        total_runs = run(total_runs)
        while(run_non_stop):
            if not manual_search_mode:
                if cycle_date_posted:
                    date_options = ["Any time", "Past month", "Past week", "Past 24 hours"]
                    global date_posted
                    date_posted = date_options[date_options.index(date_posted)+1 if date_options.index(date_posted)+1 > len(date_options) else -1] if stop_date_cycle_at_24hr else date_options[0 if date_options.index(date_posted)+1 >= len(date_options) else date_options.index(date_posted)+1]
                if alternate_sortby:
                    global sort_by
                    sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
                total_runs = run(total_runs)
                sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
            total_runs = run(total_runs)
            if dailyEasyApplyLimitReached:
                break
        

    except (NoSuchWindowException, WebDriverException) as e:
        print_lg("The browser window was closed or the session became invalid. Exiting.", e)
    except Exception as e:
        critical_error_log("In Applier Main", e)
        pyautogui.alert(e,alert_title)
    finally:
        summary = "Total runs: {}\nJobs Easy Applied: {}\nExternal job links collected: {}\nTotal applied or collected: {}\nFailed jobs: {}\nIrrelevant jobs skipped: {}\n".format(total_runs,easy_applied_count,external_jobs_count,easy_applied_count + external_jobs_count,failed_count,skip_count)
        print_lg(summary)
        print_lg("\n\nTotal runs:                     {}".format(total_runs))
        print_lg("Jobs Easy Applied:              {}".format(easy_applied_count))
        print_lg("External job links collected:   {}".format(external_jobs_count))
        print_lg("                              ----------")
        print_lg("Total applied or collected:     {}".format(easy_applied_count + external_jobs_count))
        print_lg("\nFailed jobs:                    {}".format(failed_count))
        print_lg("Irrelevant jobs skipped:        {}\n".format(skip_count))
        quotes = choice([
            "Never quit. You're one step closer than before. - Sai Vignesh Golla", 
            "All the best with your future interviews, you've got this. - Sai Vignesh Golla", 
            "Keep up with the progress. You got this. - Sai Vignesh Golla", 
            "If you're tired, learn to take rest but never give up. - Sai Vignesh Golla",
            "Success is not final, failure is not fatal, It is the courage to continue that counts. - Winston Churchill (Not a sponsor)",
            "Believe in yourself and all that you are. Know that there is something inside you that is greater than any obstacle. - Christian D. Larson (Not a sponsor)",
            "Every job is a self-portrait of the person who does it. Autograph your work with excellence. - Jessica Guidobono (Not a sponsor)",
            "The only way to do great work is to love what you do. If you haven't found it yet, keep looking. Don't settle. - Steve Jobs (Not a sponsor)",
            "Opportunities don't happen, you create them. - Chris Grosser (Not a sponsor)",
            "The road to success and the road to failure are almost exactly the same. The difference is perseverance. - Colin R. Davis (Not a sponsor)",
            "Obstacles are those frightful things you see when you take your eyes off your goal. - Henry Ford (Not a sponsor)",
            "The only limit to our realization of tomorrow will be our doubts of today. - Franklin D. Roosevelt (Not a sponsor)",
            ])
        sponsors = "Be the first to have your name here!"
        timeSaved = (easy_applied_count * 80) + (external_jobs_count * 20) + (skip_count * 10)
        timeSavedMsg = ""
        if timeSaved > 0:
            timeSaved += 60
            timeSavedMsg = f"In this run, you saved approx {round(timeSaved/60)} mins ({timeSaved} secs), please consider supporting the project."
        msg = f"{quotes}\n\n\n{timeSavedMsg}\nYou can also get your quote and name shown here, or prioritize your bug reports by supporting the project at:\n\nhttps://github.com/sponsors/GodsScion\n\n\nSummary:\n{summary}\n\n\nBest regards,\nSai Vignesh Golla\nhttps://www.linkedin.com/in/saivigneshgolla/\n\nTop Sponsors:\n{sponsors}"
        pyautogui.alert(msg, "Exiting..")
        print_lg(msg,"Closing the browser...")
        if tabs_count >= 10:
            msg = "NOTE: IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM!\n\nOr it's highly likely that application will just open browser and not do anything next time!" 
            pyautogui.alert(msg,"Info")
            print_lg("\n"+msg)
        if use_AI and aiClient:
            try:
                close_ai_client(aiClient)
                print_lg(f"Closed {ai_provider} AI client.")
            except Exception as e:
                print_lg("Failed to close AI client:", e)
        try:
            if driver:
                # Grab the login before closing, so it's still there even if this
                # run ended in an error. Never raises.
                save_login_session()
                driver.quit()
        except WebDriverException as e:
            print_lg("Browser already closed.", e)
        except Exception as e: 
            critical_error_log("When quitting...", e)


if __name__ == "__main__":
    main()
