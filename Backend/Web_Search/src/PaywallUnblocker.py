import time
import random
import urllib.parse
import logging

#import undetected_chromedriver as uc


from sentence_transformers import SentenceTransformer, util

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PaywallUnblocker:
    """
    A modular paywall unblocker class that currently uses Archive.ph to retrieve
    archived versions of articles. Future methods for additional providers can be added.

    Functionality:
      1. Launch an incognito browser (using undetected-chromedriver).
      2. Navigate to the archive.ph URL for a given target URL.
      3. Collect anchor elements (skipping any that exactly match the target URL).
      4. Use a SentenceTransformer to select the best matching link.
      5. Click the link to load the final archived page.
      6. Simulate human-like scrolling and text highlighting.
      7. Return the final page's HTML.
    """

    def __init__(
            self,
            model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
            similarity_threshold: float = 0.3,
            wait_time: int = 7,
            archive_provider: str = "archive.ph"
    ):
        """
        :param general_prompt: A broad query/topic for the article.
        :param particular_prompt: A more specific query/topic.
        :param model_name: SentenceTransformer model for matching anchor text.
        :param similarity_threshold: (Reserved for future use.)
        :param continuity_window: (Reserved for future use.)
        :param wait_time: Seconds to wait after actions (clicking, scrolling, etc.).
        :param archive_provider: Archive provider identifier (currently supports "archive.ph").
        """

        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.wait_time = wait_time
        self.archive_provider = archive_provider

        # Load transformer model for anchor text similarity
        self.transformer = SentenceTransformer(model_name)

        # Set up Chrome options (incognito mode, not headless to mimic real user)

        try:
            from selenium.webdriver.chrome.options import Options
            self.chrome_options = Options()
        except ImportError:
            print(f'Could not import Selenium. Please install Selenium.')
        self.chrome_options.add_argument("--incognito")
        # Uncomment the next line to run headless (might trigger additional checks)
        # self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    def unblock_url(self, target_url: str) -> str:
        """
        Main method that retrieves the archived HTML for the given target URL.

        :param target_url: The original article URL.
        :return: The final archived page's HTML.
        """
        # Currently, we only support archive.ph.
        if self.archive_provider == "archive.ph":
            return self._process_archive_ph(target_url)
        else:
            logger.error(f"Archive provider '{self.archive_provider}' not supported yet.")
            return ""

    def _process_archive_ph(self, target_url: str) -> str:
        """
        Process the URL using Archive.ph.
        """
        # Construct the Archive.ph URL by encoding the target URL.
        encoded_url = urllib.parse.quote_plus(target_url, safe=":/")
        archive_url = f"https://{self.archive_provider}/{encoded_url}"
        logger.info(f"Navigating to: {archive_url}")

        # Launch undetected-chromedriver with our options.
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
        except ImportError:
            print("Please install undetected_chromedriver")
            return ""

        driver = uc.Chrome(options=self.chrome_options)
        try:
            driver.get(archive_url)
            # Wait for the snapshot listing to appear.
            time.sleep(3)

            # Collect anchor elements and their text (skip any matching the target URL)
            anchors = driver.find_elements(By.TAG_NAME, "a")
            anchor_texts = []
            anchor_elements = []
            for a in anchors:
                txt = a.get_attribute("title")
                if not txt:
                    txt = a.text.strip()
                if txt and txt != target_url:
                    anchor_texts.append(txt)
                    anchor_elements.append(a)

            if not anchor_texts:
                logger.warning("No suitable anchor texts found. Returning current page HTML.")
                time.sleep(self.wait_time)
                return driver.page_source

            # Use the transformer to compute similarity
            target_emb = self.transformer.encode([target_url], convert_to_tensor=True)
            anchor_embs = self.transformer.encode(anchor_texts, convert_to_tensor=True)
            sims = util.cos_sim(anchor_embs, target_emb).squeeze(dim=1)
            best_idx = sims.argmax().item()
            best_anchor_text = anchor_texts[best_idx]
            logger.info(f"Best matching anchor text: '{best_anchor_text}'")

            best_anchor_element = anchor_elements[best_idx]

            # Click the best matching anchor link
            logger.info("Clicking on the best anchor link...")
            best_anchor_element.click()
            logger.info(f"Waiting {self.wait_time} seconds for final page to load...")
            time.sleep(self.wait_time)

            # Simulate human-like scrolling and text highlighting.
            self.simulate_human_like_actions(driver)

            return driver.page_source
        finally:
            driver.quit()



    def simulate_human_like_actions(self, driver, highlight: bool = True):
        """
        Simulate human-like browsing actions:
          1. Scroll fully down.
          2. Wait.
          3. Scroll fully up.
          4. Wait.
          5. Determine page height and scroll to the middle.
          6. Optionally highlight text in a middle paragraph.
        """
        # Scroll to bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # Scroll to top
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)

        # Retrieve page height and calculate the middle point
        page_height = driver.execute_script("return document.body.scrollHeight;")
        middle_y = page_height / 2
        logger.info(f"Page height: {page_height}, scrolling to middle: {middle_y}")

        # Scroll to the middle
        driver.execute_script(f"window.scrollTo(0, {middle_y});")
        time.sleep(2)
        try:
            from selenium.webdriver.common.by import By
        except ImportError:
            print("Please install Selenium.")
        # Optionally, highlight text in the middle paragraph
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
                time.sleep(2)


# --------------------------------------------
# Example usage:
if __name__ == "__main__":
    test_url = (
        "https://www.investors.com/news/technology/oracle-stock-earnings-preview-stargate-ai-deepseek/"
    )
    unblocker = PaywallUnblocker(
        similarity_threshold=0.45,
        wait_time=5
    )
    final_html = unblocker.unblock_url(test_url)
    logger.info(f"Final archived page HTML length: {len(final_html)}")
    print(final_html)
