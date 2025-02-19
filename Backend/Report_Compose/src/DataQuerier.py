import asyncio
import aiohttp
import re
from typing import List, Dict, Any


class DataQuerier:
    """
    Handles asynchronous querying of the Web_Search API, processes the JSON response,
    and prepares the extracted data for immediate use by the Integrator.
    """

    def __init__(self, previous_messages: List[str], focus_message: str, web_search_url: str):
        self.previous_messages = previous_messages
        self.focus_message = focus_message
        self.web_search_url = web_search_url
        self.query_result: Dict[str, Any] = {}

    async def fetch_data(self):
        """
        Makes an asynchronous request to Web_Search API and stores the response.
        """
        payload = {
            "previous_messages": self.previous_messages,
            "focus_message": self.focus_message
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.web_search_url, json=payload) as response:
                if response.status == 200:
                    self.query_result = await response.json()
                    if not self.verify_response(self.query_result):
                        raise ValueError("Invalid API response format")
                else:
                    raise Exception(f"Failed to fetch data: {response.status}")

    def verify_response(self, response: Dict[str, Any]) -> bool:
        """
        Validates the Web_Search API response structure.

        Returns:
            bool: True if response is valid, False otherwise.
        """

        # Required top-level keys
        required_keys = {"query", "timestamp", "data"}
        if not required_keys.issubset(response.keys()):
            print(f"❌ Missing required keys: {required_keys - response.keys()}")
            return False

        # Validate timestamp format (ISO 8601)
        timestamp_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        if not re.match(timestamp_pattern, response["timestamp"]):
            print(f"❌ Invalid timestamp format: {response['timestamp']}")
            return False

        # Validate "data" structure
        data = response.get("data", {})
        expected_data_types = {
            "text": list,
            "tables": list,
            "time_series": list,
            "images": list,
            "plotly_html": list,
            "pdfs": list,
            "videos": list,
            "audio": list,
            "csv": list
        }

        for key, expected_type in expected_data_types.items():
            if key in data and not isinstance(data[key], expected_type):
                print(f"❌ {key} should be of type {expected_type.__name__}, but got {type(data[key]).__name__}")
                return False

        # Validate URLs for all non-text resources
        url_fields = ["tables", "time_series", "images", "plotly_html", "pdfs", "videos", "audio", "csv"]
        url_pattern = r"^https?:\/\/[^\s]+$"  # Basic URL validation

        for key in url_fields:
            for item in data.get(key, []):
                if not isinstance(item, dict) or "source" not in item:
                    print(f"❌ Invalid structure in {key}: {item}")
                    return False
                if not re.match(url_pattern, item["source"]):
                    print(f"❌ Invalid URL in {key}: {item['source']}")
                    return False

        print("✅ Web_Search API response is valid.")
        return True

    def process_data(self):
        """
        Organizes the fetched data into structured attributes for easy access.
        """
        if not self.query_result:
            raise ValueError("No data fetched. Run fetch_data first.")

        data = self.query_result.get("data", {})

        # Directly extracted text (not URL-based)
        self.texts: List[Dict[str, Any]] = data.get("text", [])

        # URL-based resources (not stored as direct content)
        self.tables: List[str] = [table["source"] for table in data.get("tables", [])]
        self.time_series: List[str] = [ts["source"] for ts in data.get("time_series", [])]
        self.images: List[str] = [img["source"] for img in data.get("images", [])]
        self.plotly_html: List[str] = [plot["source"] for plot in data.get("plotly_html", [])]
        self.pdfs: List[str] = [pdf["source"] for pdf in data.get("pdfs", [])]
        self.videos: List[str] = [video["source"] for video in data.get("videos", [])]
        self.audio: List[str] = [audio["source"] for audio in data.get("audio", [])]
        self.csv_files: List[str] = [csv["source"] for csv in data.get("csv", [])]

    async def query_and_process(self):
        """
        Runs the entire query process asynchronously.
        """
        await self.fetch_data()
        self.process_data()

    def get_processed_data(self) -> Dict[str, Any]:
        """
        Returns the structured data in a dictionary format.
        """
        return {
            "texts": self.texts,  # Directly stored text data
            "tables": self.tables,
            "time_series": self.time_series,
            "images": self.images,
            "plotly_html": self.plotly_html,
            "pdfs": self.pdfs,
            "videos": self.videos,
            "audio": self.audio,
            "csv_files": self.csv_files
        }