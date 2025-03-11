import logging
import time
from typing import List, Dict, Optional
import re

from Backend.Web_Search.src.GoogleSearchCaller import GoogleSearchCaller
from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
from Backend.Web_Search.src.PDFScrapper import PDFScrapper
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


class SearchIntegrator:
    def __init__(self, general_prompt: str, particular_prompt, cred_mngr: CredentialManager, operating_path: str,
                 worker_timeout=100, scrapping_timeout=100):
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
        This function is run inside a separate process for real cancellation capability.
        """
        import re
        import logging
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
        from Backend.Web_Search.src.PDFScrapper import PDFScrapper

        # Re-create the scrapper objects to avoid pickling issues with the main instance
        web_scrapper = HTMLArticleScrapper(self.general_prompt, self.particular_prompt)
        pdf_scrapper = PDFScrapper(self.general_prompt, self.particular_prompt)
        custom_scrappers = {"pdf": pdf_scrapper, "html": web_scrapper}

        curr_url = resource["url"]
        ext_match = re.search(r"\.([a-zA-Z0-9]+)([\?&]|$)", curr_url)
        if ext_match:
            ext = ext_match.group(1).lower()
            if ext == "aspx":
                extension = self.detect_resource_type(curr_url)
            else:
                extension = ext
        else:
            extension = self.detect_resource_type(curr_url)

        # For DOCX, use the PDF scrapper; default to HTML if not PDF.
        if extension == "docx":
            extension = "pdf"
        if extension not in ["pdf"]:
            extension = "html"

        try:
            # Summon a short-lived ThreadPool to apply the actual scrapper timeout.
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(custom_scrappers[extension].process_resource, curr_url)
                scrapped_text = future.result(timeout=scrapping_timeout)
        except TimeoutError as te:
            logging.error(f"Scrapping resource timed out for {curr_url}: {te}")
            return None
        except Exception as e:
            logging.error(f"Failed to scrap resource for {curr_url}: {e}")
            return None

        if not scrapped_text or not scrapped_text.strip():
            return None
        if "archive.today" in scrapped_text[:40]:
            scrapped_text = ""
        resource["scrapped_text"] = scrapped_text
        resource["extension"] = extension
        return resource

    def get_aggregated_response(self, llm_api_url: str, cse_id=None) -> List[Dict[str, object]]:
        if cse_id is None:
            cse_id = self.default_csd_id

        # Build search prompts
        query_synth = QuerySynthesizer(llm_api_url)
        conj_search_prompt = self.get_composed_prompt()
        search_prompts = query_synth.generate_search_prompts(conj_search_prompt)
        logging.info("Search prompts:")
        for i, sp in enumerate(search_prompts):
            logging.info(f"{i + 1}. {sp}")

        # Gather initial list of resources
        matching_online_resources = self.get_web_articles_from_prompts(cse_id, search_prompts)
        if not matching_online_resources:
            return []

        processed_resources = []
        start_time = time.time()

        with ProcessPoolExecutor(max_workers=len(matching_online_resources)) as executor:
            future_to_res = {
                executor.submit(self._process_resource_subprocess, res, self.scrapping_timeout): res
                for res in matching_online_resources
            }

            # Wait at most 120s for them to finish
            done, not_done = wait(future_to_res.keys(), timeout=150)
            elapsed = time.time() - start_time
            if not_done:
                logging.warning(f"2-minute global timeout at {elapsed:.2f}s. Killing leftover processes.")
                # 1) Cancel the not_done futures so we ignore their results
                for fut in not_done:
                    fut.cancel()
                # 2) forcibly kill all worker processes that haven't finished
                for pid, proc in executor._processes.items():
                    try:
                        proc.terminate()  # or proc.kill()
                    except Exception as kill_ex:
                        logging.error(f"Error forcibly terminating process {pid}: {kill_ex}")

                # now forcibly shutdown the executor
                executor.shutdown(wait=False, cancel_futures=True)

            # Collect results from finished tasks
            for fut in done:
                if not fut.cancelled():
                    try:
                        result = fut.result()
                        if result is not None:
                            processed_resources.append(result)
                    except Exception as e:
                        logging.error(f"Error fetching result: {e}")

        return processed_resources

    def get_web_articles_from_prompts(self, cse_id: str, search_prompts: List[str], num_results=7) -> List[
        Dict[str, str]]:
        """
        Processes each search prompt concurrently and aggregates the results into one list.
        Duplicate URLs (based on 'url' field) are removed.
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
