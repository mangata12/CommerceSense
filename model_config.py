"""Session-scoped model settings; never mutate process environment variables."""

from dataclasses import dataclass, field
import os
import re


PROVIDERS = {
    "DeepSeek": ("DEEPSEEK_API_KEY", "deepseek-chat"),
    "OpenAI": ("OPENAI_API_KEY", "gpt-4o-mini"),
    "Google Gemini": ("GOOGLE_API_KEY", "gemini-2.5-flash"),
    "Anthropic Claude": ("ANTHROPIC_API_KEY", "claude-3-5-sonnet-latest"),
}
MODEL_TIMEOUT = 45
MODEL_RETRIES = 1


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model_name: str
    api_key: str = field(repr=False)


def resolve_model_settings(provider, model_name, session_key=""):
    if provider not in PROVIDERS:
        raise ValueError("不支持的模型服务")
    variable, _ = PROVIDERS[provider]
    key = session_key.strip() or os.environ.get(variable, "").strip()
    if not key:
        raise ValueError(f"调用模型前请在侧栏配置 {variable}，或在启动前设置该环境变量。")
    if not model_name.strip():
        raise ValueError("请填写模型名称")
    return ModelSettings(provider, model_name.strip(), key)


def create_chat_model(settings):
    options = {"model": settings.model_name, "api_key": settings.api_key,
               "temperature": 0, "timeout": MODEL_TIMEOUT, "max_retries": MODEL_RETRIES}
    if settings.provider in {"DeepSeek", "OpenAI"}:
        from langchain_openai import ChatOpenAI
        if settings.provider == "DeepSeek":
            options["base_url"] = "https://api.deepseek.com"
        return ChatOpenAI(**options)
    if settings.provider == "Google Gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(**options)
    if settings.provider == "Anthropic Claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(**options)
    raise ValueError("不支持的模型服务")


def safe_error(error, secrets=()):
    """Remove configured credentials before rendering provider error messages."""
    text = str(error)
    values = [*secrets, *(os.environ.get(variable, "") for variable, _ in PROVIDERS.values())]
    for secret in values:
        if secret:
            text = text.replace(secret, "[密钥已隐藏]")
    text = re.sub(r"(?i)bearer\s+[^\s,;\"']+", "Bearer [密钥已隐藏]", text)
    return text
