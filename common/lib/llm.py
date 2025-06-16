from typing import List, Optional, Union
from pydantic import SecretStr
from langchain_core.messages import BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_mistralai import ChatMistralAI

from common.config_manager import config


class LLMAdapter:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.0,
    ):
        """
        provider: 'openai', 'google', 'mistral', 'ollama', 'vllm', 'lmstudio', 'mistral'
        model: model name (e.g., 'gpt-4o-mini', 'claude-3-opus', 'mistral-small', etc.)
        api_key: API key if required (OpenAI, Claude, Google, Mistral)
        base_url: for local models or Mistral custom endpoints
        """
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature

        self.llm: BaseChatModel = self._load_llm()

    def _load_llm(self) -> BaseChatModel:
        if self.provider == "openai":
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                api_key=self.api_key,
                base_url=self.base_url or "https://api.openai.com/v1"
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
                api_key=self.api_key,
                base_url=self.base_url  # Optional override
            )
        elif self.provider == "ollama":
            return ChatOllama(
                model=self.model,
                temperature=self.temperature,
                base_url=self.base_url or "http://localhost:11434"
            )
        elif self.provider in {"vllm", "lmstudio"}:
            # OpenAI-compatible local servers
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                api_key=self.api_key,
                base_url=self.base_url
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def text_generation(
        self,
        messages: Union[str, List[BaseMessage]],
        system_prompt: Optional[str] = None,
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

        try:
            response = self.llm.invoke(lc_messages).content
        except Exception as e:
            raise e

        return response

    @staticmethod
    def get_model_options() -> dict:
        """
        Returns model choice options for UserInput
        """

        models = LLMAdapter.get_models()
        options = {model_id: model_values["name"] for model_id, model_values in models.items()}
        return options


    @staticmethod
    def get_models() -> dict:
        """
        Returns a dict with LLM models supported by 4CAT, either through an API or as a local option.
        Make sure to keep up-to-date!

        :returns dict, A dict with model IDs as keys and details as values
        """

        return {
            "gpt-4.1-mini": {
                "name": "[OpenAI API] GPT-4.1 mini",
                "model_card": "https://platform.openai.com/docs/models/gpt-4.1-mini",
                "provider": "openai"
            },
            "gpt-4.1 nano": {
                "name": "[OpenAI API] GPT-4.1 nano",
                "model_card": "https://platform.openai.com/docs/models/gpt-4.1-nano",
                "provider": "openai"
            },
            "gpt-4.1": {
                "name": "[OpenAI API] GPT-4.1",
                "model_card": "https://platform.openai.com/docs/models/gpt-4.1",
                "provider": "openai"
            },
            "gpt-4o-mini": {
                "name": "[OpenAI API] GPT-4o mini",
                "model_card": "https://platform.openai.com/docs/models/gpt-4o-mini",
                "provider": "openai"
            },
            "gpt-4o": {
                "name": "[OpenAI API] GPT-4o",
                "model_card": "https://platform.openai.com/docs/models/gpt-4o",
                "provider": "openai"
            },
            "o4-mini": {
                "name": "[OpenAI API] o4-mini",
                "model_card": "https://platform.openai.com/docs/models/o4-mini",
                "provider": "openai"
            },
            "o3": {
                "name": "[OpenAI API] o3",
                "model_card": "https://platform.openai.com/docs/models/o3",
                "provider": "openai"
            },
            "o3-pro": {
                "name": "[OpenAI API] o3-pro",
                "model_card": "https://platform.openai.com/docs/models/o3-pro",
                "provider": "openai"
            },
            "o3-mini": {
                "name": "[OpenAI API] o3-mini",
                "model_card": "https://platform.openai.com/docs/models/o3-mini",
                "provider": "openai"
            },
            "gemini-2.0-flash": {
                "name": "[Google API] Gemini 2.0 Flash",
                "model_card": "https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-0-flash",
                "provider": "google"
            },
            "gemini-2.0-flash-lite": {
                "name": "[Google API] Gemini 2.0 Flash Lite",
                "provider": "google"
            },
            "gemini-2.5-pro-preview-06-05": {
                "name": "[Google API] Gemini 2.5 Pro (preview 06-05)",
                "model_card": "https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-pro",
                "provider": "google"
            },
            "gemini-2.5-flash-preview-05-20": {
                "name": "[Google API] Gemini 2.5 Flash (preview 05-20)",
                "model_card": "https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash",
                "provider": "google"
            },
            "gemma-3": {
                "name": "[Google API] Gemma 3",
                "model_card": "https://console.cloud.google.com/vertex-ai/publishers/google/model-garden/gemma3",
                "provider": "google"
            },
            "claude-opus-4-0": {
                "name": "[Anthropic API] Claude Opus 4 (latest)",
                "model_card": "https://www.anthropic.com/claude/opus",
                "provider": "anthropic"
            },
            "claude-sonnet-4-0": {
                "name": "[Anthropic API] Claude Sonnet 4 (latest)",
                "model_card": "https://docs.anthropic.com/en/release-notes/system-prompts#claude-opus-4",
                "provider": "anthropic"
            },
            "claude-3-5-haiku-latest": {
                "name": "[Anthropic API] Claude 3.5 Haiku (latest)",
                 "model_card": "https://www.anthropic.com/claude/haiku",
                "provider": "anthropic"
            },
            "magistral-small-2505": {
                "name": "[Mistral API] Magistral Small (25.05)",
                "model_card": "https://huggingface.co/mistralai/Magistral-Small-2506",
                "provider": "mistral"
            },
            "magistral-medium-2506": {
                "name": "[Mistral API] Magistral Medium (25.06)",
                "model_card": "https://mistral.ai/news/magistral",
                "provider": "mistral"
            },
            "mistral-small-2503": {
                "name": "[Mistral API] Mistral Small (25.03)",
                "model_card": "https://mistral.ai/news/mistral-small-3-1",
                "provider": "mistral",
                "default": True
            },
            "mistral-medium-2506": {
                "name": "[Mistral API] Magistral Medium (2506)",
                "model_card": "https://mistral.ai/news/mistral-medium-3",
                "provider": "mistral"
            },
            "mistral-large-2506": {
                "name": "[Mistral API] Mistral Large (25.06)",
                "model_card": "https://mistral.ai/news/mistral-large",
                "provider": "mistral"
            },
            "open-mistral-nemo": {
                "name": "[Mistral API] Mistral Nemo",
                "model_card": "https://mistral.ai/news/mistral-nemo",
                "provider": "mistral"
            }
        }