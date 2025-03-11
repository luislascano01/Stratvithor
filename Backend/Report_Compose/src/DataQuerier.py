import aiohttp
import asyncio
import logging
import json  # Import json module for pretty printing
from typing import List, Optional, Dict, Any

class DataQuerier:
    """
    DataQuerier is responsible for querying the SearchIntegrator API.
    It builds a payload matching the API's SearchRequest model and
    handles asynchronous calls, error checking, and response processing.
    """
    def __init__(
        self,
        general_prompt: str,
        focus_message: str,
        search_api_url: str,
        credentials: str = "./Credentials/Credentials.yaml",
        operating_path: str = "/tmp",
        llm_api_url: str = "http://localhost:11434/api/chat",
        cse_id: Optional[str] = None
    ):
        """
        Initializes DataQuerier.

        :param general_prompt: General search prompt.
        :param focus_message: The current prompt text; used as the particular_prompt.
        :param search_api_url: The URL of the SearchIntegrator API endpoint (/search).
        :param credentials: Credentials as a YAML or JSON string.
        :param operating_path: Path for temporary file operations.
        :param llm_api_url: URL for the LLM API.
        :param cse_id: Optional Custom Search Engine ID.
        """
        self.general_prompt = general_prompt
        self.focus_message = focus_message
        self.search_api_url = search_api_url
        self.credentials = credentials
        self.operating_path = operating_path
        self.llm_api_url = llm_api_url
        self.cse_id = cse_id
        self.query_result: Optional[Dict[str, Any]] = None
        self.processed_data: Optional[Dict[str, Any]] = None

        logging.info(f"🚀 DataQuerier initialized with API URL: {self.search_api_url}")

    async def fetch_data(self):
        """
        Makes an asynchronous POST request to the SearchIntegrator API.
        Constructs the payload as required by the API and checks the response.
        Raises an exception if the response status is not 200.
        """
        payload = {
            "credentials": self.credentials,
            "general_prompt": self.general_prompt,
            "particular_prompt": self.focus_message,
            "operating_path": self.operating_path,
            "llm_api_url": self.llm_api_url,
            "cse_id": self.cse_id
        }
        logging.info("🔍 Sending POST request to SearchIntegrator API...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.search_api_url, json=payload) as response:
                    if response.status == 200:
                        self.query_result = await response.json()
                        logging.info("✅ Successfully received response from API.")
                    else:
                        error_text = await response.text()
                        logging.error(f"❌ API request failed with status {response.status}: {error_text}")
                        raise Exception(
                            f"Failed to fetch data: Status {response.status}, Error: {error_text}"
                        )
        except Exception as e:
            logging.error(f"❌ Exception in fetch_data: {e}")
            raise Exception(f"Error during fetch_data: {e}")

    def process_data(self):
        """
        Processes the fetched API response.
        Here we simply pass the query_result as processed_data.
        Additional validation or transformation can be added if needed.
        """
        logging.info("ℹ️ Processing fetched data...")
        if self.query_result is None:
            logging.error("❌ No data fetched to process. Ensure fetch_data is called first.")
            raise ValueError("No data fetched. Run fetch_data first.")
        self.processed_data = self.query_result
        logging.info("✅ Data processing complete.")

    async def query_and_process(self):
        """
        Convenience method that wraps fetching and processing the API response.
        """
        logging.info("🚀 Starting query_and_process operation...")
        await self.fetch_data()
        self.process_data()
        logging.info("✅ query_and_process operation finished.")

    def get_processed_data(self) -> Dict[str, Any]:
        """
        Returns the processed data.
        Must be called after query_and_process.
        """
        if self.processed_data is None:
            logging.error("❌ Attempted to access processed data before processing.")
            raise ValueError("Data has not been processed yet. Call query_and_process first.")
        logging.info(f'✅ Processed data returned. Type: {type(self.processed_data)}')
        return self.processed_data

# Configure logging to output to the console.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    # Define the SearchIntegrator API URL and LLM API URL.
    search_api_url = "http://0.0.0.0:8383/search"
    llm_api_url = "http://localhost:11434/api/chat"

    # Credential YAML as a string.
    credential_yaml = "Credentials/Credentials.yaml"
    # Some comment

    # Example general prompt and focus message.
    general_prompt = "Explain in depth all you can about the company's business, including all company segments. You can create tables with the evolution of sales of all different relevant segments, quarterly NOI. Give all relevant information found on how the company is operating. This is the most important section, be as thorough as possible."
    focus_message = "Acer Technological Company"

    # Instantiate the DataQuerier with the above parameters.
    dq = DataQuerier(
        general_prompt=general_prompt,
        focus_message=focus_message,
        search_api_url=search_api_url,
        credentials=credential_yaml,
        operating_path="/tmp",
        llm_api_url=llm_api_url,
        cse_id=None  # Use this if you don't have a specific Custom Search Engine ID for this call.
    )

    try:
        # Execute the asynchronous query and processing.
        await dq.query_and_process()
        results = dq.get_processed_data()
        print("Search Results:")
        # Pretty print the JSON output with an indentation of 4 spaces.
        print(json.dumps(results, indent=4))
    except Exception as e:
        logging.error(f"Main method encountered an error: {e}")

if __name__ == '__main__':
    asyncio.run(main())