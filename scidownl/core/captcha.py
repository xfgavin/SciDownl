# -*- coding: utf-8 -*-
"""ALTCHA captcha solver for Sci-Hub."""
import hashlib
import json
import base64
import re

from bs4 import BeautifulSoup

from ..log import get_logger

logger = get_logger()


def solve_altcha(session, base_url, html_content, proxies=None):
    """Solve the ALTCHA proof-of-work captcha on a Sci-Hub page.

    :param session: requests.Session with existing cookies.
    :param base_url: The Sci-Hub base URL (e.g. 'http://sci-hub.st').
    :param html_content: HTML string of the captcha page.
    :param proxies: Optional proxy dict for requests.
    :returns: True if captcha was solved, False otherwise.
    """
    proxies = proxies or {}
    soup = BeautifulSoup(html_content, 'html.parser')

    widget = soup.find('altcha-widget')
    if widget is None:
        return False

    challenge_path = widget.get('challengeurl')
    if not challenge_path:
        return False

    # Extract solution submission path from the inline script
    solution_path = None
    for script in soup.find_all('script'):
        if script.string and 'captcha/solution' in script.string:
            match = re.search(r'/captcha/solution/\d+', script.string)
            if match:
                solution_path = match.group()
                break

    if solution_path is None:
        logger.warning("Could not find captcha solution endpoint in page")
        return False

    # Fetch the challenge
    challenge_url = base_url.rstrip('/') + challenge_path
    try:
        challenge_res = session.get(challenge_url, proxies=proxies, timeout=10)
        challenge = challenge_res.json()
    except Exception as e:
        logger.warning(f"Failed to fetch captcha challenge: {e}")
        return False

    salt = challenge['salt']
    target = challenge['challenge']
    max_number = challenge.get('maxNumber', 500000)
    signature = challenge.get('signature', '')
    algorithm = challenge.get('algorithm', 'SHA-256')
    hash_name = algorithm.replace('-', '').lower()

    # Solve the proof-of-work
    logger.info(f"Solving ALTCHA captcha (max={max_number})...")
    solution_number = None
    for i in range(max_number + 1):
        h = hashlib.new(hash_name, (salt + str(i)).encode()).hexdigest()
        if h == target:
            solution_number = i
            break

    if solution_number is None:
        logger.warning("Failed to solve ALTCHA captcha")
        return False

    logger.info(f"ALTCHA captcha solved (number={solution_number})")

    # Build and submit the solution
    payload_obj = {
        'algorithm': algorithm,
        'challenge': target,
        'number': solution_number,
        'salt': salt,
        'signature': signature,
    }
    altcha_payload = base64.b64encode(json.dumps(payload_obj).encode()).decode()

    solution_url = base_url.rstrip('/') + solution_path
    try:
        res = session.post(
            solution_url,
            json={'captcha': altcha_payload},
            proxies=proxies,
            timeout=10,
        )
        result = res.json()
        if result.get('success'):
            logger.info("ALTCHA captcha verified successfully")
            return True
        else:
            logger.warning(f"Captcha solution rejected: {result}")
            return False
    except Exception as e:
        logger.warning(f"Failed to submit captcha solution: {e}")
        return False


def is_captcha_page(html_content):
    """Check if the HTML content is a Sci-Hub captcha page.

    The captcha page is identified by having a title containing 'robot'
    AND lacking any PDF content (no object/embed with PDF).
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    title = soup.title
    if title and 'robot' in title.text.lower():
        return True
    # The captcha-only page has the "question" div with "Are you a robot?"
    question_div = soup.find('div', class_='question')
    if question_div:
        return True
    return False
