import logging
import time
from concurrent.futures import as_completed, ProcessPoolExecutor, TimeoutError
from typing import List, Dict, Optional
import re
import requests
import torch

from Backend.Web_Search.src.GoogleSearchCaller import GoogleSearchCaller
from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
from Backend.Web_Search.src.PDFScrapper import PDFScrapper
from Backend.Web_Search.src.QuerySynthesizer import QuerySynthesizer
from Credentials.CredentialManager import CredentialManager

# Import the single‑GPU summarizer service
from Backend.Web_Search.src.SummarizationTask import SingleGPUSummarizerService


def format_url(url: str) -> str:
    # Remove protocol (http://, https://) and any leading "www."
    cleaned = re.sub(r'^(https?://)?(www\.)?', '', url)
    # Extract the extension (if any) from the end of the cleaned URL.
    ext_match = re.search(r'\.([a-zA-Z0-9]+)$', cleaned)
    extension = ext_match.group(1) if ext_match else ''
    # Take up to the first 10 characters of the cleaned URL.
    short_url = cleaned[:10] if len(cleaned) > 10 else cleaned
    return f"{short_url}---{('.' + extension) if extension else ''}"


def process_resource_subprocess_worker(general_prompt: str, particular_prompt: str,
                                       resource: Dict[str, object],
                                       scrapping_timeout: int) -> Optional[Dict[str, object]]:
    """
    Processes a single resource (given by a resource dictionary) by performing web scraping
    without GPU summarization. It returns the original resource dictionary updated with
    the scraped text and resource extension.
    """
    import re, logging
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
    from Backend.Web_Search.src.PDFScrapper import PDFScrapper

    curr_url = resource.get("url")
    if not curr_url:
        logging.error("Resource missing URL.")
        return None

    # Create new scrapper instances.
    web_scrapper = HTMLArticleScrapper(general_prompt, particular_prompt, summarizer_obj=None)
    pdf_scrapper = PDFScrapper(general_prompt, particular_prompt, summarizer_obj=None)
    custom_scrappers = {"pdf": pdf_scrapper, "html": web_scrapper}

    # Determine the resource extension.
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

    updated_resource = dict(resource)
    updated_resource["scrapped_text"] = scrapped_text
    updated_resource["extension"] = extension
    return updated_resource


