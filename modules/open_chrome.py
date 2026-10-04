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

from modules.helpers import get_default_temp_profile, make_directories
from config.settings import run_in_background, auto_manage_driver, disable_extensions, safe_mode, file_name, failed_file_name, logs_folder_path, generated_resume_path, keep_login_session
from config.questions import default_resume_path
if auto_manage_driver:
    import undetected_chromedriver as uc
else: 
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    # from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from modules.helpers import find_default_profile_directory, critical_error_log, print_lg
from modules.session import get_session_profile_dir, has_saved_cookies
from selenium.common.exceptions import SessionNotCreatedException


def createChromeSession(isRetry: bool = False, forceTemporary: bool = False):
    make_directories([file_name,failed_file_name,logs_folder_path+"/screenshots",default_resume_path,generated_resume_path+"/temp"])
    # Set up WebDriver with Chrome Profile
    options = uc.ChromeOptions() if auto_manage_driver else Options()
    if run_in_background:   options.add_argument("--headless")
    if disable_extensions:  options.add_argument("--disable-extensions")
    # Without these Chrome spends a tab on its first-run welcome pages.
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    print_lg("IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM! Or it's highly likely that application will just open browser and not do anything!")
    if isRetry: print_lg("Retrying to open the browser...")

    # The bot runs its OWN Chrome profile rather than attaching to your real
    # Chrome one. Your normal Chrome holds a lock on its 'User Data' folder while
    # it's open, and launching against a locked folder fails outright - which is
    # what used to force a brand new, never-before-used session on every run.
    # A private folder is always writable, so the login sticks every time.
    profile_dir = None
    if keep_login_session and not safe_mode and not forceTemporary:
        profile_dir = get_session_profile_dir()
        print_lg("Using the bot's own browser profile, so your LinkedIn login is remembered between runs:\n{}".format(profile_dir))
        if has_saved_cookies(): print_lg("Found a saved LinkedIn login from a previous run.")
        # NOTE: your *real* Chrome profile is deliberately not used, so
        # `find_default_profile_directory()` is left unapplied here. It can
        # supply one if you ever want it - but only with every Chrome window
        # closed, or ChromeDriver won't start.
    else:
        if forceTemporary: print_lg("Falling back to a temporary profile, browsing history will not be saved in the browser!")
        elif safe_mode: print_lg("Safe mode is on, so using a temporary profile. Browsing history will not be saved in the browser!")
        else: print_lg("'Keep me logged in' is off, so using a temporary profile. You'll have to log in again next run!")

    if auto_manage_driver:
        # try: 
        #     driver = uc.Chrome(driver_executable_path="C:\\Program Files\\Google\\Chrome\\chromedriver-win64\\chromedriver.exe", options=options)
        # except (FileNotFoundError, PermissionError) as e: 
        #     print_lg("(auto-managed driver) Got '{}' when using pre-installed ChromeDriver.".format(type(e).__name__))
            print_lg("Downloading the matching Chrome driver... This may take some time (this happens each run when auto_manage_driver is enabled).")
            # Passing user_data_dir (rather than only the --user-data-dir argument)
            # is what tells undetected-chromedriver to keep the profile on quit.
            # Left as None it creates its own temp folder and deletes it again.
            driver = uc.Chrome(options=options, user_data_dir=profile_dir)
    else:
        # Plain ChromeDriver reads the folder from the argument set above.
        if profile_dir: options.add_argument("--user-data-dir={}".format(profile_dir))
        driver = webdriver.Chrome(options=options) #, service=Service(executable_path="C:\\Program Files\\Google\\Chrome\\chromedriver-win64\\chromedriver.exe"))
    driver.maximize_window()
    wait = WebDriverWait(driver, 5)
    actions = ActionChains(driver)
    return options, driver, actions, wait

try:
    options, driver, actions, wait = None, None, None, None
    options, driver, actions, wait = createChromeSession()
except SessionNotCreatedException as e:
    # Retry once, still keeping the profile - the first failure is usually a
    # stale lock left behind by a bot run that didn't shut down cleanly.
    critical_error_log("Failed to create Chrome Session, retrying", e)
    try:
        options, driver, actions, wait = createChromeSession(isRetry=True)
    except Exception as retry_error:
        # Last resort so the run isn't dead: forget the profile and start clean.
        critical_error_log("Failed to create Chrome Session again, retrying with a temporary profile", retry_error)
        options, driver, actions, wait = createChromeSession(isRetry=True, forceTemporary=True)
except Exception as e:
    msg = 'Seems like Google Chrome is out dated. Update browser and try again! \n\n\nIf issue persists, try Safe Mode. Set, safe_mode = True in config.py \n\nPlease check GitHub discussions/support for solutions https://github.com/GodsScion/Auto_job_applier_linkedIn \n                                   OR \nReach out in discord ( https://discord.gg/fFp7uUzWCY )'
    if isinstance(e,TimeoutError): msg = "Couldn't download Chrome-driver. Set auto_manage_driver = False in config!"
    print_lg(msg)
    critical_error_log("In Opening Chrome", e)
    from pyautogui import alert
    alert(msg, "Error in opening chrome")
    try: driver.quit()
    except NameError: exit()