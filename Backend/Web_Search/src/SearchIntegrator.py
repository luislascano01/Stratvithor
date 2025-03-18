import logging
import time
from concurrent.futures import as_completed
from typing import List, Dict, Optional
import re

import torch.cuda

from Backend.Web_Search.src.GoogleSearchCaller import GoogleSearchCaller
from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
from Backend.Web_Search.src.PDFScrapper import PDFScrapper
from Backend.Web_Search.src.SummarizationTask import PrioritySummarizerQueue
from Backend.Web_Search.src.QuerySynthesizer import QuerySynthesizer
from Credentials.CredentialManager import CredentialManager

from concurrent.futures import ProcessPoolExecutor, wait, TimeoutError
import requests


def format_url(url: str) -> str:
    # Remove protocol (http://, https://) and any leading "www."
    cleaned = re.sub(r'^(https?://)?(www\.)?', '', url)

    # Extract the extension (if any) from the end of the cleaned URL.
    ext_match = re.search(r'\.([a-zA-Z0-9]+)$', cleaned)
    extension = ext_match.group(1) if ext_match else ''

    # Take up to the first 10 characters of the cleaned URL.
    short_url = cleaned[:10] if len(cleaned) > 10 else cleaned

    # Build the formatted string.
    return f"{short_url}---{('.' + extension) if extension else ''}"


def process_resource_subprocess_worker(general_prompt: str, particular_prompt: str, resource: Dict[str, object],
                                       scrapping_timeout: int) -> Optional[Dict[str, object]]:
    """
    Processes a single resource (given by a resource dictionary) by performing web scraping without GPU summarization.
    This function is designed to be pickle‑able by only taking basic data types as parameters.

    Parameters:
        general_prompt (str): The broad search query.
        particular_prompt (str): The specific query details.
        resource (Dict[str, object]): The resource dictionary (should contain at least a 'url' key and may contain others like title, snippet, etc.)
        scrapping_timeout (int): Timeout for scraping in seconds.

    Returns:
        Optional[Dict[str, object]]: A dictionary merging the original resource fields with keys "scrapped_text" and "extension",
                                     or None if scraping fails.
    """
    import re, logging
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
    from Backend.Web_Search.src.PDFScrapper import PDFScrapper

    # Use the full resource dictionary (preserving extra fields).
    # Ensure that a 'url' key exists.
    curr_url = resource.get("url")
    if not curr_url:
        logging.error("Resource missing URL.")
        return None

    # Create new scrapper instances.
    web_scrapper = HTMLArticleScrapper(general_prompt, particular_prompt, summarizer_obj=None)
    pdf_scrapper = PDFScrapper(general_prompt, particular_prompt, summarizer_obj=None)
    custom_scrappers = {"pdf": pdf_scrapper, "html": web_scrapper}

    # Determine resource extension.
    ext_match = re.search(r"\.([a-zA-Z0-9]+)([\?&]|$)", curr_url)
    if ext_match:
        ext = ext_match.group(1).lower()
        extension = "html" if ext == "aspx" else ext
    else:
        extension = "html"

    if extension == "docx":
        extension = "pdf"
    if extension not in ["pdf"]:
        extension = "html"

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            logging.debug(f"Submitting scraping task for URL: {curr_url}")
            future = executor.submit(custom_scrappers[extension].process_resource_raw, curr_url)
            scrapped_text = future.result(timeout=scrapping_timeout)
            logging.debug(f"Scraped text length for URL {curr_url}: {len(scrapped_text) if scrapped_text else 0}")
    except TimeoutError as te:
        logging.error(f"Scrapping resource timed out for {curr_url}: {te}")
        return None
    except Exception as e:
        logging.error(f"Failed to scrap resource for {curr_url}: {e}")
        return None

    if not scrapped_text or not scrapped_text.strip():
        logging.debug(f"No valid text scraped for {curr_url}")
        return None

    # Merge the original resource fields with the new fields.
    updated_resource = dict(resource)  # Preserve original keys (e.g., title, snippet, display_url)
    updated_resource["scrapped_text"] = scrapped_text
    updated_resource["extension"] = extension
    return updated_resource


