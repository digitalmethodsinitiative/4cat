"""
Fake 'client' to read from local store of known 3d party, API-based LLMs that
can be used with 4CAT
"""
import json

from common.lib.llm.llm_client import LLMServerClient


class ThirdPartyClient(LLMServerClient):
    type = "thirdparty"

    _models_info_key = "models"
    _model_id_key = "model"

    def get_status(self):
        return 200

    def list_models(self) -> dict:
        with self.config.get("PATH_ROOT").joinpath("common/assets/llms.json").open() as infile:
            models = json.load(infile)

        return models

    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """
        Derive the media types a model supports from its LiteLLM metadata.

        :param meta:    `model info` response dict, or `None`.
        :returns:       Ordered list of supported media type strings.
                        Returns `[]` when `meta` is `None`
        """
        return meta.get("supported_media_types", ["text"])

    def format_display_name(self, meta: dict) -> str:
        """
        Build a human-readable display name for a model.

        :param meta:        `/api/show` response dict, or `None`.
        :returns:           Human-readable display name string.
        """
        return meta["name"]

    def build_model_entry(self, meta: dict) -> dict:
        """
        Build a canonical `llm.available_models` entry for a model.

        :param meta:            `/api/show` response dict, or `None` if unavailable.
        :returns:               Dict ready to store under `llm.available_models[model_id]`.
        """
        entry = super().build_model_entry(meta)
        # Third-party catalog models span multiple vendors, so the wrapper
        # (which LangChain chat class to use) is per-model, not the connection
        # type ("api"). Override the connection-derived wrapper with the vendor.
        entry["wrapper"] = meta["server"]

        return entry

    def get_model_card_url(self, meta: dict) -> str:
        """
        Get a URL for a model card for a given model

        :param meta:  Model metadata
        :return str:  Model card URL (empty string if unavailable)
        """
        return meta["model_card"] if meta["model_card"] else ""
