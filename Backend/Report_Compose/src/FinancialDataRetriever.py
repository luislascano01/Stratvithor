import json
import urllib.parse
import httpx
import asyncio
import logging
import os
import yaml

import yfinance as yf


class FinancialDataRetriever:
    """
    FinancialDataRetriever is responsible for retrieving ticker symbols from multiple
    sources (Yahoo, Alpha Vantage, Polygon) and fetching summary/historical data via yfinance.

    Usage:
        retriever = FinancialDataRetriever(alpha_vantage_api_key="...", polygon_api_key="...")
        info = await retriever.get_financial_info_yahoo("Acme Corp")
        if "INFO_NOT_FOUND" not in info:
            # process info...
    """

    def __init__(self, alpha_vantage_api_key="", polygon_api_key=""):
        """
        :param alpha_vantage_api_key: optional API key for Alpha Vantage
        :param polygon_api_key: optional API key for Polygon.io
        """
        self.alpha_vantage_api_key = alpha_vantage_api_key
        self.polygon_api_key = polygon_api_key

    async def request_with_retries(self, client, url, max_retries=3, initial_delay=2):
        """
        Helper method to handle HTTP GET with retry & backoff.
        Includes a user-agent header (optional) to look more like a real browser.
        """
        delay = initial_delay

        # Example User-Agent; you can rotate or omit this if you wish
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
            )
        }

        for attempt in range(max_retries):
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 429:
                    logging.warning(
                        "Rate limited (429) on URL %s (attempt %d)",
                        url, attempt + 1
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                response.raise_for_status()
                return response

            except Exception as e:
                logging.warning(
                    "Attempt %d failed for URL %s: %s",
                    attempt + 1, url, e
                )
                # If we've used up all attempts, return None or re-raise
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(delay)
                delay *= 2

        # If we exit the loop, return None to indicate failure
        return None

    async def try_yahoo_search(self, company_name: str) -> str:
        """
        Attempt to find a ticker using Yahoo's search endpoint by calling `curl` directly
        as a subprocess, then parsing JSON from stdout.
        """
        encoded_name = urllib.parse.quote(company_name)  # URL-encode
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded_name}"

        # Build a curl command (quiet, show errors, no special headers, etc.)
        cmd = [
            "curl", "-sS",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
            url
        ]

        # Run `curl` in a subprocess
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logging.error(
                "Curl command failed (code=%d). stderr: %s",
                proc.returncode,
                stderr.decode("utf-8", errors="replace")
            )
            return ""

        try:
            # Parse the JSON from stdout
            data = json.loads(stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            logging.error("Failed to parse JSON from curl output: %s", e)
            return ""

        # Check for quotes in the JSON
        for quote in data.get("quotes", []):
            if quote.get("quoteType") == "EQUITY" and "symbol" in quote:
                return quote["symbol"]

        # If no symbol found
        return ""

    async def try_alpha_vantage_search(self, company_name: str) -> str:
        """Attempt to find a ticker using Alpha Vantage's SYMBOL_SEARCH endpoint."""
        if not self.alpha_vantage_api_key:
            return ""
        base_url = "https://www.alphavantage.co/query"
        params = {
            "function": "SYMBOL_SEARCH",
            "keywords": company_name,
            "apikey": self.alpha_vantage_api_key
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await self.request_with_retries(client, base_url, max_retries=3, initial_delay=2)
                if not response:
                    return ""
                data = response.json()
                best_matches = data.get("bestMatches", [])
                if not best_matches:
                    return ""
                # For example, pick the first symbol
                return best_matches[0].get("1. symbol", "")
            except Exception as e:
                logging.error("Alpha Vantage search error for %s: %s", company_name, e)
        return ""

    async def try_polygon_search(self, company_name: str) -> str:
        """Attempt to find a ticker using Polygon.io's reference ticker list endpoint."""
        if not self.polygon_api_key:
            return ""

        from polygon import RESTClient

        def polygon_search(name: str):
            client = RESTClient(self.polygon_api_key)
            try:
                # The v3 reference tickers endpoint can filter by `search=` param
                response = client.list_tickers(search=name, limit=5)
                return response
            finally:
                client.close()

        try:
            results = await asyncio.to_thread(polygon_search, company_name)
            if not results:
                return ""
            # For example, pick the first
            return results[0].ticker
        except Exception as e:
            logging.error("Polygon search error for %s: %s", company_name, e)
        return ""

    async def get_financial_info_yahoo(self, company_name: str) -> dict:
        """
        Hybrid approach:
         1) Attempt to find the ticker from multiple sources (Yahoo -> Alpha Vantage -> Polygon).
         2) If found, fetch summary & historical data with yfinance.
         3) Return structured result or INFO_NOT_FOUND if all fails.
        """
        decoded_name = company_name  # Keep for logging
        company_name = urllib.parse.quote(company_name)  # URL-encode for fallback usage, if needed

        logging.info("Attempting to get financial info for %s.", company_name)

        # 1) Attempt ticker retrieval from multiple sources in order
        ticker = await self.try_yahoo_search(decoded_name)
        if not ticker:
            ticker = await self.try_alpha_vantage_search(decoded_name)
        if not ticker:
            ticker = await self.try_polygon_search(decoded_name)

        if not ticker:
            logging.info("No ticker found for company: %s (all sources).", decoded_name)
            return {"INFO_NOT_FOUND": True}

        # 2) Use yfinance to get the main info
        try:
            ticker_data = await asyncio.to_thread(yf.Ticker, ticker)
        except Exception as e:
            logging.error(f"Error initializing yfinance.Ticker({ticker}): %s", e)
            return {"INFO_NOT_FOUND": True}

        # ticker_data.info can throw an exception or be incomplete
        try:
            summary_data_full = await asyncio.to_thread(lambda: ticker_data.info)

            # Define the keys you are interested in
            keys_ignore = ['longBusinessSummary']

            # Create a new dictionary with only the keys of interest
            summary_data = {
                key: summary_data_full.get(key, None)
                for key in summary_data_full
                if key not in keys_ignore
            }

        except Exception as e:
            logging.error(f"Error retrieving info() from yfinance: %s", e)
            summary_data = None

        # Now get historical data: 1y & 5y monthly intervals
        historical_data = {}
        try:
            hist_1y = await asyncio.to_thread(lambda: ticker_data.history(period="1y", interval="1mo"))
            historical_data["1Y"] = hist_1y.to_dict(orient="index") if not hist_1y.empty else None
        except Exception as e:
            logging.error("Error fetching 1-year historical data for %s: %s", ticker, e)
            historical_data["1Y"] = None

        try:
            hist_3y = await asyncio.to_thread(lambda: ticker_data.history(period="3y", interval="3mo"))
            historical_data["3Y"] = hist_3y.to_dict(orient="index") if not hist_3y.empty else None
        except Exception as e:
            logging.error("Error fetching 5-year historical data for %s: %s", ticker, e)
            historical_data["3Y"] = None

        # 3) Compile final result
        result_dict = {
            "TICKER": ticker,

            "FINANCIAL_INFO": str(summary_data),
            "HISTORICAL_DATA": str(historical_data)
        }

        logging.info("Hybrid data for ticker %s: %s", ticker, result_dict)
        return result_dict


# If your load_api_key is elsewhere, import it from the correct module
def load_api_key(yaml_file_path: str, api_name: str) -> str:
    """
    Loads the specified API key (api_name) from the given YAML file.
    """
    try:
        if not os.path.exists(yaml_file_path):
            raise FileNotFoundError(f"YAML file not found: {yaml_file_path}")

        with open(yaml_file_path, "r") as file:
            data = yaml.safe_load(file)

        if "API_Keys" not in data or api_name not in data["API_Keys"]:
            raise KeyError(f"{api_name} API key is missing from the YAML file.")

        return data["API_Keys"][api_name]
    except (FileNotFoundError, yaml.YAMLError, KeyError) as e:
        logging.error("Error loading API key: %s", e)
        return ""


async def main():
    """
    Simple test for FinancialDataRetriever.
    1) Load relevant API keys from Credentials.yaml.
    2) Create and run a test retrieval for a sample company.
    3) Print or log the result.
    """
    logging.basicConfig(level=logging.INFO)

    # 1) Load your API keys
    vantage_key = load_api_key("./Credentials/Credentials.yaml", "Vantage")
    polygon_key = load_api_key("./Credentials/Credentials.yaml", "Polygon")

    # 2) Import your FinancialDataRetriever class (adjust import path as needed)
    from FinancialDataRetriever import FinancialDataRetriever

    # 3) Instantiate the retriever
    retriever = FinancialDataRetriever(
        alpha_vantage_api_key=vantage_key,
        polygon_api_key=polygon_key
    )

    # 4) Test retrieval with a sample company
    company = "United Airlines"
    logging.info(f"Retrieving financial info for: {company}")
    result = await retriever.get_financial_info_yahoo(company)

    # 5) Check results
    if "INFO_NOT_FOUND" in result:
        logging.info(f"No data found for '{company}'.")
    else:
        logging.info(f"Retrieved data for '{company}': {result}")


if __name__ == "__main__":
    asyncio.run(main())