class SearchIntegrator:
    def __init__(self, general_prompt: str, particular_prompt, cred_mngr: CredentialManager, operating_path: str,
                 worker_timeout: int = 100, scrapping_timeout: int = 100, summarizer_obj: 'SummarizerQueue' = None):
        """
        :param general_prompt: Broad search query or topic.
        :param particular_prompt: Specific query details.
        :param cred_mngr: CredentialManager for API keys.
        :param operating_path: Path for temporary file operations.
        :param worker_timeout: Timeout for worker tasks.
        :param scrapping_timeout: Timeout for scrapping each resource.
        :param summarizer_obj: (Optional) Shared SummarizerQueue instance. If None, a new instance is created
                               using the selected device (device=0 for CUDA, -1 otherwise).
        """
        self.general_prompt = general_prompt
        self.particular_prompt = particular_prompt
        self.cred_mngr = cred_mngr
        self.g_api_key = cred_mngr.get_credential("API_Keys", "Google_Cloud")
        self.operating_dir_path = operating_path
        self.default_csd_id = cred_mngr.get_credential("Online_Tool_ID", "Custom_G_Search")
        self.worker_timeout = worker_timeout
        self.scrapping_timeout = scrapping_timeout
        if self.g_api_key is None:
            logging.error("Google Cloud API key not found in passed credential manager (grouped credentials).")

        # Select device (0 for CUDA, -1 for CPU)
        try:
            self.device = 0 if torch.cuda.is_available() else -1
        except RuntimeError:
            logging.info("Cuda is not available. Using CPU.")
            self.device = -1

        # Instantiate SummarizerQueue if not provided.
        self.summarizer_obj = summarizer_obj if summarizer_obj is not None else PrioritySummarizerQueue(...)

    def detect_resource_type(self, url: str) -> str:
        """
        Attempts to detect the resource type of the URL by sending a HEAD request.
        If that fails, falls back to a GET request (streaming only a bit).
        Returns 'pdf', 'docx', or 'html'.
        """
        try:
            response = requests.head(url, allow_redirects=True, timeout=10)
            content_type = response.headers.get("Content-Type", "").lower()
            if "application/pdf" in content_type:
                return "pdf"
            elif ("application/vnd.openxmlformats-officedocument.wordprocessingml.document" in content_type or
                  "application/msword" in content_type):
                return "docx"
            else:
                return "html"
        except Exception as e:
            logging.warning(f"HEAD request failed for {url}: {e}. Falling back to GET request.")
            try:
                response = requests.get(url, stream=True, timeout=10)
                content_type = response.headers.get("Content-Type", "").lower()
                if "application/pdf" in content_type:
                    return "pdf"
                elif ("application/vnd.openxmlformats-officedocument.wordprocessingml.document" in content_type or
                      "application/msword" in content_type):
                    return "docx"
                else:
                    return "html"
            except Exception as e:
                logging.error(f"Failed to detect resource type for {url}: {e}")
                return "html"

    def _process_resource_subprocess(self, resource: Dict[str, object], scrapping_timeout: int) -> Optional[
        Dict[str, object]]:
        """
        Processes a single resource in a separate process for cancellation capability.
        This updated version only performs web scraping and returns the raw extracted text.
        GPU-based summarization is deferred to the aggregator (get_aggregated_response).

        Parameters:
            resource (Dict[str, object]): The resource dictionary containing at least a 'url' key.
            scrapping_timeout (int): The timeout in seconds for scraping the resource.

        Returns:
            Optional[Dict[str, object]]: The resource dictionary updated with 'scrapped_text' and 'extension',
                                         or None if processing failed or timed out.
        """
        import re
        import logging
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
        from Backend.Web_Search.src.PDFScrapper import PDFScrapper

        print(f"[DEBUG] Starting _process_resource_subprocess for URL: {resource.get('url')}")
        # Re-create the scrapper objects to avoid pickling issues.
        web_scrapper = HTMLArticleScrapper(self.general_prompt, self.particular_prompt, summarizer_obj=None)
        pdf_scrapper = PDFScrapper(self.general_prompt, self.particular_prompt, summarizer_obj=None)
        custom_scrappers = {"pdf": pdf_scrapper, "html": web_scrapper}

        curr_url = resource["url"]
        # Determine the resource extension.
        ext_match = re.search(r"\.([a-zA-Z0-9]+)([\?&]|$)", curr_url)
        if ext_match:
            ext = ext_match.group(1).lower()
            if ext == "aspx":
                extension = self.detect_resource_type(curr_url)
            else:
                extension = ext
        else:
            extension = self.detect_resource_type(curr_url)
        print(f"[DEBUG] Determined extension for URL {curr_url}: {extension}")

        # For DOCX, treat as PDF; default to HTML otherwise.
        if extension == "docx":
            extension = "pdf"
        if extension not in ["pdf"]:
            extension = "html"

        try:
            # Use a short-lived ThreadPoolExecutor to enforce the scrapping timeout.
            with ThreadPoolExecutor(max_workers=1) as executor:
                print(f"[DEBUG] Submitting scraping task for URL: {curr_url}")
                # Call process_resource_raw to perform scraping without GPU summarization.
                future = executor.submit(custom_scrappers[extension].process_resource_raw, curr_url)
                scrapped_text = future.result(timeout=scrapping_timeout)
                print(f"[DEBUG] Scraped text length for URL {curr_url}: {len(scrapped_text) if scrapped_text else 0}")
        except TimeoutError as te:
            print(f"[ERROR] Scrapping resource timed out for {curr_url}: {te}")
            return None
        except Exception as e:
            print(f"[ERROR] Failed to scrap resource for {curr_url}: {e}")
            return None

        # Validate and update the resource dictionary.
        if not scrapped_text or not scrapped_text.strip():
            print(f"[DEBUG] No valid text scraped for {curr_url}")
            return None
        if "archive.today" in scrapped_text[:40]:
            scrapped_text = ""
        resource["scrapped_text"] = scrapped_text
        resource["extension"] = extension
        print(f"[DEBUG] Finished _process_resource_subprocess for {curr_url}")
        return resource

    def get_aggregated_response(self, llm_api_url: str, cse_id: Optional[str] = None) -> List[Dict[str, object]]:
        """
        Aggregates search results by:
          1. Generating search prompts and retrieving online resource URLs.
          2. Concurrently scraping each resource to extract raw text (without GPU summarization).
          3. For each scraped resource, if the text is long, using chunk-based summarization (which returns a final string),
             otherwise using the asynchronous summarization method (which returns a SummarizationTask).
          4. Waiting for each asynchronous summarization task to complete and updating the resource with its summarized text.

        Parameters:
            llm_api_url (str): The URL endpoint for the LLM API used to generate search prompts.
            cse_id (Optional[str]): The Custom Search Engine ID for online searches. If None, the default CSE ID is used.

        Returns:
            List[Dict[str, object]]: A list of resource dictionaries, each updated with the summarized text.
        """
        logging.info(f"SearchIntegrator getting aggregated response using LLM @ {llm_api_url}")
        print("[DEBUG] Starting get_aggregated_response.")

        if cse_id is None:
            cse_id = self.default_csd_id
            print("[DEBUG] No CSE ID provided, using default CSE ID.")

        query_synth = QuerySynthesizer(llm_api_url)
        conj_search_prompt = self.get_composed_prompt()
        search_prompts = query_synth.generate_search_prompts(conj_search_prompt)

        logging.info("Search prompts:")
        for i, sp in enumerate(search_prompts):
            logging.info(f"{i + 1}. {sp}")
            print(f"[DEBUG] Generated search prompt {i + 1}: {sp}")
        logging.info("\n\n")
        print("[DEBUG] Completed generation of search prompts.")

        matching_online_resources = self.get_web_urls_from_prompts(cse_id, search_prompts)
        print(f"[DEBUG] Retrieved {len(matching_online_resources)} online resources.")
        if not matching_online_resources:
            logging.info("No matching online resources found.")
            return []

        processed_resources = []  # Will store tuples: (resource, summarization result)
        start_time = time.time()
        print("[DEBUG] Starting submission of scraping tasks.")

        with ProcessPoolExecutor(max_workers=len(matching_online_resources)) as executor:
            # Submit a scraping task for each resource, passing the full resource dictionary.
            future_to_res = {
                executor.submit(process_resource_subprocess_worker,
                                self.general_prompt,
                                self.particular_prompt,
                                res,  # pass the entire resource dictionary
                                self.scrapping_timeout): res
                for res in matching_online_resources
            }
            print(f"[DEBUG] Submitted {len(future_to_res)} scraping tasks.")

            try:
                for fut in as_completed(future_to_res, timeout=self.scrapping_timeout):
                    try:
                        result = fut.result()
                        if result is not None:
                            raw_text = result.get("scrapped_text", "")
                            if raw_text:
                                print(f"[DEBUG] Scraping task completed for URL: {result.get('url', 'Unknown')}.")
                                # If text is long, use chunk-based summarization; else, use async summarization.
                                if len(raw_text.split()) > 500:
                                    print("[DEBUG] Text is long (>500 words); using chunk-based summarization.")
                                    summary = self.summarizer_obj.summarize_in_chunks(
                                        text=raw_text,
                                        chunk_size=512,
                                        max_length=300,
                                        min_length=30,
                                        do_sample=False
                                    )
                                    # 'summary' is a final string.
                                    processed_resources.append((result, summary))
                                else:
                                    print("[DEBUG] Text is short; using async summarization.")
                                    task = self.summarizer_obj.summarize_async(
                                        text=raw_text,
                                        priority=10,
                                        max_length=300,
                                        min_length=30,
                                        do_sample=False
                                    )
                                    processed_resources.append((result, task))
                            else:
                                print("[DEBUG] Scraping task returned empty text.")
                        else:
                            print("[DEBUG] Scraping task returned None.")
                    except Exception as e:
                        logging.error(f"Error processing scraped resource: {e}")
                        print(f"[DEBUG] Exception while processing a scraping task: {e}")
            except TimeoutError:
                logging.warning(f"Global scraping timeout of {self.scrapping_timeout} seconds reached.")
                print(f"[DEBUG] Global scraping timeout reached after {self.scrapping_timeout} seconds.")

            for fut in future_to_res:
                if not fut.done():
                    fut.cancel()
                    logging.warning("Cancelling a scraping task that did not complete within the timeout.")
                    print("[DEBUG] Cancelling a pending scraping task.")

            executor.shutdown(wait=False, cancel_futures=True)
            elapsed = time.time() - start_time
            print(f"[DEBUG] All scraping tasks processed (or cancelled) in {elapsed:.2f} seconds.")

        # Process summarization results.
        for (res, summ_obj) in processed_resources:
            if isinstance(summ_obj, str):
                res["scrapped_text"] = summ_obj
                summary_preview = summ_obj[:60] if summ_obj else 'None'
                print(
                    f"[DEBUG] (Chunked) Summarization complete for URL: {res.get('url', 'Unknown')}. Summary (first 60 chars): {summary_preview}")
            else:
                print(f"[DEBUG] Waiting for summarization task for URL: {res.get('url', 'Unknown')}.")
                summ_obj.event.wait()
                res["scrapped_text"] = summ_obj.result
                summary_preview = summ_obj.result[:60] if summ_obj.result else 'None'
                print(
                    f"[DEBUG] Summarization complete for URL: {res.get('url', 'Unknown')}. Summary (first 60 chars): {summary_preview}")

        print(f"[DEBUG] get_aggregated_response finished processing {len(processed_resources)} resources.")
        return [res for (res, _) in processed_resources]

    def get_web_urls_from_prompts(self, cse_id: str, search_prompts: List[str], num_results: int = 7) -> List[
        Dict[str, str]]:
        """
        Processes each search prompt concurrently and aggregates the results into one list.

        This method concurrently processes multiple search prompts by using a ThreadPoolExecutor.
        For each prompt, it uses the GoogleSearchCaller to perform a custom search with the specified
        Custom Search Engine (CSE) ID and number of results. The results from each search are aggregated
        into a single list, with duplicate URLs (based on the 'url' field) removed.

        Parameters:
            cse_id (str): The Custom Search Engine ID to be used for the search.
            search_prompts (List[str]): A list of search query strings.
            num_results (int, optional): The number of search results to fetch per prompt. Defaults to 7.

        Returns:
            List[Dict[str, str]]: A list of search result dictionaries, each containing at least a 'url' key.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        url_set = set()
        aggregated_result = []

        def worker(prompt: str) -> List[Dict[str, str]]:
            g_searcher = GoogleSearchCaller(self.g_api_key, self.operating_dir_path)
            return g_searcher.run_custom_search(prompt, cse_id, num_results)

        with ThreadPoolExecutor(max_workers=len(search_prompts)) as executor:
            future_to_prompt = {executor.submit(worker, prompt): prompt for prompt in search_prompts}
            for future in as_completed(future_to_prompt):
                try:
                    results = future.result()
                    for curr_search_result in results:
                        if curr_search_result['url'] not in url_set:
                            url_set.add(curr_search_result['url'])
                            aggregated_result.append(curr_search_result)
                except Exception as e:
                    logging.error(f"Error processing prompt '{future_to_prompt[future]}': {e}")

        return aggregated_result

    def get_composed_prompt(self, simple=True) -> str:
        if simple:
            conj = "\nIn our case the subject matter we are talking about is: "
            return self.general_prompt + conj + self.particular_prompt + " {" + self.general_prompt + "}"
        else:
            advanced_merged_prompt = self.get_intelligent_composed_prompt()
            return advanced_merged_prompt

    def get_intelligent_composed_prompt(self):
        raise NotImplementedError("This method is not implemented yet.")
