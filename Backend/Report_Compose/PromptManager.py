import yaml
import os

class PromptManager:
    def __init__(self, yaml_file_path):
        self.prompts = {}  # Dictionary of dictionaries
        self.load_prompts(yaml_file_path)

    def load_prompts(self, yaml_file_path):
        """Load prompts from a YAML file and store them in a nested dictionary."""
        with open(yaml_file_path, 'r', encoding='utf-8') as file:
            data = yaml.safe_load(file)

        prompts_data = data.get("prompts", {})  # Ensure it doesn't crash if 'prompts' key is missing

        for section_title, prompt_data in prompts_data.items():
            if isinstance(prompt_data, dict) and "text" in prompt_data:  # Ensure it's a dictionary and contains text
                if section_title not in self.prompts:
                    self.prompts[section_title] = {
                        "section_title": prompt_data.get("section_name", section_title),  # Use section_name if available
                        "text": prompt_data["text"],
                        "additional_data": {}
                    }
    def add_metadata(self, prompt, key, value):
        """Add extra metadata under a given prompt."""
        if prompt in self.prompts:
            self.prompts[prompt]["additional_data"][key] = value
        else:
            print(f"Prompt '{prompt}' not found.")

    def get_prompt_data(self, prompt):
        """Retrieve stored data for a given prompt."""
        return self.prompts.get(prompt, None)

    def display_prompts(self):
        """Print all stored prompts in a readable format."""
        import textwrap
        prompt_text_wrapp_indent = "    "
        for prompt, details in self.prompts.items():
            print(f"Prompt: {prompt}")
            print(f"  Section Title: {details['section_title']}")
            wrapped_text = textwrap.fill(details['text'], width=50,
                                         subsequent_indent=prompt_text_wrapp_indent)  # Wrap text to 50 chars with indent
            print(f"  Prompt Text:\n{prompt_text_wrapp_indent}{wrapped_text}")
            print(f"  Additional Data: {details['additional_data']}")
            print("-" * 40)

if __name__ == "__main__":
    manager = PromptManager("./Prompts/prompts.yaml")

    manager.display_prompts()