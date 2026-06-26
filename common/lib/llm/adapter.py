import json
import base64
import mimetypes

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
            model: dict,
            server: dict = None,
            api_key: Optional[str] = None,
            temperature: float = 0.1,
            max_tokens: int = 1000,
            client_kwargs: Optional[dict] = None,
    ):
        """
        Instantiate an adapter to interface with an LLM model

        :param dict model:  Model metadata (as in `llm.available_models` 4CAT
          setting)
        :param dict server:  Server metadata (as in `llm.servers` 4CAT setting)
        :param str api_key:  API key, if needed
        :param float temperature:  Temperature hyperparameter
        :param int max_tokens:  Max tokens to generate
        :param dict client_kwargs:  Optional parameters for the LLM adapter class
        """
        self.model = model
        self.server = server
        self.api_key = api_key
        self.temperature = temperature
        self.structured_output = False
        self.parser = None
        self.max_tokens = max_tokens
        self.client_kwargs = dict(client_kwargs) if client_kwargs else {}

        self.llm: BaseChatModel = self._load_llm()

    def _load_llm(self) -> BaseChatModel:
        """
        Load appropriate langchain chat class

        :return BaseChatModel:  Langchain chat model for interfacing with model
        """
        # The "wrapper" is which LangChain chat class to use for this model. For
        # self-hosted connections it equals the connection type; for the
        # third-party catalog (connection type "api") it is the model's vendor,
        # stamped per-model in build_model_entry. Dispatching on the wrapper
        # rather than the connection type is what lets third-party models
        # resolve to the right SDK.
        wrapper = self.model["wrapper"]

        chat_params = {
            "model": self.model["local_id"],
            "api_key": SecretStr(self.api_key),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        # Only pass a base URL when the connection actually has one. An empty
        # string is taken literally by some SDKs (Anthropic, DeepSeek -> empty
        # endpoint) instead of falling back to the vendor default.
        if self.server["url"]:
            chat_params["base_url"] = self.server["url"]

        if wrapper == "openai":
            if "o3" in self.model["local_id"]:
                del chat_params["temperature"]
            adapter_class = ChatOpenAI

        elif wrapper == "google":
            adapter_class = ChatGoogleGenerativeAI

        elif wrapper == "anthropic":
            chat_params.update({"timeout": 100, "stop": None})
            adapter_class = ChatAnthropic

        elif wrapper == "mistral":
            adapter_class = ChatMistralAI

        elif wrapper == "deepseek":
            chat_params["max_tokens"] = min(self.max_tokens, 8192)
            adapter_class = ChatDeepSeek

        elif wrapper == "ollama":
            adapter_class = ChatOllama
            chat_params.update({"client_kwargs": self.client_kwargs})

        elif wrapper in {"litellm", "openai-like"}:
            url = f"{self.server['url']}/" if not self.server["url"].endswith("/") else self.server['url']
            url += "v1/" if not url.endswith("v1/") else ""

            chat_params.update({"base_url": url})
            if self.server["auth_header"]:
                chat_params.update({
                    "default_headers": {
                        self.server["auth_header"]: self.server["auth_key"]
                    }
                })

            adapter_class = ChatOpenAI

        else:
            raise ValueError(f"{self.__class__.__name__} Unsupported LLM wrapper: {wrapper}")

        return adapter_class(**chat_params)

    def generate_text(
            self,
            messages: Union[str, List[BaseMessage]],
            system_prompt: Optional[str] = None,
            temperature: float = 0.1,
            files: Optional[List[str]] = None,
            media_files: Optional[List[Union[str, Path]]] = None,
    ) -> BaseMessage:
        """
        Supports string input or LangChain message list, with optional multimodal files.

        :param messages: Text prompt or list of LangChain messages
        :param system_prompt: Optional system prompt
        :param temperature: Temperature for generation
        :param files: Optional list of media URLs for multimodal input
        :param media_files: Optional list of local file paths for multimodal input (base64-encoded)
        :returns: Generated response message
        """
        if isinstance(messages, str):
            lc_messages = []
            if system_prompt:
                lc_messages.append(SystemMessage(content=system_prompt))

            # Create multimodal content if files are provided
            if files or media_files:
                multimodal_content = self.create_multimodal_content(
                    messages,
                    media_urls=files,
                    media_files=media_files,
                )
                lc_messages.append(HumanMessage(content=multimodal_content))
            else:
                lc_messages.append(HumanMessage(content=messages))
        else:
            lc_messages = messages

        kwargs = {"temperature": temperature}
        if self.model["wrapper"] in ("google", "ollama") or "o3" in self.model["local_id"] or "gpt-5" in self.model[
            "local_id"]:
            kwargs = {}

        try:
            response = self.llm.invoke(lc_messages, **kwargs)
        except Exception as e:
            raise e

        return response

    def create_multimodal_content(
            self,
            text: str,
            media_urls: Optional[List[str]] = None,
            media_files: Optional[List[Union[str, Path]]] = None,
    ) -> List[dict]:
        """
        Create multimodal content structure for LangChain messages with media URLs
        and/or local media files (base64-encoded).

        Supports images, video, and audio depending on the server and model.

        :param text: Text content
        :param media_urls: List of media URLs (http/https)
        :param media_files: List of local file paths to encode as base64
        :returns: List of content blocks
        """
        content = []

        # Add media URLs
        if media_urls:
            for url in media_urls:
                if not isinstance(url, str):
                    raise ValueError(f"Media URL must be a string, got {type(url)}")

                mime_type = mimetypes.guess_type(url.split("?")[0])[0] or "application/octet-stream"
                media_category = mime_type.split("/")[0]  # "image", "video", or "audio"
                content.append(self._format_media_block(url=url, mime_type=mime_type, media_category=media_category))

        # Add base64-encoded local files
        if media_files:
            for file_path in media_files:
                file_path = Path(file_path)
                if not file_path.exists():
                    raise ValueError(f"Media file not found: {file_path}")

                mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                media_category = mime_type.split("/")[0]

                with file_path.open("rb") as f:
                    b64_data = base64.b64encode(f.read()).decode("utf-8")

                content.append(self._format_media_block(
                    b64_data=b64_data, mime_type=mime_type, media_category=media_category
                ))

        # Add text content
        if text:
            content.append({"type": "text", "text": text})

        return content

    def _format_media_block(
            self,
            url: Optional[str] = None,
            b64_data: Optional[str] = None,
            mime_type: str = "image/jpeg",
            media_category: str = "image",
    ) -> dict:
        """
        Format a single media block for the appropriate server.

        :param url: Media URL (if URL-based)
        :param b64_data: Base64-encoded data (if file-based)
        :param mime_type: MIME type of the media
        :param media_category: "image", "video", or "audio"
        :returns: Server-formatted content block
        """
        if self.model["wrapper"] == "anthropic":
            if media_category == "image":
                if url:
                    return {"type": "image", "source": {"type": "url", "url": url}}
                else:
                    return {"type": "image", "source": {
                        "type": "base64", "media_type": mime_type, "data": b64_data
                    }}
            else:
                # Anthropic uses document blocks for video/audio
                if url:
                    return {"type": "document", "source": {"type": "url", "url": url}}
                else:
                    return {"type": "document", "source": {
                        "type": "base64", "media_type": mime_type, "data": b64_data
                    }}
        elif self.model["wrapper"] == "google":
            if url:
                return {"type": "image_url", "image_url": {"url": url}}
            else:
                data_uri = f"data:{mime_type};base64,{b64_data}"
                return {"type": "image_url", "image_url": {"url": data_uri}}
        elif self.model["wrapper"] == "ollama":
            if media_category != "image":
                raise ValueError(f"Ollama only supports image media, got category '{media_category}'")
            if url:
                return {
                    "type": "image_url",
                    "image_url": url,
                }
            else:
                data_uri = f"data:{mime_type};base64,{b64_data}"
                return {
                    "type": "image_url",
                    "image_url": data_uri
                }
        else:
            # OpenAI-style format (OpenAI, Mistral, DeepSeek, LM Studio, vLLM)
            if url:
                return {"type": "image_url", "image_url": {"url": url}}
            else:
                data_uri = f"data:{mime_type};base64,{b64_data}"
                if media_category == "audio" and self.model["wrapper"] == "openai":
                    return {"type": "input_audio", "input_audio": {
                        "data": b64_data, "format": mime_type.split("/")[-1]
                    }}
                return {"type": "image_url", "image_url": {"url": data_uri}}

    def set_structure(self, json_schema):
        """
        Set desired response JSON schema

        :param json_schema:
        """
        if not json_schema:
            raise ValueError("json_schema is None")

        if isinstance(json_schema, str):
            json_schema = json.loads(json_schema)

        json.dumps(json_schema)  # To validate / raise an error

        # LM Studio needs some more guidance
        if self.model["wrapper"] == "lmstudio":
            json_schema = {"type": "json_schema", "json_schema": {"schema": json_schema}}
            self.llm = self.llm.bind(response_format=json_schema)
        else:
            kwargs = {"include_raw": include_raw}
            if method:
                kwargs["method"] = method
            if strict is not None:
                kwargs["strict"] = strict
            self.llm = self.llm.with_structured_output(json_schema, **kwargs)
        self.structured_output = True
