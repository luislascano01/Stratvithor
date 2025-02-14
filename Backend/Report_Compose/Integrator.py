import json
import yaml
from PromptManager import PromptManager
from DataMolder import DataMolder
from DataQuerier import DataQuerier


class Integrator:
    def __init__(self, yaml_file_path):
        """
        Initializes the Integrator by loading prompts from a YAML file and setting up dependencies.
        :param yaml_file_path: Path to the YAML file containing prompts.
        :param data_molder: Instance of DataMolder.
        :param data_querier: Instance of DataQuerier.
        """
        self.prompt_manager = self.load_prompts(yaml_file_path)

    def load_prompts(self, yaml_file_path):
        """
        Loads the YAML file and initializes the PromptManager.
        :param yaml_file_path: Path to the YAML file.
        :return: An instance of PromptManager.
        """
        with open(yaml_file_path, "r", encoding="utf-8") as file:
            prompts_data = yaml.safe_load(file)

        return PromptManager(prompts_data)

    def generate_report(self, company_name):
        """
        Generates a JSON report by iterating through prompts in order.
        Skips the "initial" prompt for querying.
        :param company_name: Name of the company for the report.
        :return: JSON-formatted report.
        """
        report_data = {"company": company_name, "sections": {}}

        # Retrieve prompts in order, skipping "initial"
        for section_key, section_info in self.prompt_manager.prompts.items():
            if section_key == "initial":
                continue  # Skip initial prompt

            prompt_text = section_info["text"]
            section_title = section_info["section_title"]

            # Fetch and process data using DataMolder and DataQuerier
            raw_data = self.data_querier.query(company_name, prompt_text)
            structured_data = self.data_molder.process_data(raw_data)

            # Store processed data in report
            report_data["sections"][section_title] = structured_data

        return json.dumps(report_data, indent=4)