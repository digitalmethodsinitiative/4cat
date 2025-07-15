import json

from flask import g
from typing import List, Optional, Union
from pydantic import SecretStr
from langchain_core.messages import BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers.json import JsonOutputParser
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_mistralai import ChatMistralAI

class LLMAdapter:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        structured_output = False,
        json_schema = None,
        temperature: float = 0.0,
    ):
        """
        provider: 'openai', 'google', 'mistral', 'ollama', 'lmstudio', 'mistral'
        model: model name (e.g., 'gpt-4o-mini', 'claude-3-opus', 'mistral-small', etc.)
        api_key: API key if required (OpenAI, Claude, Google, Mistral)
        base_url: for local models or Mistral custom endpoints
        structured_output: if true, structured output is returned
        json_schema: use a custom JSON schema
        """
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.llm: BaseChatModel = self._load_llm()
        self.structured_output = structured_output
        self.parser = None

        if structured_output:
            self.set_structure(json_schema=json_schema)

    def _load_llm(self) -> BaseChatModel:
        if self.provider == "openai":
            kwargs = {}
            if "o3" not in self.model:
                kwargs["temperature"] = self.temperature # temperature not supported for all models
            return ChatOpenAI(
                model=self.model,
                api_key=SecretStr(self.api_key),
                base_url=self.base_url or "https://api.openai.com/v1",
                **kwargs
            )
        elif self.provider == "google":
            return ChatGoogleGenerativeAI(
                model=self.model,
                temperature=self.temperature,
                google_api_key=self.api_key
            )
        elif self.provider == "anthropic":
            return ChatAnthropic(
                model_name=self.model,
                temperature=self.temperature,
                api_key=SecretStr(self.api_key),
                timeout=100,
                stop=None
            )
        elif self.provider == "mistral":
            return ChatMistralAI(
                model_name=self.model,
                temperature=self.temperature,
                api_key=SecretStr(self.api_key),
                base_url=self.base_url  # Optional override
            )
        elif self.provider == "ollama":
            ollama_adapter = ChatOllama(
                model=self.model,
                temperature=self.temperature,
                base_url=self.base_url or "http://localhost:11434"
            )
            self.model = ollama_adapter.model
            return ollama_adapter
        elif self.provider in {"vllm", "lmstudio"}:
            # OpenAI-compatible local servers
            if self.provider == "lmstudio" and not self.api_key:
                self.api_key = "lm-studio"
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                api_key=SecretStr(self.api_key),
                base_url=self.base_url
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def generate_text(
        self,
        messages: Union[str, List[BaseMessage]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
    ) -> str:
        """
        Supports string input or LangChain message list.
        """
        if isinstance(messages, str):
            from langchain_core.messages import HumanMessage, SystemMessage
            lc_messages = []
            if system_prompt:
                lc_messages.append(SystemMessage(content=system_prompt))
            lc_messages.append(HumanMessage(content=messages))
        else:
            lc_messages = messages

        kwargs = {"temperature": temperature}
        if self.provider == "google":  # Temperature not supported here by Google
            kwargs = {}
        try:
            response = self.llm.invoke(lc_messages, **kwargs)
        except Exception as e:
            raise e

        return response if self.structured_output else response.content

    def set_structure(self, json_schema=None):
        if json_schema:
            self.llm = self.llm.with_structured_output(json_schema)
        else:
            self.llm = self.llm.with_structured_output(method="json_mode")

        self.structured_output = True

    @staticmethod
    def get_model_options(config) -> dict:
        """
        Returns model choice options for UserInput

        """

        models = LLMAdapter.get_models(config)
        options = {model_id: model_values["name"] for model_id, model_values in models.items()}
        return options

    @staticmethod
    def get_models(config) -> dict:
        """
        Returns a dict with LLM models supported by 4CAT, either through an API or as a local option.
        Make sure to keep up-to-date!

        :returns dict, A dict with model IDs as keys and details as values
        """

        with (
            config.PATH_ROOT
            .joinpath("common/assets/llms.json")
            .open() as available_models
        ):
            available_models = json.loads(available_models.read())
        return available_models