import aiohttp
import asyncio
from typing import Any, Dict, Optional


class DataMolder:
    """
    DataMolder is responsible for refining raw text data by combining it with parent context
    and an optional custom topic focuser, then sending it to a text processing microservice.
    The microservice (which may be LLM-powered) returns a refined result in JSON format.
    """

    def __init__(self, text_processing_url: str):
        """
        Initializes the DataMolder with the provided microservice URL.

        :param text_processing_url: URL of the Text_Processing microservice.
        """
        self.text_processing_url = text_processing_url

    async def process_data(
            self,
            raw_data: Dict[str, Any],
            parent_context: Optional[str] = "",
            custom_topic_focuser: Optional[str] = ""
    ) -> Dict[str, Any]:
        """
        Processes the raw data by combining it with parent context and custom topic focuser,
        then sends it to the text processing microservice for refinement.

        :param raw_data: The raw structured data obtained from the DataQuerier.
        :param parent_context: Concatenated context from parent prompt responses.
        :param custom_topic_focuser: Additional text to steer the processing.
        :return: A dictionary with the processed (molded) data.
        :raises Exception: If the microservice call fails.
        """
        payload = {
            "raw_data": raw_data,
            "parent_context": parent_context,
            "custom_topic_focuser": custom_topic_focuser
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.text_processing_url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return result
                else:
                    raise Exception(f"Failed to process data: HTTP {response.status}")

# Example usage:
# async def main():
#     data_molder = DataMolder("https://text-processing.example.com/process")
#     raw = {"texts": ["Example text data..."], "tables": []}
#     parent_ctx = "Parent context information."
#     focuser = "Focus on financial analysis."
#     processed = await data_molder.process_data(raw, parent_ctx, focuser)
#     print(processed)
#
# asyncio.run(main())