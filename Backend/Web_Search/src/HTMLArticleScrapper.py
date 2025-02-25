import random
import time
import logging
from typing import List, Optional
import torch
import requests
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer, util

# A small list of user agents for demonstration.
# In reality, you might have a larger pool or load from an external file.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_3_1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/102.0.5005.115 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0",
]


class HTMLArticleScrapper:
    """
    A class that:
      1) Fetches HTML content from a given URL (with basic stealth tactics),
      2) Removes boilerplate tags,
      3) Extracts text blocks from <p>, <div>, and <table> elements,
      4) Uses sentence-transformer embeddings to filter out irrelevant text
         based on two prompts (general and particular).
    """

    def __init__(
            self,
            general_prompt: str,
            particular_prompt: str,
            model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
            similarity_threshold: float = 0.3,
            continuity_window: int = 1,
    ):
        """
        :param general_prompt: A broad question/topic you want to find in the article.
        :param particular_prompt: A more specific question/topic.
        :param model_name: A huggingface model name for SentenceTransformer embeddings.
        :param similarity_threshold: Keep paragraphs whose max similarity with either prompt exceeds this.
        :param continuity_window: Number of neighboring paragraphs to keep for context.
        """
        self.model_name = model_name
        self.device = self._select_device()
        self.model = SentenceTransformer(model_name).to(self.device)

        # Pre-embed the prompts for faster comparisons
        self.general_prompt = general_prompt
        self.particular_prompt = particular_prompt
        self.general_prompt_emb = self.model.encode(
            self.general_prompt, convert_to_tensor=True, device=self.device
        )
        self.particular_prompt_emb = self.model.encode(
            self.particular_prompt, convert_to_tensor=True, device=self.device
        )

        self.similarity_threshold = similarity_threshold
        self.continuity_window = continuity_window

    def _select_device(self) -> torch.device:
        """Selects the best available device (MPS, CUDA, or CPU)."""
        if torch.backends.mps.is_available():
            return torch.device("mps")
        elif torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    def _fetch_html_stealthily(self, url: str, max_retries: int = 3) -> Optional[str]:
        """
        Fetch the HTML content from a URL with basic stealth:
          - Random User-Agent
          - Random short delay
          - Optional retries if the request fails
        Returns the HTML content as a string, or None if all attempts fail.
        """
        for attempt in range(max_retries):
            try:
                # Random delay (you could refine or randomize further)
                time.sleep(random.uniform(1.0, 3.0))

                # Randomly pick a User-Agent
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept-Language": "en-US,en;q=0.9",
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                return response.text  # Successfully got the page
            except requests.RequestException as e:
                logging.warning(f"[Attempt {attempt + 1}/{max_retries}] Failed to fetch {url}: {e}")
                # Optionally implement backoff or handle HTTP codes differently

        logging.error(f"Failed to fetch {url} after {max_retries} attempts.")
        return None

    def process_resource(self, url: str) -> str:
        """
        Main entry point:
          1) Stealthily fetch the HTML at 'url'.
          2) Parse and remove boilerplate.
          3) Extract relevant text blocks (including from tables).
          4) Filter them by semantic similarity with the two prompts.
        Returns the extracted main article or an empty string if fetching fails.
        """
        html_content = self._fetch_html_stealthily(url)
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, "html.parser")
        self._remove_boilerplate(soup)

        text_blocks = self._extract_text_blocks(soup)
        if not text_blocks:
            logging.info("[INFO] No text blocks found, trying alternative extraction.")
            text_blocks = self._extract_alternative_text_blocks(soup)

        main_article = self._extract_main_article_from_blocks(text_blocks)
        return main_article

    def _remove_boilerplate(self, soup: BeautifulSoup):
        """
        Remove HTML tags that are typically not relevant to the article content.
        Add more tag names if needed (e.g., <header>, <form>, etc.).
        """
        for tag_name in ["nav", "footer", "aside", "script", "style", "form"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

    def _extract_text_blocks(self, soup: BeautifulSoup, min_length: int = 50) -> List[str]:
        """
        Extract text from <p> and <div> elements above certain length.
        Also includes text from tables as separate blocks.
        """
        blocks = []

        # Paragraphs
        for p in soup.find_all("p"):
            text = p.get_text(separator=" ", strip=True)
            if len(text) >= min_length:
                blocks.append(text)

        # If not enough paragraphs, also look for <div> blocks
        if len(blocks) < 5:
            for div in soup.find_all("div"):
                text = div.get_text(separator=" ", strip=True)
                if len(text) >= 100:  # higher threshold for div text
                    blocks.append(text)

        # Extract tables as text blocks
        table_texts = self._extract_tables_as_text(soup)
        blocks.extend(table_texts)

        return blocks

    def _extract_tables_as_text(self, soup: BeautifulSoup) -> List[str]:
        """
        Convert each <table> element into a string so that table data is also considered.
        """
        tables = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(" | ".join(cells))
            table_str = "\n".join(rows).strip()
            if len(table_str) > 30:
                # Exclude very short/empty tables
                tables.append(table_str)
        return tables

    def _extract_alternative_text_blocks(self, soup: BeautifulSoup) -> List[str]:
        """
        Fallback extraction: simply get all text from the page.
        """
        text = soup.get_text(separator=" ", strip=True)
        return [text] if text else []

    def _extract_main_article_from_blocks(self, text_blocks: List[str]) -> str:
        """
        1) Embed each block and compute similarity with the prompts.
        2) Retain blocks above self.similarity_threshold (using the higher of the two prompt similarities).
        3) Keep some neighbors for continuity.
        """
        if not text_blocks:
            return ""

        # Embed blocks
        block_embeddings = self.model.encode(text_blocks, convert_to_tensor=True, device=self.device)

        # Compare with both prompts
        sim_general = util.cos_sim(block_embeddings, self.general_prompt_emb).squeeze(dim=1)
        sim_partic = util.cos_sim(block_embeddings, self.particular_prompt_emb).squeeze(dim=1)

        # Give 10% more weight to particular prompt
        # (You can think of this as: final_score = sim_general + 1.1 * sim_partic)
        similarities = sim_general + 1.1 * sim_partic

        # Now apply the threshold check
        relevant_indices = [
            i for i, score in enumerate(similarities)
            if score.item() >= self.similarity_threshold
        ]
        if not relevant_indices:
            # No relevant blocks
            return ""

        # Keep neighbors for continuity
        keep_indices = set()
        for i in relevant_indices:
            keep_indices.add(i)
            for offset in range(1, self.continuity_window + 1):
                if i - offset >= 0:
                    keep_indices.add(i - offset)
                if i + offset < len(text_blocks):
                    keep_indices.add(i + offset)

        # Build final text, preserving order
        kept_blocks = [text_blocks[i] for i in sorted(keep_indices)]
        main_article = "\n\n".join(kept_blocks)
        return main_article


# Example usage:
if __name__ == "__main__":
    scrapper = HTMLArticleScrapper(
        general_prompt="I want to know EBIDTA and Performance indices of the company.",
        particular_prompt="Well Tower Inc.",
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        similarity_threshold=0.45,
        continuity_window=1
    )
    # Replace with any URL that you want to scrape
    url = "https://www.macrotrends.net/stocks/charts/WELL/Welltower/ebitda"
    article_text = scrapper.process_resource(url)
    print("===== EXTRACTED ARTICLE =====")
    print(article_text)
