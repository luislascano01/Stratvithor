import logging
import aiohttp
import asyncio
import json
from openai import OpenAI

from datetime import datetime


def get_todays_date():
    today = datetime.now()
    day = today.day
    # Determine ordinal suffix for the day
    if 4 <= day <= 20 or 24 <= day <= 30:
        suffix = "th"
    else:
        suffix = ["st", "nd", "rd"][day % 10 - 1]
    # Build formatted string: e.g., "Thursday, March 27th, 2025"
    return today.strftime("%A, %B ") + str(day) + suffix + today.strftime(", %Y")


from typing import Any, Dict, Optional, List


class DataMolder:
    """
    The microservice (which may be LLM-powered) returns a refined result in JSON format.
    Now process_data returns a dictionary with two entries:
      - "llm_response": The text response from the model.
      - "web_references": A string containing any web reference URLs extracted from annotations.
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
        self.client = OpenAI(api_key=self.openai_api_key)

    async def process_data(
            self,
            online_data: Dict[str, Any],
            ancestor_messages: List[Dict[str, Any]] = None,
            custom_topic_focuser: Optional[str] = ""
    ) -> Dict[str, str]:
        """
        Processes the raw data by combining it with parent context and custom topic focuser,
        then sends it to OpenAI for refinement.

        Returns a dictionary with:
          - "llm_response": the response text from the model.
          - "web_references": any references (URLs) provided in the annotations (if applicable).

        If the API call fails due to input length, it will reduce the largest scrapped_text
        in online_data by half and retry.
        """
        if ancestor_messages is None:
            ancestor_messages = []

        # A system message plus an initial user message referencing custom_topic_focuser.

        date_str = get_todays_date()
        molder_messages = [{
            "entity": "system",
            "text": (
                    "Today's Date: " + date_str + "\n" +
                    "You are an assistant with the responsibility of answering the user prompts. "
                    "The user sometimes will provide online data to answer these prompts in the "
                    "most up-to-date way. However, if no online data is provided, then you must "
                    "answer to the best of your knowledge at the time of your request. "
                    "Please provide your response in markdown style, with correct citation "
                    "of the online data sources. If the online data is empty, ignore it "
                    "and do not think of its existence. "
                    "Attempt to provide your most accurate response.\n"
                    "For every response, use markdown format, however, do not start your response with a markdown header, but instead "
                    "give a plain text intro when starting your response. Do not re-state the question. The intro should start "
                    "answering right away. Follow the markdown format appropriately."
                    "Your response should be an entire essay providing in-depth analysis. Please provide long response"
            )
        }, {
            "entity": "user",
            "text": f"The company we will be building the report on today is {custom_topic_focuser}"
        }]

        ancestor_messages = molder_messages + ancestor_messages

        print("DEBUG ancestor_messages for node:", json.dumps(ancestor_messages, indent=2))

        # Convert ancestor_messages into a ChatCompletion-style list.
        role_map = {
            "system": "system",  # You can also map 'system' to 'system'
            "developer": "system",  # If you want to treat 'developer' as system
            "user": "user",
            "llm": "assistant"
        }

        chat_messages = []
        for msg in ancestor_messages:
            entity = msg.get("entity", "user")
            text = msg.get("text", "")
            # If the original code used "system" => "developer", revert if needed:
            # But typically: system => "system", user => "user", llm => "assistant"
            role = role_map.get(entity, "user")
            chat_messages.append({"role": role, "content": text})

        # Optionally incorporate online_data as an extra system/developer message.
        if online_data:
            data_str = json.dumps(online_data, indent=2)
            chat_messages.append({
                "role": "user",
                "content": (
                        "##########\nONLINE_DATA\n----------\n" +
                        data_str +
                        "\n----------\nEnd of ONLINE_DATA\n##########\n"
                )
            })
        logging.info(f'chat_messages: {json.dumps(chat_messages, indent=2)}')

        # If there's a custom topic focuser, add it as a final user message (already added above).
        # Possibly omit if you do not need it repeated.

        # Set openai.api_key

        # Retry loop for potential token-length errors
        max_retries = 5
        attempt = 0
        last_exception = None

        while attempt < max_retries:
            try:
                # Use the new ChatCompletion API
                if self.model_name in ["gpt-4o", "gpt-3.5-turbo"]:
                    response = await asyncio.to_thread(
                        lambda: self.client.chat.completions.create(
                            model=self.model_name,
                            messages=chat_messages
                        )
                    )
                    output_text = response.choices[0].message.content
                    return {
                        "llm_response": output_text,
                        "web_references": ""
                    }

                elif self.model_name == "gpt-4o-search-preview":
                    try:
                        response = await asyncio.to_thread(
                            lambda: self.client.chat.completions.create(
                                model=self.model_name,
                                messages=chat_messages,
                                web_search_options={}
                            )
                        )
                        message = response.choices[0].message
                        llm_response = message.content

                        annotations = getattr(message, "annotations", [])
                        references = []
                        for annotation in annotations:
                            if getattr(annotation, "type", None) == "url_citation":
                                url_citation = getattr(annotation, "url_citation", None)
                                if url_citation:
                                    title = getattr(url_citation, "title", "No Title")
                                    url = getattr(url_citation, "url", "No URL")
                                    references.append(f"{title}: {url}")
                        web_references = "\n".join(references)
                        return {
                            "llm_response": llm_response,
                            "web_references": web_references
                        }
                    except Exception as e:
                        logging.info("gpt-4o-search-preview failed with error: %s. Falling back to gpt-4o.", e)
                        # Fall back to gpt-4o if search-preview fails.
                        response = await asyncio.to_thread(
                            lambda: self.client.chat.completions.create(
                                model="gpt-4o",
                                messages=chat_messages
                            )
                        )
                        output_text = response.choices[0].message.content
                        return {
                            "llm_response": output_text,
                            "web_references": ""
                        }
                else:
                    raise Exception("Unsupported model name provided.")

            except Exception as e:
                last_exception = e
                error_message = str(e)
                logging.info(f"Attempt {attempt + 1} failed: {error_message}")

                # Check if it's a token-length issue => reduce largest scrapped_text
                if ("Token indices sequence length" in error_message or
                        "exceeds maximum" in error_message):
                    results = online_data.get("results")
                    if results and isinstance(results, list):
                        # Find the largest scrapped_text
                        longest_idx = None
                        max_len = 0
                        for idx, result in enumerate(results):
                            text_val = result.get("scrapped_text", "")
                            if len(text_val) > max_len:
                                max_len = len(text_val)
                                longest_idx = idx
                        if longest_idx is not None and max_len > 0:
                            old_text = results[longest_idx]["scrapped_text"]
                            new_text = old_text[: len(old_text) // 2]
                            results[longest_idx]["scrapped_text"] = new_text
                            logging.info(
                                f"Reduced scrapped_text length of result {longest_idx} "
                                f"from {max_len} to {len(new_text)}"
                            )
                            data_str = json.dumps(online_data, indent=2)
                            # Update the system message with the truncated data
                            if chat_messages and chat_messages[-1]["content"].startswith("##########\nONLINE_DATA"):
                                chat_messages.pop()
                            chat_messages.append({
                                "role": "system",
                                "content": (
                                        "##########\nONLINE_DATA\n----------\n" +
                                        data_str +
                                        "\n----------\nEnd of ONLINE_DATA\n##########\n"
                                )
                            })
                            attempt += 1
                            continue

                break

        raise Exception(
            f"DataMolder process_data failed after {attempt} attempts: {last_exception}"
        )


# ------------------------------------------
# Example usage script (main):
# ------------------------------------------
if __name__ == "__main__":
    import asyncio
    import json
    from Backend.Report_Compose.src.Integrator import load_openai_api_key


    async def main():
        # 1) Load your API key from credentials YAML (ensure the file path is correct)
        openai_api_key = load_openai_api_key("./Credentials/Credentials.yaml")

        # 2) Instantiate the DataMolder with model "gpt-4o-search-preview"
        data_molder = DataMolder(model="gpt-4o-search-preview", service_api_key=openai_api_key)

        # 3) Create example online data for the Meta Quest VR headset
        online_data = {
            "articles": [
                {
                    "title": "Meta Unveils Next Generation Meta Quest VR Headset",
                    "content": (
                        "Meta has introduced the new Meta Quest VR headset featuring improved resolution, advanced tracking, "
                        "and enhanced comfort. The new design promises a more immersive experience that could redefine home VR entertainment."
                    )
                },
                {
                    "title": "Consumer Reactions to the Meta Quest Launch",
                    "content": (
                        "Early reviews and social media buzz indicate strong interest in Meta's new VR headset. While users praise "
                        "its innovative features and immersive performance, there are mixed opinions regarding its pricing and overall market positioning."
                    )
                }
            ],
            "statistics": {
                "preorder_count": 4000,
                "social_media_mentions": 20000,
                "average_rating": 4.7
            }
        }

        # 4) Build a mock chat history focused on the Meta Quest topic
        ancestor_messages = [
            {"entity": "system", "text": "You are an expert VR technology analyst."},
            {"entity": "user", "text": "Analyze the market impact of Meta's new Meta Quest VR headset."},
            {"entity": "llm", "text": "Understood. I will review the technical features and market positioning."},
            {"entity": "user",
             "text": "Consider both the technological innovations and the consumer pricing strategy."},
            {"entity": "llm",
             "text": "I have noted improvements in display resolution and tracking capabilities, as well as insights into competitive pricing."},
            {"entity": "user",
             "text": "Now, provide an overall analysis including consumer sentiment and potential future trends in the VR market."}
        ]

        # 5) Custom topic focuser
        custom_topic_focuser = "Focus on the balance between technological innovation and market adoption for VR devices."

        # 6) Call process_data and print the result
        try:
            result = await data_molder.process_data(
                online_data=online_data,
                ancestor_messages=ancestor_messages,
                custom_topic_focuser=custom_topic_focuser
            )
            print("Result from DataMolder:")
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"DataMolder processing failed: {e}")


    asyncio.run(main())
