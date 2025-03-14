import re
import random
import time
import logging
from typing import List, Optional
import torch
import requests
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer, util
from transformers import pipeline

from Backend.Web_Search.src.PaywallUnblocker import PaywallUnblocker

# A small list of user agents for demonstration.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_3_1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/102.0.5005.115 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0",
]


class HTMLArticleScrapper:
    def __init__(
            self,
            general_prompt: str,
            particular_prompt: str,
            summarizer_obj,  # New parameter for shared summarizer
            model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
            similarity_threshold: float = 0.3,
            continuity_window: int = 1,
            summarization_model_name: str = "philschmid/bart-large-cnn-samsum",
            max_summary_length: int = 200,
            max_tokens_for_article: int = 600
    ):
        """
        :param general_prompt: Broad topic/question for extraction.
        :param particular_prompt: Specific query/focus.
        :param summarizer_obj: Shared SummarizerQueue instance to queue GPU summarization tasks.
        :param model_name: HuggingFace SentenceTransformer model used for embeddings.
        :param similarity_threshold: Minimum similarity threshold to select relevant text blocks.
        :param continuity_window: Number of neighboring blocks to retain for context.
        :param summarization_model_name: Model name for the summarization pipeline (not used locally anymore).
        :param max_summary_length: Maximum token length for each summarization chunk.
        :param max_tokens_for_article: Token count threshold beyond which summarization is applied.
        """
        self.model_name = model_name
        self.device = self._select_device()
        self.model = SentenceTransformer(model_name).to(self.device)
        self.general_prompt = general_prompt
        self.particular_prompt = particular_prompt
        self.general_prompt_emb = self.model.encode(general_prompt, convert_to_tensor=True, device=self.device)
        self.particular_prompt_emb = self.model.encode(particular_prompt, convert_to_tensor=True, device=self.device)
        self.similarity_threshold = similarity_threshold
        self.continuity_window = continuity_window
        # Use the passed summarizer object.
        self.summarizer_obj = summarizer_obj
        self.max_summary_length = max_summary_length
        self.max_tokens_for_article = max_tokens_for_article

    def _select_device(self) -> torch.device:
        if torch.backends.mps.is_available():
            return torch.device("mps")
        elif torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    def _fetch_html_stealthily(self, url: str, max_retries: int = 3) -> Optional[str]:
        for attempt in range(max_retries):
            try:
                time.sleep(random.uniform(1.0, 3.0))
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept-Language": "en-US,en;q=0.9",
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                html = response.text
                if len(html.strip()) < 500:
                    logging.warning(
                        f"[Attempt {attempt + 1}/{max_retries}] HTML too short (length {len(html.strip())}); "
                        "might be paywalled."
                    )
                    continue
                return html
            except requests.RequestException as e:
                logging.warning(f"[Attempt {attempt + 1}/{max_retries}] Failed to fetch {url}: {e}")

        logging.error(f"Failed to fetch {url} via normal HTTP after {max_retries} attempts.")
        logging.info("Falling back to PaywallUnblocker method.")
        fallback_unblocker = PaywallUnblocker(wait_time=5)
        return fallback_unblocker.unblock_url(url)

    def process_resource(self, url: str) -> str:
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
        cleaned_article = self._clean_text(main_article)

        # >>> Summarize if needed <<<
        final_text = self._summarize_if_long(cleaned_article, self.max_tokens_for_article)

        return final_text

    def _remove_boilerplate(self, soup: BeautifulSoup):
        for tag_name in ["nav", "footer", "aside", "script", "style", "form"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

    def _extract_text_blocks(self, soup: BeautifulSoup, min_length: int = 50) -> List[str]:
        blocks = []
        # Extract paragraphs
        for p in soup.find_all("p"):
            text = p.get_text(separator=" ", strip=True)
            if len(text) >= min_length:
                blocks.append(text)
        # If not enough paragraphs, look for div blocks
        if len(blocks) < 5:
            for div in soup.find_all("div"):
                text = div.get_text(separator=" ", strip=True)
                if len(text) >= 100:
                    blocks.append(text)
        # Extract table data
        table_texts = self._extract_tables_as_text(soup)
        blocks.extend(table_texts)
        return blocks

    def _extract_tables_as_text(self, soup: BeautifulSoup) -> List[str]:
        tables = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(" | ".join(cells))
            table_str = "\n".join(rows).strip()
            if len(table_str) > 30:
                tables.append(table_str)
        return tables

    def _extract_meta_content(self, soup: BeautifulSoup) -> List[str]:
        meta_texts = []
        meta_names = {"description", "og:description", "twitter:description"}
        for meta in soup.find_all("meta"):
            name_attr = meta.get("name", "").lower()
            prop_attr = meta.get("property", "").lower()
            if name_attr in meta_names or prop_attr in meta_names:
                content = meta.get("content", "").strip()
                if content:
                    meta_texts.append(content)
        return meta_texts

    def _extract_alternative_text_blocks(self, soup: BeautifulSoup) -> List[str]:
        # Try to extract meta tag content first.
        meta_texts = self._extract_meta_content(soup)
        if meta_texts:
            return meta_texts
        # Fallback: get all text from the page.
        text = soup.get_text(separator=" ", strip=True)
        return [text] if text else []

    def _extract_main_article_from_blocks(self, text_blocks: List[str]) -> str:
        if not text_blocks:
            return ""
        block_embeddings = self.model.encode(text_blocks, convert_to_tensor=True, device=self.device)
        sim_general = util.cos_sim(block_embeddings, self.general_prompt_emb).squeeze(dim=1)
        sim_partic = util.cos_sim(block_embeddings, self.particular_prompt_emb).squeeze(dim=1)

        # Weighted sum: can adjust weighting if desired
        similarities = sim_general + 3 * sim_partic

        relevant_indices = [
            i for i, score in enumerate(similarities)
            if score.item() >= self.similarity_threshold
        ]
        if not relevant_indices:
            return ""

        # Keep some context lines around each relevant block
        keep_indices = set()
        for i in relevant_indices:
            keep_indices.add(i)
            for offset in range(1, self.continuity_window + 1):
                if i - offset >= 0:
                    keep_indices.add(i - offset)
                if i + offset < len(text_blocks):
                    keep_indices.add(i + offset)

        kept_blocks = [text_blocks[i] for i in sorted(keep_indices)]
        main_article = "\n\n".join(kept_blocks)
        main_article = self.remove_redundant_lines(main_article, n=6)
        return main_article

    def remove_redundant_lines(self, text: str, n=6) -> str:
        seen_ngrams = set()
        filtered_lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            words = line.split()
            if len(words) < n:
                # Keep short lines once, to avoid losing them entirely
                if line in filtered_lines:
                    continue
                filtered_lines.append(line)
                continue
            ngrams = {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}
            if any(ng in seen_ngrams for ng in ngrams):
                continue
            seen_ngrams.update(ngrams)
            filtered_lines.append(line)
        return "\n".join(filtered_lines)

    def _clean_text(self, text: str) -> str:
        cleaned_lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Remove unwanted characters (allow a-z, A-Z, 0-9, punctuation, whitespace)
            line = re.sub(r"[^a-zA-Z0-9\s.,!?;:\-()]+", "", line)
            line = re.sub(r"\s+", " ", line).strip()

            # Check word count
            words = line.split()
            if len(words) < 3:
                continue

            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    # -------------------------------------------------------------------------
    # Summarize if final text is longer than 'max_tokens_for_article'
    # -------------------------------------------------------------------------
    def _summarize_if_long(self, text: str, max_tokens: int = 600) -> str:
        def count_tokens(s: str) -> int:
            return len(s.split())

        if count_tokens(text) <= max_tokens:
            return text

        chunk_size = 700
        words = text.split()
        chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
        summarized_chunks = []
        for chunk in chunks:
            try:
                # Use the shared summarizer_obj to process the chunk.
                result = self.summarizer_obj.summarize(chunk, max_length=self.max_summary_length, min_length=30, do_sample=False)
                summarized_chunks.append(result)
            except Exception as e:
                logging.warning(f"Summarization error: {e}")
                summarized_chunks.append(chunk)
        merged_summary = "\n".join(summarized_chunks)
        if count_tokens(merged_summary) > max_tokens:
            try:
                merged_summary = self.summarizer_obj.summarize(merged_summary, max_length=self.max_summary_length, min_length=30, do_sample=False)
            except Exception as e:
                logging.warning(f"Final summarization pass error: {e}")
        return merged_summary[:100000]

# Example usage:
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scrapper = HTMLArticleScrapper(
        general_prompt="Financial Performance",
        particular_prompt="Oracle Earnings",
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        similarity_threshold=0.45,
        continuity_window=3,
        summarization_model_name="philschmid/bart-large-cnn-samsum",
        max_summary_length=200,
        max_tokens_for_article=600
    )

    url = "https://www.wsj.com/politics/national-security/u-s-hitting-brakes-on-flow-of-arms-to-ukraine-980a71d1"
    article_text = scrapper.process_resource(url)

    print("===== EXTRACTED (SUMMARIZED IF >600 TOKENS) =====")
    print(article_text)