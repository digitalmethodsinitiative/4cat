import json
import requests
from pathlib import Path
from typing import List, Optional, Union
from pydantic import SecretStr
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_mistralai import ChatMistralAI
from langchain_deepseek import ChatDeepSeek


class LLMAdapter:
    def __init__(
            self,
            provider: str,
            model: str,
            api_key: Optional[str] = None,
            base_url: Optional[str] = None,
            temperature: float = 0.1,
            max_tokens: int = 1000,
            client_kwargs: Optional[dict] = None,
    ):
        """
        provider: 'openai', 'google', 'mistral', 'ollama', 'lmstudio', 'anthropic', 'deepseek'
        model: model name (e.g., 'gpt-4o-mini', 'claude-3-opus', 'mistral-small', etc.)
        api_key: API key if required (OpenAI, Claude, Google, Mistral)
        base_url: for local models or Mistral custom endpoints
        temperature: temperature hyperparameter,
        max_tokens: how many output tokens may be used
        client_kwargs: additional client parameters
        """
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.structured_output = False
        self.parser = None
        self.max_tokens = max_tokens
        self.client_kwargs = dict(client_kwargs) if client_kwargs else {}
        self.llm: BaseChatModel = self._load_llm()

    def _load_llm(self) -> BaseChatModel:
        if self.provider == "openai":
            kwargs = {}
            if "o3" not in self.model:
                kwargs["temperature"] = self.temperature # temperature not supported for all models
            return ChatOpenAI(
                model=self.model,
                api_key=SecretStr(self.api_key),
                base_url=self.base_url or "https://api.openai.com/v1",
                max_tokens=self.max_tokens,
                **kwargs
            )
        elif self.provider == "google":
            return ChatGoogleGenerativeAI(
                model=self.model,
                temperature=self.temperature,
                google_api_key=self.api_key,
                max_tokens=self.max_tokens
            )
        elif self.provider == "anthropic":
            return ChatAnthropic(
                model_name=self.model,
                temperature=self.temperature,
                api_key=SecretStr(self.api_key),
                max_tokens=self.max_tokens,
                timeout=100,
                stop=None
            )
        elif self.provider == "mistral":
            return ChatMistralAI(
                model_name=self.model,
                temperature=self.temperature,
                api_key=SecretStr(self.api_key),
                base_url=self.base_url,  # Optional override
                max_tokens=self.max_tokens,
            )
        elif self.provider == "deepseek":
            return ChatDeepSeek(
                model=self.model,
                temperature=self.temperature,
                api_key=SecretStr(self.api_key),
                base_url=self.base_url,
                max_tokens=self.max_tokens if self.max_tokens <= 8192 else 8192,
            )
        elif self.provider == "ollama":
            ollama_adapter = ChatOllama(
                model=self.model,
                temperature=self.temperature,
                base_url=self.base_url or "http://localhost:11434",
                max_tokens=self.max_tokens,
                client_kwargs=self.client_kwargs
            )
            self.model = ollama_adapter.model
            return ollama_adapter
        elif self.provider in {"vllm", "lmstudio"}:
            # OpenAI-compatible local servers
            if self.provider == "lmstudio" and not self.api_key:
                self.api_key = "lm-studio"

            # For vLLM, query the server to get the actual model name. We can't leave this empty, unfortunately.
            if self.provider == "vllm" and self.model=="vllm_model":
                model_name = self.get_vllm_model_name(self.base_url, self.api_key)
                self.model = model_name
            else:
                model_name = self.model if self.model else "lmstudio-model"

            llm = ChatOpenAI(
                model=model_name,
                temperature=self.temperature,
                api_key=SecretStr(self.api_key),
                base_url=self.base_url,
                max_tokens=self.max_tokens,
            )
            self.model = llm.model_name
            return llm
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def generate_text(
            self,
            messages: Union[str, List[BaseMessage]],
            system_prompt: Optional[str] = None,
            temperature: float = 0.1,
            files: Optional[List[Union[str, Path, dict]]] = None,
    ) -> BaseMessage:
        """
        Supports string input or LangChain message list, with optional multimodal files.

        :param messages: Text prompt or list of LangChain messages
        :param system_prompt: Optional system prompt
        :param temperature: Temperature for generation
        :param files: Optional list of file paths or content dicts for multimodal input
        :returns: Generated response message
        """
        if isinstance(messages, str):
            lc_messages = []
            if system_prompt:
                lc_messages.append(SystemMessage(content=system_prompt))

            # Create multimodal content if files are provided
            if files:
                multimodal_content = self.create_multimodal_content(messages, files)
                lc_messages.append(HumanMessage(content=multimodal_content))
            else:
                lc_messages.append(HumanMessage(content=messages))
        else:
            lc_messages = messages

        kwargs = {"temperature": temperature}
        if self.provider in ("google", "ollama") or "o3" in self.model or "gpt-5" in self.model:
            kwargs = {}

        try:
            response = self.llm.invoke(lc_messages, **kwargs)
        except Exception as e:
            raise e

        return response

    def create_multimodal_content(
        self,
        text: str,
        image_urls: Optional[List[str]] = None,
    ) -> List[dict]:
        """
        Create multimodal content structure for LangChain messages with media URLs.
        Only supports image URLs for now.

        :param text: Text content
        :param image_urls: List of media URLs (http/https)
        :returns: List of content blocks
        """
        content = []

        # Add image URLs first
        if image_urls:
            for url in image_urls:
                if not isinstance(url, str):
                    raise ValueError(f"Image URL must be a string, got {type(url)}")

                # Format based on provider
                if self.provider == "anthropic":
                    content.append(
                        {"type": "image", "source": {"type": "url", "url": url}}
                    )
                else:
                    # OpenAI-style format
                    content.append({"type": "image_url", "image_url": {"url": url}})

        # Add text content
        if text:
            content.append({"type": "text", "text": text})

        return content

    def set_structure(self, json_schema):
        if not json_schema:
            raise ValueError("json_schema is None")

        if isinstance(json_schema, str):
            json_schema = json.loads(json_schema)

        json.dumps(json_schema)  # To validate / raise an error

        # LM Studio needs some more guidance
        if self.provider == "lmstudio":
            json_schema = {"type": "json_schema", "json_schema": {"schema": json_schema}}
            self.llm = self.llm.bind(response_format=json_schema)
        else:
            self.llm = self.llm.with_structured_output(json_schema)
        self.structured_output = True

    @staticmethod
    def get_model_options(config) -> dict:
        """
        Returns model choice options for UserInput
        """
        models = LLMAdapter.get_models(config)
        if not models:
            return {}
        options = {model_id: model_values["name"] for model_id, model_values in models.items()}
        return options

    @staticmethod
    def get_model_providers(config) -> dict:
        """
        Returns available model providers through APIs
        """
        models = LLMAdapter.get_models(config)
        if not models:
            return {}
        providers = list(set([model_values.get("provider", "") for model_values in models.values()]))
        if not providers:
            return {}
        options = {provider: provider.capitalize() for provider in providers if provider}
        return options

    @staticmethod
    def get_models(config) -> dict:
        """
        Returns a dict with LLM models supported by 4CAT, either through an API or as a local option.
        Make sure to keep up-to-date!

        :returns dict, A dict with model IDs as keys and details as values
        """
        with (
            config.get("PATH_ROOT")
                    .joinpath("common/assets/llms.json")
                    .open() as available_models
        ):
            available_models = json.loads(available_models.read())
        return available_models


    @staticmethod
    def get_vllm_model_name(base_url: str, api_key: str = None) -> str:
        """
        Query vLLM server to get the name of the served model.
        """

        try:
            # vLLM exposes available models at /v1/models endpoint
            models_url = f"{base_url.rstrip('/')}/models"
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            response = requests.get(models_url, headers=headers, timeout=10)
            response.raise_for_status()
            models_data = response.json()

            # Get the first available model
            if models_data.get("data") and len(models_data["data"]) > 0:
                return models_data["data"][0]["id"]
            else:
                raise ValueError("No models found on vLLM server")
        except Exception as e:
            raise ValueError(f"Could not retrieve model name from vLLM server: {e}")
