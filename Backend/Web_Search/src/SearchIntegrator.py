import logging
from typing import List, Dict, Optional
import re

from Backend.Web_Search.src.GoogleSearchCaller import GoogleSearchCaller
from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
from Backend.Web_Search.src.PDFScrapper import PDFScrapper
from Backend.Web_Search.src.QuerySynthesizer import QuerySynthesizer
from Credentials.CredentialManager import CredentialManager
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    def __init__(self, general_prompt: str, particular_prompt, cred_mngr: CredentialManager, operating_path: str):
        self.general_prompt = general_prompt
        self.particular_prompt = particular_prompt
        self.cred_mngr = cred_mngr
        self.g_api_key = cred_mngr.get_credential("API_Keys", "Google_Cloud")
        self.operating_dir_path = operating_path
        self.default_csd_id = cred_mngr.get_credential("Online_Tool_ID", "Custom_G_Search")
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

    def get_aggregated_response(self, llm_api_url: str, cse_id=None) -> List[Dict[str, object]]:
        if cse_id is None:
            cse_id = self.default_csd_id

        query_synth = QuerySynthesizer(llm_api_url)
        conjugated_search_prompt = self.get_composed_prompt()
        search_prompts = query_synth.generate_search_prompts(conjugated_search_prompt)
        print(f"Search prompts:\n")
        for i, search_prompt in enumerate(search_prompts):
             print(f'{i+1}. {search_prompt}')

        web_scrapper = HTMLArticleScrapper(self.general_prompt, self.particular_prompt)
        pdf_scrapper = PDFScrapper(self.general_prompt, self.particular_prompt)
        custom_scrappers = {"pdf": pdf_scrapper, "html": web_scrapper}

        matching_online_resources = self.get_web_articles_from_prompts(cse_id, search_prompts)

        def process_resource(matching_resource: Dict[str, object]) -> Optional[Dict[str, object]]:
            curr_url = matching_resource["url"]
            # Try to extract an extension from the URL.
            ext_match = re.search(r"\.([a-zA-Z0-9]+)([\?&]|$)", curr_url)
            if ext_match:
                extension = ext_match.group(1).lower()
            else:
                # If no explicit extension, use our helper to detect the type.
                extension = self.detect_resource_type(curr_url)

            # For DOCX, use the PDF scrapper.
            if extension == "docx":
                extension = "pdf"
            # Default to HTML if it's not a PDF.
            if extension not in ["pdf"]:
                extension = "html"

            scrapped_text = custom_scrappers[extension].process_resource(curr_url)
            # If no text was scrapped, skip this resource.
            if not scrapped_text.strip():
                return None

            matching_resource["scrapped_text"] = scrapped_text
            matching_resource["extension"] = extension
            return matching_resource

        processed_resources = []
        with ThreadPoolExecutor(max_workers=len(matching_online_resources)) as executor:
            future_to_resource = {
                executor.submit(process_resource, res): res for res in matching_online_resources
            }
            for future in as_completed(future_to_resource):
                try:
                    result = future.result()
                    if result is not None:
                        processed_resources.append(result)
                except Exception as e:
                    logging.error(f"Error processing resource: {e}")

        return processed_resources

    def get_web_articles_from_prompts(self, cse_id: str, search_prompts: List[str]) -> List[Dict[str, str]]:
        """
        Processes each search prompt concurrently and aggregates the results into one list.
        Duplicate URLs (based on 'url' field) are removed.

        :param cse_id: Custom Search Engine ID.
        :param search_prompts: List of search prompts generated from the composed query.
        :return: Aggregated list of search result dictionaries.
        """
        url_set = set()  # For fast duplicate checking
        aggregated_result = []

        def worker(prompt: str) -> List[Dict[str, str]]:
            # Create a new instance per thread to avoid potential thread-safety issues.
            g_searcher = GoogleSearchCaller(self.g_api_key, self.operating_dir_path)
            return g_searcher.run_custom_search(prompt, cse_id, num_results=3)

        # Use a ThreadPoolExecutor to run each prompt concurrently.
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
            conjugating_string = "\nIn our case the subject matter we are talking about is: "
            return self.general_prompt + conjugating_string + self.particular_prompt + " {" + self.general_prompt + "}"
        else:
            advanced_merged_prompt = self.get_intelligent_composed_prompt()
            return advanced_merged_prompt

    def get_intelligent_composed_prompt(self):
        raise NotImplementedError("This method is not implemented yet.")
