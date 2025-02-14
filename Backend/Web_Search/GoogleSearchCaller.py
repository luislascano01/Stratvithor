import os
import re
import time
import random
import string
import logging
import datetime
import requests
from pathlib import Path
from typing import List, Dict, Optional, Union
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# Concurrency
from concurrent.futures import ThreadPoolExecutor, as_completed

# PDF parsing
try:
    import PyPDF2
    import pdfplumber

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# Optional advanced extraction libraries (install if needed)
try:
    import newspaper  # newspaper3k

    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False

try:
    import readability  # readability-lxml

    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:86.0) Gecko/20100101 Firefox/86.0",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.183 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.96 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
]

PROXIES = []

class GoogleSearchCaller:
    def __init__(
        self,
        download_dir: str = "downloaded_files",
        concurrency: int = 1,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
        use_proxies: bool = False,
    ):
        """
        :param download_dir: Directory path to store downloaded PDF (or other) files.
        :param concurrency: Number of concurrent threads to use for URL processing (1 = no concurrency).
        :param min_delay: Minimum delay (in seconds) before sending a request (anti-bot measure).
        :param max_delay: Maximum delay (in seconds) before sending a request (anti-bot measure).
        :param use_proxies: Whether to try rotating through a proxy list (if provided).
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.concurrency = concurrency
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.use_proxies = use_proxies

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )

    # ----------------------------------------------------------------------
    # NEW GOOGLE-SEARCH METHODS
    # ----------------------------------------------------------------------

    def build_query(self, base_term: str, keywords: List[str]) -> str:
        """
        Create a query from a base term + list of keywords, joined by OR.
        For example: "Coca Cola financial statements OR quarterly earnings OR annual report ..."
        """
        # You can adapt how you want queries to be joined (AND, OR, etc.)
        # or remove the OR logic if you'd prefer a single combined query.
        return " OR ".join([f"{base_term} {kw}" for kw in keywords])

    def run_custom_search(
        self,
        query: str,
        api_key: str,
        cse_id: str,
        num_results: int = 5
    ) -> List[Dict[str, str]]:
        """
        Perform a Google Custom Search (CSE) and return the raw 'items' from the JSON response.

        :param query: The query string to search for.
        :param api_key: Google API key
        :param cse_id:  Google Custom Search Engine ID
        :param num_results: Number of results to fetch (max 10 if using free tier).
        :return: A list of search result items (dictionaries with 'title', 'link', etc.)
        """
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "q": query,
            "key": api_key,
            "cx": cse_id,
            "num": num_results
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data.get("items", [])  # Will be a list of dict
        except requests.RequestException as e:
            logging.error(f"Error calling Google Custom Search: {e}", exc_info=True)
            return []

    def google_search_with_parse(
        self,
        base_term: str,
        keywords: List[str],
        api_key: str,
        cse_id: str,
        num_results: int = 5
    ) -> List[Dict]:
        """
        1) Build the query from 'base_term' + 'keywords'.
        2) Run the custom search.
        3) Extract the 'link' fields to get a list of URLs.
        4) Pass URLs to self.parse_urls(...) to download/parse each resource.
        5) Return the aggregated parse results.

        :return: A list of parse results (each is a dictionary with Main_Content, etc.)
        """
        query_str = self.build_query(base_term, keywords)
        search_items = self.run_custom_search(query_str, api_key, cse_id, num_results=num_results)

        # Extract URLs
        urls = [item["link"] for item in search_items if "link" in item]

        # Now parse all those URLs with the existing pipeline
        results = self.parse_urls(urls)
        return results

    # ----------------------------------------------------------------------
    # EXISTING DOWNLOAD / PARSE METHODS
    # ----------------------------------------------------------------------

    def parse_urls(self, urls: List[str]) -> List[Dict]:
        """
        Processes each URL in the list, returning a list of dictionaries
        with extracted data from the resource.

        :param urls: List of URLs to parse.
        :return: List of dictionaries with fields like:
          {
            "Title_Header": str,
            "URL": str,
            "File_resources": Optional[str],
            "Date_access": str,
            "Main_Content": Optional[str],
            "Tables": Optional[List],  # extracted tables, if any
            "Metadata": dict,          # domain, content length, etc.
          }
        """
        if self.concurrency > 1:
            return self._process_urls_concurrently(urls)
        else:
            results = []
            for url in urls:
                data = self._process_url(url)
                if data:
                    results.append(data)
            return results

    def _process_urls_concurrently(self, urls: List[str]) -> List[Dict]:
        results = []
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_to_url = {
                executor.submit(self._process_url, url): url for url in urls
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    data = future.result()
                    if data:
                        results.append(data)
                except Exception as e:
                    logging.error(f"Error processing {url}: {e}", exc_info=True)
        return results

    def _process_url(self, url: str) -> Optional[Dict]:
        # Simple delay to reduce request bursts
        time.sleep(random.uniform(self.min_delay, self.max_delay))

        if url.lower().endswith(".pdf"):
            return self._handle_pdf(url)
        else:
            return self._handle_html(url)

    def _handle_pdf(self, url: str) -> Optional[Dict]:
        if not PDF_AVAILABLE:
            logging.warning("PDF libraries not installed. Cannot process PDF.")
            return None

        date_access = datetime.datetime.now().isoformat()
        local_filename = self._download_file(url, extension=".pdf")
        if not local_filename:
            return None

        main_text = None
        tables = []

        # Attempt to extract text/tables from PDF
        try:
            with open(local_filename, "rb") as fp:
                reader = PyPDF2.PdfReader(fp)
                all_text = []
                for page_num in range(len(reader.pages)):
                    page_text = reader.pages[page_num].extract_text() or ""
                    all_text.append(page_text)
                main_text = "\n".join(all_text)

            # Attempt advanced text + table extraction with pdfplumber
            with pdfplumber.open(local_filename) as pdf:
                for page in pdf.pages:
                    extracted_tables = page.extract_tables()
                    if extracted_tables:
                        tables.extend(extracted_tables)
        except Exception as e:
            logging.error(f"PDF processing error for {url}: {e}", exc_info=True)
            return None

        main_content = self._extract_main_content(main_text) if main_text else None

        return {
            "Title_Header": os.path.basename(local_filename),
            "URL": url,
            "File_resources": local_filename,
            "Date_access": date_access,
            "Main_Content": main_content,
            "Tables": tables,
            "Metadata": {
                "Content_Length": len(main_text) if main_text else 0,
                "Downloaded_File": local_filename,
            },
        }

    def _handle_html(self, url: str) -> Optional[Dict]:
        date_access = datetime.datetime.now().isoformat()
        proxies = self._maybe_get_proxy()

        headers = {"User-Agent": random.choice(USER_AGENTS)}

        try:
            response = requests.get(url, headers=headers, timeout=10, proxies=proxies)
            response.raise_for_status()
            html_content = response.text
        except requests.RequestException as e:
            logging.error(f"Request failed for {url}: {e}", exc_info=True)
            return None

        page_title, main_text = self._advanced_html_extraction(url, html_content)
        if not main_text:
            soup = BeautifulSoup(html_content, "html.parser")
            page_title = page_title or (soup.title.string.strip() if soup.title else "No Title Found")
            all_text = soup.get_text(separator="\n")
            main_text = self._extract_main_content(all_text)

        soup = BeautifulSoup(html_content, "html.parser")
        tables = self._extract_html_tables(soup)

        parsed_url = urlparse(url)
        domain = parsed_url.netloc

        return {
            "Title_Header": page_title,
            "URL": url,
            "File_resources": None,
            "Date_access": date_access,
            "Main_Content": main_text,
            "Tables": tables,
            "Metadata": {
                "Domain": domain,
                "Content_Length": len(main_text),
            },
        }

    def _maybe_get_proxy(self) -> Optional[Dict[str, str]]:
        if self.use_proxies and PROXIES:
            chosen_proxy = random.choice(PROXIES)
            return {"http": chosen_proxy, "https": chosen_proxy}
        return None

    def _download_file(self, url: str, extension: str = ".pdf") -> Optional[str]:
        random_name = "".join(random.choices(string.ascii_letters + string.digits, k=12))
        filename = self.download_dir / f"{random_name}{extension}"

        proxies = self._maybe_get_proxy()
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        try:
            with requests.get(url, headers=headers, stream=True, timeout=15, proxies=proxies) as r:
                r.raise_for_status()
                with open(filename, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return str(filename)
        except requests.RequestException as e:
            logging.error(f"Download failed for {url}: {e}", exc_info=True)
            return None

    def _extract_main_content(self, text: str) -> str:
        possible_keywords = [
            r"\bintroduction\b", r"\babstract\b", r"\bcontent\b", r"\bconclusion\b",
            r"\bchapter\b", r"\bsection\b", r"\bbackground\b", r"\bstudy\b",
            r"\breferences\b", r"\bbibliography\b"
        ]
        combined_pattern = "(" + "|".join(possible_keywords) + ")"
        matches = [m.start() for m in re.finditer(combined_pattern, text, flags=re.IGNORECASE)]

        if not matches:
            return text[:3000]
        start_index = matches[0]
        chunk_length = 5000
        main_excerpt = text[start_index : start_index + chunk_length]
        return main_excerpt

    def _extract_html_tables(self, soup: BeautifulSoup) -> List[List[List[str]]]:
        all_tables = []
        found_tables = soup.find_all("table")
        for tbl in found_tables:
            rows_data = []
            rows = tbl.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                rows_data.append(cell_texts)
            if rows_data:
                all_tables.append(rows_data)
        return all_tables

    def _advanced_html_extraction(self, url: str, html_content: str) -> (Optional[str], Optional[str]):
        if NEWSPAPER_AVAILABLE:
            try:
                article = newspaper.Article(url=url)
                article.set_html(html_content)
                article.download_state = newspaper.article.ArticleDownloadState.SUCCESS
                article.parse()
                title = article.title.strip() if article.title else None
                text = article.text.strip() if article.text else None
                return (title, text)
            except Exception as e:
                logging.warning(f"newspaper3k parsing failed: {e}", exc_info=True)

        if READABILITY_AVAILABLE:
            try:
                from readability import Document
                doc = Document(html_content)
                summary_html = doc.summary()
                soup = BeautifulSoup(summary_html, "html.parser")
                title = doc.short_title().strip() if doc.short_title() else None
                text = soup.get_text(separator="\n").strip()
                return (title, text)
            except Exception as e:
                logging.warning(f"readability-lxml parsing failed: {e}", exc_info=True)

        return (None, None)

# ----------------------------------------------------------------------
# Example usage:
# ----------------------------------------------------------------------
if __name__ == "__main__":
    gsc = GoogleSearchCaller(
        download_dir="files",
        concurrency=2,
        min_delay=1.0,
        max_delay=3.0,
        use_proxies=False
    )

    # Suppose we want to look up 'Tesla' with some financial keywords:
    base_company_name = "Tesla"
    financial_keywords = [
        "financial statements",
        "quarterly earnings",
        "annual report",
        "SEC filings",
        "Annual Report 2024"
    ]

    # Provide your Google API key and CSE ID
    search_api_key = "YOUR_GOOGLE_API_KEY"
    cse_id = "YOUR_CUSTOM_SEARCH_ID"

    # This method will:
    # 1) Build a combined query from base term + keywords
    # 2) Call Google Custom Search
    # 3) Parse the returned URLs for content
    parse_results = gsc.google_search_with_parse(
        base_term=base_company_name,
        keywords=financial_keywords,
        api_key=search_api_key,
        cse_id=cse_id,
        num_results=5
    )

    # Print summarized results
    for idx, res in enumerate(parse_results, start=1):
        title = res.get("Title_Header", "No Title")
        url = res.get("URL", "No URL")
        content_snippet = (res.get("Main_Content") or "")[:250].replace("\n", " ")
        print(f"\n---- Result {idx} ----")
        print(f"Title: {title}")
        print(f"URL: {url}")
        print(f"Content snippet: {content_snippet}...")