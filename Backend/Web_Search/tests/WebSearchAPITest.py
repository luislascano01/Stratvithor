import os
import http.client
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from Backend.Web_Search.src.WebSearchAPI import app


class WebSearchAPITest(unittest.TestCase):

    def setUp(self):
        """
        Load the credentials from the Credentials.yaml file and initialize the TestClient
        for each test (instead of using setUpClass).
        """
        print("Initializing TestClient from setUp")
        self.client = TestClient(app)

        credentials_file = Path("../Credentials/Credentials.yaml").resolve()
        if not os.path.exists(credentials_file):
            print("Unable to find credentials file")
            raise FileNotFoundError(f"Credentials file not found at {credentials_file}")

        with open(credentials_file, 'r', encoding='utf-8') as file:
            credentials_content = file.read()

        print(f'Credentials content: {credentials_content}')

        # Hardcode other parameters.
        self.test_params = {
            "credentials": credentials_content,
            "general_prompt": "Ukraine and Russia War",
            "particular_prompt": "Zelensky in White House",
            "operating_path": "./output",
            "llm_api_url": "http://localhost:11434/api/chat",
            "cse_id": None,  # Or provide your Custom Search Engine ID if needed.
        }

    def test_health_check(self):
        """Test the /health endpoint returns a status of ok."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_search_endpoint(self):
        """
        Test the /search endpoint by sending the credentials loaded from Credentials.yaml
        along with hardcoded search parameters.
        Verifies that the response contains a 'results' key with a list.
        """
        payload = {
            "credentials": self.test_params["credentials"],
            "general_prompt": self.test_params["general_prompt"],
            "particular_prompt": self.test_params["particular_prompt"],
            "operating_path": self.test_params["operating_path"],
            "llm_api_url": self.test_params["llm_api_url"],
            "cse_id": self.test_params["cse_id"],
        }
        response = self.client.post("/search", json=payload)
        self.assertEqual(response.status_code, 200, f"Response JSON: {response.json()}")
        json_data = response.json()
        self.assertIn("results", json_data)
        print(f'Test search results: {json_data["results"]}')
        self.assertIsInstance(json_data["results"], list)


if __name__ == "__main__":
    unittest.main()