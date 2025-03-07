import aiohttp
import asyncio
import json
import openai
from typing import Any, Dict, Optional, List

class DataMolder:
    """
    DataMolder is responsible for refining raw text data by combining it with parent context
    and an optional custom topic focuser, then sending it to a text processing microservice.
    The microservice (which may be LLM-powered) returns a refined result in JSON format.
    """

    def __init__(self, model: str, service_api_key: str, text_processing_url="DEFAULT"):
        """
        Initializes the DataMolder with the provided microservice URL.
        :param model: The name of the model to use.
        :param service_api_key: The OpenAI (or alternative) API key to use.
        :param text_processing_url: URL of the Text_Processing microservice (if not using OpenAI).
        """
        self.text_processing_url = text_processing_url
        self.model_name = model
        self.openai_api_key = service_api_key

    async def process_data(
        self,
        online_data: Dict[str, Any],
        ancestor_messages: List[Dict[str, Any]] = None,
        custom_topic_focuser: Optional[str] = ""
    ) -> str:
        """
        Processes the raw data by combining it with parent context and custom topic focuser,
        then sends it to the text processing microservice (or OpenAI) for refinement.

        :param online_data: The raw structured data obtained from the DataQuerier.
        :param ancestor_messages: List of previous messages in the conversation branch.
                                 e.g. [{"entity": "system", "text": "..."}, {"entity": "user", "text": "..."}, ...]
        :param custom_topic_focuser: Additional text to steer the processing.
        :return: A dictionary with the processed (molded) data.
        :raises Exception: If the microservice or OpenAI call fails.
        """
        if ancestor_messages is None:
            ancestor_messages = []

        # 1) Convert `ancestor_messages` into GPT-4o–style chat structure
        role_map = {
            "system": "developer",   # system => "developer"
            "user":   "user",        # user => "user"
            "llm":    "assistant"    # LLM => "assistant"
        }

        gpt4o_messages = []
        for msg in ancestor_messages:
            entity = msg.get("entity", "user")
            text   = msg.get("text", "")
            role   = role_map.get(entity, "user")
            gpt4o_messages.append({
                "role": role,
                "content": [
                    {
                        "type": "text",
                        "text": text
                    }
                ]
            })

        # 2) Optionally incorporate online_data as a "developer" message with JSON payload:
        if online_data:
            data_str = json.dumps(online_data, indent=2)
            gpt4o_messages.append({
                "role": "developer",
                "content": [
                    {
                        "type": "text",
                        "text": f"ONLINE_DATA:\n{data_str}"
                    }
                ]
            })

        # 3) If there's a custom topic focuser, treat it like a user message at the end.
        if custom_topic_focuser:
            gpt4o_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Custom focus: {custom_topic_focuser}"
                    }
                ]
            })

        # 4) Call the selected model. We create an OpenAI client instance and run the synchronous call
        # within asyncio.to_thread to keep the interface async.
        try:
            client = openai.OpenAI(api_key=self.openai_api_key)
            if self.model_name == "gpt-4o":
                response = await asyncio.to_thread(
                    lambda: client.chat.completions.create(
                        model="gpt-4o",
                        messages=gpt4o_messages,
                    )
                )
                output_text = response.choices[0].message.content
            else:
                response = await asyncio.to_thread(
                    lambda: client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a helpful assistant. Please process the user inputs carefully."
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"Ancestor messages:\n{json.dumps(ancestor_messages, indent=2)}\n\n"
                                    f"online_data:\n{json.dumps(online_data, indent=2)}\n\n"
                                    f"Custom topic:\n{custom_topic_focuser}"
                                )
                            }
                        ]
                    )
                )
                output_text = response.choices[0].message.content

            # 5) Return the processed result.
            return {"molded_text": output_text}

        except Exception as e:
            raise Exception(f"DataMolder process_data failed: {str(e)}") from e

if __name__ == "__main__":
    import asyncio
    import json
    from Backend.Report_Compose.src.Integrator import load_openai_api_key  # Adjust the import as needed

    async def main():
        # 1. Load your API key from credentials YAML.
        openai_api_key = load_openai_api_key("./Credentials/Credentials.yaml")

        # 2. Instantiate the DataMolder with model "gpt-4o"
        data_molder = DataMolder(model="gpt-4o", service_api_key=openai_api_key)

        # 3. Create believable online data for a new tech product.
        online_data = {
            "articles": [
                {
                    "title": "TechCorp Unveils Its Latest Smartphone",
                    "content": (
                        "TechCorp has released a new smartphone featuring a cutting-edge foldable display, "
                        "an advanced AI-driven camera system, and extended battery life. Early reviews praise "
                        "its innovative design while noting the high price point."
                    )
                },
                {
                    "title": "Consumers Weigh In on TechCorp's New Phone",
                    "content": (
                        "Social media and tech blogs are abuzz with reactions to TechCorp's latest release. "
                        "Many users commend the device’s unique design and performance, although some remain "
                        "cautious about its premium pricing."
                    )
                }
            ],
            "statistics": {
                "preorder_count": 5000,
                "social_media_mentions": 12000,
                "average_rating": 4.5
            }
        }

        # 4. Build a longer, more detailed mock chat history.
        ancestor_messages = [
            {"entity": "system", "text": "You are an expert product analyst."},
            {"entity": "user", "text": "Analyze the impact of TechCorp's new smartphone release."},
            {"entity": "llm", "text": "Understood. I will start by reviewing product specifications."},
            {"entity": "user", "text": "Consider the hardware features and overall design innovations."},
            {"entity": "llm", "text": "I have noted the advanced features and unique design aspects."},
            {"entity": "user", "text": "Now, factor in consumer reviews and market sentiment."},
            {"entity": "llm", "text": "I am gathering insights from various online articles and social media metrics."},
            {"entity": "user", "text": "Provide a comprehensive analysis on potential market trends."}
        ]

        # 5. Optionally, set a custom topic focuser (if desired).
        custom_topic_focuser = "Focus on the balance between innovation and pricing strategy."

        # 6. Call process_data to generate the molded result.
        try:
            result = await data_molder.process_data(
                online_data=online_data,
                ancestor_messages=ancestor_messages,
                custom_topic_focuser=custom_topic_focuser
            )
            print("Result from DataMolder:")
            print(result)
        except Exception as e:
            print(f"DataMolder processing failed: {e}")

    asyncio.run(main())