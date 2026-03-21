# -*- coding: utf-8 -*-
"""Crawler implementations."""
import requests

from .captcha import solve_altcha, is_captcha_page
from .content import HtmlContent
from .base import BaseCrawler, BaseSource, BaseTaskStep, BaseTask, BaseContent
from ..log import get_logger
from ..exception import CrawlException
from ..db.service import ScihubUrlService

logger = get_logger()


class ScihubCrawler(BaseCrawler, BaseTaskStep):
    """Crawler of a scihub source."""

    OK_STATUS_CODES = [200]

    def __init__(self, source: BaseSource, scihub_url: str, task: BaseTask = None):
        BaseCrawler.__init__(self, source)
        BaseTaskStep.__init__(self, task)
        self.scihub_url = scihub_url
        self.sess = requests.Session()
        self.service = ScihubUrlService()

        if self.task is not None:
            self.task.context['source'] = source
            self.task.context['referer'] = scihub_url
            self.task.context['status'] = 'crawling'

    def _fetch(self, proxies):
        """Fetch the page from Sci-Hub. Uses GET with path for DOI/PMID,
        falls back to POST for title searches."""
        source_id = self.source[self.source.type]

        if self.source.type == 'title':
            # Title searches must use POST form data
            res = self.sess.post(self.scihub_url, data={'request': source_id}, proxies=proxies)
        else:
            # DOI/PMID use GET with identifier in URL path
            url = f"{self.scihub_url.rstrip('/')}/{source_id}"
            res = self.sess.get(url, proxies=proxies)
        return res

    def crawl(self) -> HtmlContent:
        try:
            proxies = self.task.context.get('proxies', {}) if self.task is not None else {}
            logger.info(f"<- Request: scihub_url={self.scihub_url}, source={self.source}, proxies={proxies}")

            res = self._fetch(proxies)
            logger.info(f"-> Response: status_code={res.status_code}, content_length={len(res.content.decode())}")

            if res.status_code not in ScihubCrawler.OK_STATUS_CODES:
                raise RuntimeError(f"Error occurs when crawling source: {self.source}")

            html_text = res.content.decode()

            # Handle CAPTCHA if present
            if is_captcha_page(html_text):
                logger.info("Captcha detected, solving...")
                solved = solve_altcha(self.sess, self.scihub_url, html_text, proxies)
                if solved:
                    # Re-fetch the page after solving captcha
                    res = self._fetch(proxies)
                    html_text = res.content.decode()
                    logger.info(f"-> Post-captcha response: status_code={res.status_code}, "
                                f"content_length={len(html_text)}")
                    if is_captcha_page(html_text):
                        raise RuntimeError("Still getting captcha after solving it")
                else:
                    raise RuntimeError("Failed to solve captcha")

            content = HtmlContent(html_text)

            if self.task is not None:
                self.task.context['content'] = content
                self.task.context['status'] = 'crawled'
            return content
        except Exception as e:
            if self.task is not None:
                self.task.context['status'] = 'crawling_failed'
                self.task.context['error'] = e
                self.service.increment_failed_times(self.scihub_url)
            raise CrawlException(f"Error occurs when crawling: {e}")

    def __del__(self):
        self.sess.close()
