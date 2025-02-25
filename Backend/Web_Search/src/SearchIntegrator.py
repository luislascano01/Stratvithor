import logging
from typing import List, Dict
import re

from Backend.Web_Search.src.GoogleSearchCaller import GoogleSearchCaller
from Backend.Web_Search.src.HTMLArticleScrapper import HTMLArticleScrapper
from Backend.Web_Search.src.PDFScrapper import PDFScrapper
from Backend.Web_Search.src.QuerySynthesizer import QuerySynthesizer
from Credentials.CredentialManager import CredentialManager


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

    def get_aggregated_response(self, llm_api_url: str, cse_id=None) -> List[Dict[str, object]]:
        if cse_id is None:
            cse_id = self.default_csd_id

        query_synth = QuerySynthesizer(llm_api_url)
        conjugated_search_prompt = self.get_composed_prompt()
        search_prompts = query_synth.generate_search_prompts(conjugated_search_prompt)

        web_scrapper = HTMLArticleScrapper(self.general_prompt, self.particular_prompt)
        pdf_scrapper = PDFScrapper(self.general_prompt, self.particular_prompt)

        custom_scrappers = {"pdf": pdf_scrapper, "html": web_scrapper}

        matching_online_resources = self.get_webpages_from_prompts(cse_id, search_prompts)

        for matching_resource in matching_online_resources:
            curr_url = matching_resource["url"]
            match = re.search(r"\.(pdf|html)([\?&]|$)", curr_url)
            if match:
                extension = match.group(1)  # captures 'pdf' or 'html'
                scrapped_text = custom_scrappers[extension].process_resource(curr_url)
                matching_resource["scrapped_text"] = scrapped_text
                matching_resource["extension"] = extension
            else:
                print(f"No supported extension found in URL: {format_url(url=curr_url)}")
                logging.warning(f"Skipping unsupported file type: {curr_url}")

    def get_webpages_from_prompts(self, cse_id: str, search_prompts: List[str]) -> List[Dict[str, str]]:
        url_set = set()  # Use set for O(1) lookup
        aggregated_result = []

        g_searcher = GoogleSearchCaller(self.g_api_key, self.operating_dir_path)

        for prompt in search_prompts:
            curr_search_results = g_searcher.run_custom_search(prompt, cse_id, num_results=3)
            for curr_search_result in curr_search_results:
                if curr_search_result['url'] not in url_set:
                    url_set.add(curr_search_result['url'])
                    aggregated_result.append(curr_search_result)
        return aggregated_result

    def get_composed_prompt(self, simple=True) -> str:
        if simple:
            conjugating_string = "\nIn our case the subject matter we are talking about is: "
            return self.general_prompt + conjugating_string + self.particular_prompt + " {" + self.general_prompt + "}"
        else:
            advanced_merged_prompt = self.get_intelligent_composed_propmpt()
            return advanced_merged_prompt

    def get_intelligent_composed_propmpt(self):
        raise NotImplementedError("This method is not implemented yet.")