class SearchIntegrator:
    def __init__(self, general_prompt: str, particular_prompt, cred_mngr: CredentialManager,
                 operating_path: str, worker_timeout: int = 100, scrapping_timeout: int = 100,
                 summarizer_obj: Optional[SingleGPUSummarizerService] = None):  # UPDATED type hint
        """
        :param general_prompt: Broad search query or topic.
        :param particular_prompt: Specific query details.
        :param cred_mngr: CredentialManager for API keys.
        :param operating_path: Path for temporary file operations.
        :param worker_timeout: Timeout for worker tasks.
        :param scrapping_timeout: Timeout for scraping each resource.
        :param summarizer_obj: (Optional) Shared summarization service instance.
                              If None, a new SingleGPUSummarizerService is instantiated.
        """
        self.general_prompt = general_prompt
        self.particular_prompt = particular_prompt
        self.cred_mngr = cred_mngr
        self.g_api_key = cred_mngr.get_credential("API_Keys", "Google_Cloud")
        self.operating_dir_path = operating_path
        self.default_csd_id = cred_mngr.get_credential("Online_Tool_ID", "Custom_G_Search")
        self.worker_timeout = worker_timeout
        self.scrapping_timeout = scrapping_timeout
        self.global_timeout = 500
        if self.g_api_key is None:
            logging.error("Google Cloud API key not found in passed credential manager (grouped credentials).")

        try:
            self.device = 0 if torch.cuda.is_available() else -1
            logging.info(f'CUDA is available: {torch.cuda.is_available()}')
        except RuntimeError:
            logging.info("Cuda is not available. Using CPU.")
            self.device = -1

        # Instantiate the single-GPU summarizer service if not provided.
        self.summarizer_service = summarizer_obj if summarizer_obj is not None else SingleGPUSummarizerService(device=self.device)  # UPDATED

    def detect_resource_type(self, url: str) -> str:
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

    def _process_resource_subprocess(self, resource: Dict[str, object],
                                      scrapping_timeout: int) -> Optional[Dict[str, object]]:
        # (Same as the process_resource_subprocess_worker function)
        import re
        import logging
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
        from Backend.Web_Search.src.PDFScrapper import PDFScrapper

        print(f"[DEBUG] Starting _process_resource_subprocess for URL: {resource.get('url')}")
        web_scrapper = HTMLArticleScrapper(self.general_prompt, self.particular_prompt, summarizer_obj=None)
        pdf_scrapper = PDFScrapper(self.general_prompt, self.particular_prompt, summarizer_obj=None)
        custom_scrappers = {"pdf": pdf_scrapper, "html": web_scrapper}

        curr_url = resource["url"]
        ext_match = re.search(r"\.([a-zA-Z0-9]+)([\?&]|$)", curr_url)
        if ext_match:
            ext = ext_match.group(1).lower()
            extension = self.detect_resource_type(curr_url) if ext == "aspx" else ext
        else:
            extension = self.detect_resource_type(curr_url)
        print(f"[DEBUG] Determined extension for URL {curr_url}: {extension}")

        if extension == "docx":
            extension = "pdf"
        if extension not in ["pdf"]:
            extension = "html"

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                print(f"[DEBUG] Submitting scraping task for URL: {curr_url}")
                future = executor.submit(custom_scrappers[extension].process_resource_raw, curr_url)
                scrapped_text = future.result(timeout=scrapping_timeout)
                print(f"[DEBUG] Scraped text length for URL {curr_url}: {len(scrapped_text) if scrapped_text else 0}")
        except TimeoutError as te:
            print(f"[ERROR] Scrapping resource timed out for {curr_url}: {te}")
            return None
        except Exception as e:
            print(f"[ERROR] Failed to scrap resource for {curr_url}: {e}")
            return None

        if not scrapped_text or not scrapped_text.strip():
            print(f"[DEBUG] No valid text scraped for {curr_url}")
            return None

        resource["scrapped_text"] = scrapped_text
        resource["extension"] = extension
        print(f"[DEBUG] Finished _process_resource_subprocess for {curr_url}")
        return resource

    def get_aggregated_response(self, llm_api_url: str,
                                cse_id: Optional[str] = None) -> List[Dict[str, object]]:
        """
        Aggregates search results by generating search prompts, scraping online resources,
        and then using the single-GPU summarizer service to summarize the scraped text.
        Returns whatever resources it found after 45 seconds (hard limit).
        """
        logging.info(f"⌛️ SearchIntegrator getting aggregated response using LLM @ {llm_api_url}")
        print("[DEBUG] Starting get_aggregated_response.")

        if cse_id is None:
            cse_id = self.default_csd_id
            print("[DEBUG] No CSE ID provided, using default CSE ID.")
            logging.error("❌ No CSE ID provided, using default CSE ID.")

        query_synth = QuerySynthesizer(llm_api_url)
        conj_search_prompt = self.get_composed_prompt()
        search_prompts = query_synth.generate_search_prompts(conj_search_prompt)

        logging.info("Search prompts:")
        for i, sp in enumerate(search_prompts):
            logging.info(f"{i + 1}. {sp}")
            print(f"[DEBUG] Generated search prompt {i + 1}: {sp}")
        logging.info("\n\n")
        print("[DEBUG] Completed generation of search prompts.")

        matching_online_resources = self.get_web_urls_from_prompts(cse_id, search_prompts, num_results=3)
        print(f'URLs found:\n')
        for i, resource in enumerate(matching_online_resources):
            print(f"{i}: {resource['url']}")
        print(f"[DEBUG] Retrieved {len(matching_online_resources)} online resources.")
        if not matching_online_resources:
            logging.info("No matching online resources found.")
            return []

        processed_resources = []
          # Hard limit in seconds
        start_time = time.time()
        print("[DEBUG] Starting submission of scraping tasks.")

        with ProcessPoolExecutor(max_workers=16) as executor:
            future_to_res = {
                executor.submit(process_resource_subprocess_worker,
                                self.general_prompt,
                                self.particular_prompt,
                                res,
                                self.scrapping_timeout): res
                for res in matching_online_resources
            }
            print(f"[DEBUG] Submitted {len(future_to_res)} scraping tasks.")

            try:
                # Use the global timeout here
                for fut in as_completed(future_to_res, timeout=self.global_timeout):
                    # Check if our global time limit is reached before processing further
                    if time.time() - start_time >= self.global_timeout:
                        print("[DEBUG] Global timeout reached, breaking out of loop.")
                        break

                    try:
                        result = fut.result()
                        if result is not None:
                            raw_text = result.get("scrapped_text", "")
                            if raw_text:
                                print(f"[DEBUG] Scraping task completed for URL: {result.get('url', 'Unknown')}.")
                                print(f'Raw text: \n {raw_text}')
                                print("\n\n")
                                # Submit the scraped text to the single-GPU summarizer service.
                                req_id = self.summarizer_service.submit_request(
                                    raw_text,
                                    priority=10,
                                    max_length=1200,
                                    min_length=30,
                                    do_sample=False
                                )
                                # Wait for the summarization response.
                                resp = self.summarizer_service.get_response(req_id, timeout=120)
                                if resp.error:
                                    logging.error(
                                        f"Summarization error for URL {result.get('url', 'Unknown')}: {resp.error}")
                                    result["scrapped_text"] = "Web Scraping Error - Information must be accessed manually"
                                else:
                                    result["scrapped_text"] = resp.summary_text
                                processed_resources.append(result)
                            else:
                                print("[DEBUG] Scraping task returned empty text.")
                        else:
                            print("[DEBUG] Scraping task returned None.")
                    except Exception as e:
                        logging.error(f"Error processing scraped resource: {e}")
                        print(f"[DEBUG] Exception while processing a scraping task: {e}")
            except TimeoutError:
                logging.warning(f"Global scraping timeout of {self.global_timeout} seconds reached.")
                print(f"[DEBUG] Global scraping timeout reached after {self.global_timeout} seconds.")

            # Cancel any remaining futures
            for fut in future_to_res:
                if not fut.done():
                    fut.cancel()
                    logging.warning("Cancelling a scraping task that did not complete within the timeout.")
                    print("[DEBUG] Cancelling a pending scraping task.")

            executor.shutdown(wait=False, cancel_futures=True)
            elapsed = time.time() - start_time
            print(f"[DEBUG] All scraping tasks processed (or cancelled) in {elapsed:.2f} seconds.")

        print(f"[DEBUG] get_aggregated_response finished processing {len(processed_resources)} resources.")
        return processed_resources

    def get_web_urls_from_prompts(self, cse_id: str, search_prompts: List[str], num_results: int = 5) -> List[Dict[str, str]]:
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

