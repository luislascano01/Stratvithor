import re
import logging
import yaml
from pathlib import Path


class CredentialManager:
    def __init__(self, credential_input: str):
        """
        Initializes the CredentialManager.

        :param credential_input: Either a path to a YAML file or a YAML/JSON string.
        """
        logging.debug(f"Initializing CredentialManager with input: {credential_input}")

        # Regex pattern to detect a file path:
        # - It can start with "./", "/" or a drive letter (e.g., "C:\")
        # - It must end with .yaml or .yml
        file_path_pattern = r"^(?:\.\/|\/|[a-zA-Z]:\\)?[^:\n]+\.(yaml|yml)$"
        if re.match(file_path_pattern, credential_input.strip()):
            # Looks like a file path
            credential_path = Path(credential_input).resolve()
            logging.debug(f"Resolved path: {credential_path}")

            if not credential_path.exists():
                logging.error(f"File not found at {credential_path}")
                raise FileNotFoundError(f"No file found at {credential_path}")

            self.credential_file = credential_path
            self.credentials = self._load_credentials_from_file()
            self._loaded_from_file = True
        else:
            # Treat credential_input as the content of the credentials (YAML/JSON string)
            try:
                self.credentials = yaml.safe_load(credential_input) or {}
            except yaml.YAMLError as e:
                logging.error("Failed to parse YAML/JSON string.")
                raise ValueError("Invalid YAML/JSON string provided.") from e

            self.credential_file = None
            self._loaded_from_file = False

    def _load_credentials_from_file(self):
        with open(self.credential_file, "r") as file:
            return yaml.safe_load(file) or {}

    def _save_credentials(self):
        if self._loaded_from_file and self.credential_file is not None:
            with open(self.credential_file, "w") as file:
                yaml.safe_dump(self.credentials, file)
        else:
            logging.warning("Credentials were loaded from a string; saving to file is not supported.")

    def get_credential(self, category: str, key: str):
        return self.credentials.get(category, {}).get(key)

    def set_credential(self, category: str, key: str, value: str):
        if category not in self.credentials:
            self.credentials[category] = {}
        self.credentials[category][key] = value
        self._save_credentials()