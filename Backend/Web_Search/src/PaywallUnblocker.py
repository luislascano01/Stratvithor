import time
import random
import urllib.parse
import logging

from sentence_transformers import SentenceTransformer, util

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PaywallUnblocker:
    """
    A modular paywall unblocker that uses Archive.ph to retrieve archived versions of articles.
    It launches a visual, incognito Chrome browser (via undetected_chromedriver), navigates
    to the Archive.ph URL for the target article, selects the best matching snapshot based on
    anchor text similarity, and returns the final page's HTML.
    """

    def __init__(
            self,
            model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
            similarity_threshold: float = 0.3,
            wait_time: int = 1,  # Reduced wait time
            archive_provider: str = "archive.ph"
    ):
        """
        :param model_name: Model for matching anchor text.
        :param similarity_threshold: (Reserved for future use.)
        :param wait_time: Seconds to wait after key actions.
        :param archive_provider: Currently supports "archive.ph".
        """
        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.wait_time = wait_time
        self.archive_provider = archive_provider

        # Load transformer for computing anchor similarity.
        self.transformer = SentenceTransformer(model_name)

        # Set up Chrome options:
        try:
            from selenium.webdriver.chrome.options import Options
            self.chrome_options = Options()
        except ImportError:
            logger.error("Could not import Selenium. Please install Selenium.")
            raise

        self.chrome_options.add_argument("--incognito")
        # Remove the headless argument to use a visual Chrome window.
        # self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    def unblock_url(self, target_url: str) -> str:
        """
        Retrieves the archived HTML for the given target URL.
        :param target_url: The original article URL.
        :return: Final archived page HTML.
        """
        if self.archive_provider == "archive.ph":
            return self._process_archive_ph(target_url)
        else:
            logger.error(f"Archive provider '{self.archive_provider}' not supported yet.")
            return ""

    def _process_archive_ph(self, target_url: str) -> str:
        """
        Uses Archive.ph to retrieve the archived page.
        """
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
        except ImportError:
            logger.error("Please install undetected_chromedriver")
            return ""

        # Construct Archive.ph URL by URL-encoding the target URL.
        encoded_url = urllib.parse.quote_plus(target_url, safe=":/")
        archive_url = f"https://{self.archive_provider}/{encoded_url}"
        logger.info(f"Navigating to: {archive_url}")

        # Force use of a specific Chrome version (adjust version_main if needed)
        driver = uc.Chrome(options=self.chrome_options, version_main=133)

        try:
            driver.get(archive_url)
            time.sleep(1)  # Reduced wait time for page load

            # Collect all anchor elements.
            anchors = driver.find_elements(By.TAG_NAME, "a")
            anchor_texts = []
            anchor_elements = []
            for a in anchors:
                txt = a.get_attribute("title") or a.text.strip()
                # Skip anchors whose text exactly equals the target URL.
                if txt and txt != target_url:
                    anchor_texts.append(txt)
                    anchor_elements.append(a)

            if not anchor_texts:
                logger.warning("No suitable anchor texts found. Returning current page HTML.")
                time.sleep(self.wait_time)
                return driver.page_source

            # Compute similarity between each anchor text and the target URL.
            target_emb = self.transformer.encode([target_url], convert_to_tensor=True)
            anchor_embs = self.transformer.encode(anchor_texts, convert_to_tensor=True)
            sims = util.cos_sim(anchor_embs, target_emb).squeeze(dim=1)
            best_idx = sims.argmax().item()
            best_anchor_text = anchor_texts[best_idx]
            logger.info(f"Best matching anchor text: '{best_anchor_text}'")

            best_anchor_element = anchor_elements[best_idx]
            logger.info("Clicking on the best anchor link...")
            best_anchor_element.click()
            logger.info(f"Waiting {self.wait_time} seconds for final page to load...")
            time.sleep(self.wait_time)

            # Optionally simulate some human-like actions.
            self.simulate_human_like_actions(driver)

            return driver.page_source
        finally:
            driver.quit()

    def simulate_human_like_actions(self, driver, highlight: bool = True):
        """
        Simulate minimal human-like actions.
        """
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.5)
        page_height = driver.execute_script("return document.body.scrollHeight;")
        middle_y = page_height / 2
        logger.info(f"Page height: {page_height}, scrolling to middle: {middle_y}")
        driver.execute_script(f"window.scrollTo(0, {middle_y});")
        time.sleep(0.5)
        try:
            from selenium.webdriver.common.by import By
        except ImportError:
            logger.error("Please install Selenium.")
            return
        if highlight:
            paragraphs = driver.find_elements(By.TAG_NAME, "p")
            if paragraphs:
                mid_idx = len(paragraphs) // 2
                driver.execute_script("""
                    var range = document.createRange();
                    var sel = window.getSelection();
                    var midEl = arguments[0];
                    range.selectNodeContents(midEl);
                    sel.removeAllRanges();
                    sel.addRange(range);
                """, paragraphs[mid_idx])
                time.sleep(0.5)


# --------------------------------------------
# Example usage:
if __name__ == "__main__":
    test_url = "https://www.wsj.com/politics/national-security/u-s-hitting-brakes-on-flow-of-arms-to-ukraine-980a71d1"
    unblocker = PaywallUnblocker(similarity_threshold=0.45, wait_time=1)
    final_html = unblocker.unblock_url(test_url)
    logger.info(f"Final archived page HTML length: {len(final_html)}")
    print(final_html)
