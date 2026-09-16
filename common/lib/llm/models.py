"""
Present the configured LLM model inventory to processors.

Kept separate from `common.lib.llm.adapter` on purpose: that module pulls in the
whole LangChain stack, while this one only reads 4CAT settings. A processor that
merely needs to list models or a test that needs to check the filtering can
import this without the heavy dependencies.
"""


def supports_task(model: dict, task: str = "generate") -> bool:
    """
    Check whether a model entry can be used for a given task.

    Entries built before `supported_tasks` existed carry no task info. They all
    predate embedding support, so they read as generative rather than vanishing
    from every processor until the inventory is next refreshed.

    :param dict model:  A single `llm.available_models` entry.
    :param str task:  Task to check for - `"generate"` or `"embed"`.
    :return bool:  Whether the model supports the task.
    """
    return task in model.get("supported_tasks", ["generate"])


def get_model_library(config, task: str = "generate") -> dict:
    """
    Get the LLM models available for a given task, grouped by server.

    Only models that are both enabled and capable of `task` are returned, so a
    prompting processor never offers an embedding model and an embedding
    processor never offers a generative one. Without this filter either choice
    produces a dataset that only fails once the request reaches the server.

    :param config:  4CAT config reader (context-aware, so per-user `llm.access`
      is respected)
    :param str task:  Task the model must support - `"generate"` or `"embed"`.
    :return dict:  `{server name: {model ID: model display name}}`, shaped for
      a `UserInput.OPTION_CHOICE` option.
    """
    available_models = config.get("llm.available_models", {})
    enabled_model_ids = config.get("llm.enabled_models", [])
    servers = config.get("llm.servers", {})
    if not config.get("llm.access"):
        enabled_model_ids = [_ for _ in enabled_model_ids if _.startswith("thirdparty")]

    models_option = {}
    for key, value in {k: v for k, v in available_models.items() if k in enabled_model_ids}.items():
        if not supports_task(value, task):
            continue

        server = servers[value["server"]]
        if server["name"] not in models_option:
            models_option[server["name"]] = {}

        models_option[server["name"]][key] = value["name"]

    return models_option
