import os
import io
import time
import random
import logging
from typing import List, Optional

import requests
import torch
import pdfplumber
from sentence_transformers import SentenceTransformer, util
from transformers import pipeline  # For local summarization
from transformers import T5Tokenizer, T5ForConditionalGeneration

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

# A small list of user agents for demonstration.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_3_1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/102.0.5005.115 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0",
]


class PDFScrapper:
    """
    A class that:
      1) Stealthily fetches a PDF from a given URL.
      2) Extracts text and table data from each page.
      3) (NEW) Uses a small local LLM to extract up to N keywords from the general prompt.
      4) Ranks pages by the presence of these keywords, pre-selecting top K pages.
      5) Runs SentenceTransformer embedding-based filtering on those pages.
      6) Summarizes relevant pages with a local summarization model.
      7) Returns the merged text summary + any table data from the relevant pages.
    """

    def __init__(
            self,
            general_prompt: str,
            particular_prompt: str,
            model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
            similarity_threshold: float = 0.3,
            continuity_window: int = 0,
            summarization_model_name: str = "philschmid/bart-large-cnn-samsum",
            max_summary_length: int = 200,
            keyword_top_k_pages: int = 5,
            # The small LLM we use for keyword extraction (Flan-T5-Small for demonstration)
            keyword_llm_model: str = "google/flan-t5-small"
    ):
        """
        :param general_prompt: Broad question/topic you want to find in the PDF.
        :param particular_prompt: A more specific question/topic.
        :param model_name: A huggingface model name for SentenceTransformer embeddings.
        :param similarity_threshold: Keep pages whose max similarity >= this threshold.
        :param continuity_window: Number of page neighbors to keep around a relevant page.
        :param summarization_model_name: A local or HF model ID for summarization pipeline.
        :param max_summary_length: Control maximum length of each summary chunk (in tokens).
        :param keyword_top_k_pages: How many pages to keep after the keyword-based pre-selection.
        :param keyword_llm_model: A small local LLM for keyword extraction (default: Flan-T5-Small).
        """

        self.general_prompt = general_prompt
        self.particular_prompt = particular_prompt
        self.similarity_threshold = similarity_threshold
        self.continuity_window = continuity_window
        self.device = self._select_device()

        # Sentence embeddings for classification
        self.embedding_model = SentenceTransformer(model_name).to(self.device)
        self.general_prompt_emb = self.embedding_model.encode(
            self.general_prompt, convert_to_tensor=True, device=self.device
        )
        self.particular_prompt_emb = self.embedding_model.encode(
            self.particular_prompt, convert_to_tensor=True, device=self.device
        )

        # Local summarization pipeline
        self.summarizer = pipeline(
            "summarization",
            model=summarization_model_name,
            tokenizer=summarization_model_name,
            device=0 if (self.device.type == "cuda") else -1,
        )
        self.max_summary_length = max_summary_length

        # How many pages to keep based on keyword approach
        self.keyword_top_k_pages = keyword_top_k_pages

        # Small LLM for keyword extraction
        self.keyword_llm_tokenizer = T5Tokenizer.from_pretrained(keyword_llm_model)
        self.keyword_llm = T5ForConditionalGeneration.from_pretrained(keyword_llm_model).to(self.device)

    def _select_device(self) -> torch.device:
        """Selects the best available device (MPS, CUDA, or CPU)."""
        if torch.backends.mps.is_available():
            print("[INFO] Using MPS for Apple Silicon acceleration.")
            return torch.device("mps")
        elif torch.cuda.is_available():
            print("[INFO] Using CUDA for acceleration.")
            return torch.device("cuda")
        print("[INFO] No GPU detected, using CPU.")
        return torch.device("cpu")

    def _fetch_pdf_stealthily(self, url: str, max_retries: int = 3) -> Optional[bytes]:
        """
        Fetch the PDF file from a URL with basic stealth:
          - Random User-Agent
          - Random short delay
          - Optional retries if request fails
        Returns the PDF data as bytes, or None if all attempts fail.
        """
        for attempt in range(max_retries):
            try:
                time.sleep(random.uniform(1.0, 3.0))  # Random delay
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept-Language": "en-US,en;q=0.9",
                }
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                return response.content  # PDF content as bytes
            except requests.RequestException as e:
                logging.warning(f"[Attempt {attempt + 1}/{max_retries}] Failed to fetch {url}: {e}")
        logging.error(f"Failed to fetch {url} after {max_retries} attempts.")
        return None

    def process_resource(self, url: str) -> str:
        """
        Main method:
          1) Fetch PDF from 'url' stealthily.
          2) Parse each page's text and tables, build a combined text for each page.
          3) Generate up to 5 keywords from 'general_prompt' using a small local LLM.
          4) Pre-select top-K pages by counting how many keywords appear.
          5) Among those top-K pages, apply embedding-based filtering with general/particular prompts.
          6) Summarize relevant pages (and neighbors).
          7) Return the combined textual result.
        """
        pdf_data = self._fetch_pdf_stealthily(url)
        if not pdf_data:
            return ""

        # Extract page-wise text
        pages_text = self._extract_pages_text(pdf_data)
        if not pages_text:
            logging.info("No pages found or unable to extract text from the PDF.")
            return ""

        # 1) LLM-based keyword extraction
        keywords = self._extract_keywords_llm(self.general_prompt, max_keywords=5)
        print(f'PDF keywords: {keywords}')
        if not keywords:
            logging.info("No keywords could be extracted from the LLM approach.")
            return ""

        # 2) Pre-select pages via keywords
        selected_indices = self._select_pages_by_keywords(pages_text, keywords, top_k=self.keyword_top_k_pages)
        if not selected_indices:
            logging.info("No pages matched the simple keyword-based filter.")
            return ""

        # Create a sub-list of pages that passed the keyword filter
        sub_pages_text = [pages_text[idx] for idx in selected_indices]

        # 3) Among those top-K pages, do embedding-based filter
        relevant_sub_indices = self._filter_relevant_pages(sub_pages_text)
        if not relevant_sub_indices:
            logging.info("No pages found relevant after embedding filter.")
            return ""

        # Map sub-indices back to original page indices
        relevant_full_indices = [selected_indices[i] for i in relevant_sub_indices]

        # 4) Apply continuity logic
        keep_indices = self._apply_continuity(relevant_full_indices, len(pages_text))

        # 5) Summarize relevant pages
        final_text = self._summarize_pages(pages_text, keep_indices)
        return final_text

    def _extract_pages_text(self, pdf_data: bytes) -> List[str]:
        pages_text = []
        try:
            with io.BytesIO(pdf_data) as pdf_buffer:
                with pdfplumber.open(pdf_buffer) as pdf:
                    for page in pdf.pages:
                        # Extract text, tables, etc.
                        page_content = []

                        text = page.extract_text()
                        if text:
                            page_content.append(text)

                        tables = page.extract_tables()
                        for tbl in tables:
                            table_lines = []
                            for row in tbl:
                                line = " | ".join(str(cell).strip() for cell in row if cell)
                                table_lines.append(line)
                            table_text = "\n".join(table_lines)
                            if len(table_text) > 10:
                                page_content.append(table_text)

                        combined_page_text = "\n\n".join(page_content).strip()
                        pages_text.append(combined_page_text)
        except Exception as e:
            logging.error(f"Error reading PDF: {e}")
        return pages_text

    # ------------------------------------------------------------------
    # New: LLM-Based Keyword Extraction
    # ------------------------------------------------------------------
    def _extract_keywords_llm(self, prompt_text: str, max_keywords: int = 5) -> List[str]:
        """
        Use a small local LLM (e.g., Flan-T5) to extract up to N keywords from the prompt text.
        We'll do a zero-shot instruction prompt.
        """
        instruction = (
            f"Extract up to {max_keywords} distinct keywords from the following text:\n"
            f"---\n{prompt_text}\n---\n"
            "Respond with only the keywords, separated by commas."
        )

        # Tokenize and move input to correct device
        inputs = self.keyword_llm_tokenizer(
            instruction, return_tensors="pt", truncation=True
        ).to(self.device)  # 🔥 Move to MPS or CUDA

        # Generate
        with torch.no_grad():
            outputs = self.keyword_llm.generate(
                **inputs,
                max_new_tokens=50,
                num_beams=2,
                no_repeat_ngram_size=2
            )

        # Decode
        raw_text = self.keyword_llm_tokenizer.decode(outputs[0], skip_special_tokens=True)
        possible_keywords = [kw.strip().lower() for kw in raw_text.split(",") if kw.strip()]

        # Keep only unique ones, up to max_keywords
        unique_keywords = []
        for kw in possible_keywords:
            if kw not in unique_keywords and kw:
                unique_keywords.append(kw)

        return unique_keywords[:max_keywords]

    def _select_pages_by_keywords(self, pages_text: List[str], keywords: List[str], top_k: int) -> List[int]:
        """
        For each page, count how many of the given keywords it contains.
        Then pick the top_k pages with the highest count (only if count > 0).
        """
        counts = []
        for i, page in enumerate(pages_text):
            text_lower = page.lower()
            score = 0
            for kw in keywords:
                score += text_lower.count(kw)
            counts.append((i, score))

        # Sort by score descending, take top_k
        counts.sort(key=lambda x: x[1], reverse=True)
        top_pages = [idx for (idx, score) in counts[:top_k] if score > 0]
        return top_pages

    # ------------------------------------------------------------------
    # Existing Embedding-based Filtering
    # ------------------------------------------------------------------
    def _filter_relevant_pages(self, pages_text: List[str]) -> List[int]:
        """
        Among the 'selected' pages, embed each page, compute its max similarity
        to the general/particular prompts, and collect indices of pages
        that exceed self.similarity_threshold.
        """
        if not pages_text:
            return []

        # 🔥 Ensure embeddings run on the correct device
        pages_embeddings = self.embedding_model.encode(
            pages_text, convert_to_tensor=True, device=self.device
        ).to(self.device)

        sim_general = util.cos_sim(pages_embeddings, self.general_prompt_emb.to(self.device)).squeeze(dim=1)
        sim_partic = util.cos_sim(pages_embeddings, self.particular_prompt_emb.to(self.device)).squeeze(dim=1)

        # Example: max approach
        final_sim = torch.max(sim_general, sim_partic)

        relevant_indices = [
            i for i, score in enumerate(final_sim)
            if score.item() >= self.similarity_threshold
        ]
        return relevant_indices

    def _apply_continuity(self, relevant_indices: List[int], total_pages: int) -> List[int]:
        """
        Keep some neighboring pages around each relevant page for context,
        based on self.continuity_window.
        """
        keep_set = set()
        for i in relevant_indices:
            keep_set.add(i)
            for offset in range(1, self.continuity_window + 1):
                if i - offset >= 0:
                    keep_set.add(i - offset)
                if i + offset < total_pages:
                    keep_set.add(i + offset)
        return sorted(list(keep_set))

    def _summarize_pages(self, pages_text: List[str], keep_indices: List[int]) -> str:
        """
        Summarize each relevant page with a local summarization model.
        Combine the summarized pages into one final text.
        If a page is too large, we might chunk it for summarization.
        """
        summaries = []
        for idx in keep_indices:
            content = pages_text[idx]
            if not content:
                continue

            # Chunking by characters
            chunk_size = 1000
            chunks = [content[i: i + chunk_size] for i in range(0, len(content), chunk_size)]

            page_summary_parts = []
            for chunk in chunks:
                try:
                    result = self.summarizer(
                        chunk,
                        max_length=self.max_summary_length,
                        min_length=30,
                        do_sample=False
                    )
                    summary_text = result[0]["summary_text"]
                    page_summary_parts.append(summary_text)
                except Exception as e:
                    logging.warning(f"Summarization error on page {idx}, chunk: {e}")

            page_summary = "\n".join(page_summary_parts)
            page_summary_final = f"[PAGE {idx + 1}] {page_summary}"
            summaries.append(page_summary_final)

        final_text = "\n\n".join(summaries)
        return final_text


# Example Usage
if __name__ == "__main__":
    # For demonstration, we ask about sustainability and Google Deepmind
    scrapper = PDFScrapper(
        general_prompt="What can you tell me about Nvidia's consumer GPU market?",
        particular_prompt="RTX4090, Consumer GPU, Gaming ",
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        similarity_threshold=0.35,
        continuity_window=1,
        summarization_model_name="philschmid/bart-large-cnn-samsum",
        max_summary_length=300,
        keyword_top_k_pages=10,
        # Use Flan-T5-Small as a local LLM for keyword extraction
        keyword_llm_model="google/flan-t5-small"
    )
    url = "https://nvidianews.nvidia.com/_gallery/download_pdf/646e7438a1383555093ab633/"
    result = scrapper.process_resource(url)
    print("===== SCRAPED & SUMMARIZED PDF CONTENT =====")
    print(result)
