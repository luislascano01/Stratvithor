import logging
import yaml
from pathlib import Path


class CredentialManager:
    def __init__(self, credential_file: str):
        logging.debug(f"Initializing CredentialManager with {credential_file}")
        credential_path = Path(credential_file).resolve()
        logging.debug(f"Resolved path: {credential_path}")

        if not credential_path.suffix in ['.yaml', '.yml']:
            logging.error("Invalid file extension for YAML file.")
            raise ValueError("File must be a YAML file with a .yaml or .yml extension")
        if not credential_path.exists():
            logging.error(f"File not found at {credential_path}")
            raise FileNotFoundError(f"No file found at {credential_path}")

        self.credential_file = credential_path
        self.credentials = self._load_credentials()

    def _load_credentials(self):
        with open(self.credential_file, "r") as file:
            return yaml.safe_load(file) or {}

    def _load_credentials(self):
        with open(self.credential_file, "r") as file:
            return yaml.safe_load(file) or {}

    def _save_credentials(self):
        with open(self.credential_file, "w") as file:
            yaml.safe_dump(self.credentials, file)

    def get_credential(self, category: str, key: str):
        return self.credentials.get(category, {}).get(key)

    def set_credential(self, category: str, key: str, value: str):
        if category not in self.credentials:
            self.credentials[category] = {}
        self.credentials[category][key] = value
        self._save_credentials()
