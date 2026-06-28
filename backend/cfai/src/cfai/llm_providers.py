"""
LLM provider abstraction — interface única sobre Anthropic + OpenAI-compat.

5 providers suportados: Anthropic, OpenAI, DeepSeek, Groq, Minimax.
Os 4 últimos compartilham o `openai` SDK com `base_url` parametrizado
(todos expõem chat.completions OpenAI-compatible).

Schema enforcement:
- json_mode=True faz o provider tentar retornar JSON estruturado:
  - Anthropic: instrução explícita no prompt + parser tolerante
  - OpenAI: response_format={"type": "json_object"}
  - DeepSeek/Groq/Minimax: idem (json_object — todos suportam)
- Resposta sem JSON parseável marca `schema_failure=True` no LLMResponse;
  parser tolerante tenta extrair `{...}` da string antes de falhar.

Cada `complete()` registra telemetria em `cost_tracker` (latency, tokens, $).

Faltando key da env var → ValueError no construtor; smoke test deve skipar.

Uso:
    from cfai.llm_providers import OpenAIProvider, GroqProvider
    p = OpenAIProvider()              # usa OPENAI_API_KEY do env
    resp = p.complete(system="...", user="...", json_mode=True)
    print(resp["parsed"], resp["cost_usd"])
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional, TypedDict

from .cost_tracker import cost_tracker


class LLMResponse(TypedDict):
    content: str                        # raw text retornado
    parsed: Optional[dict]              # JSON parseado ou None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    schema_failure: bool
    model: str
    provider: str


_THINK_TAG_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)
_THINK_TEXT_RE = re.compile(
    r"^\s*Thinking\.{3}.*?\.{3}done thinking\.\s*",
    re.IGNORECASE | re.DOTALL,
)


def _parse_json_tolerant(text: str) -> Optional[dict]:
    """Tenta json.loads direto; se falhar, busca o último `{...}` no texto.
    LLMs frequentemente envolvem JSON em markdown, comentários ou blocos de
    raciocínio. Suporta:
      - `<think>...</think>` (Claude-style hidden reasoning)
      - `Thinking... ...done thinking.` (qwen3-thinking via Ollama)
      - markdown fences ```json ... ```
    Estratégia: limpa thinking → tenta direto → tenta último objeto top-level.
    """
    text = _THINK_TAG_RE.sub("", text)
    text = _THINK_TEXT_RE.sub("", text)
    text = text.strip()
    # Remove fences markdown ```json ... ``` ou ``` ... ```
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback 1: extrair último objeto top-level (pula JSON dentro de
    # thinking/explicações). rfind último '}' + procurar '{' balanceado.
    last_brace = text.rfind("}")
    if last_brace == -1:
        return None
    depth = 0
    for i in range(last_brace, -1, -1):
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                candidate = text[i: last_brace + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None


# ============================================================
# Anthropic
# ============================================================

class AnthropicProvider:
    family = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: Optional[str] = None,
    ):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "anthropic SDK ausente. Instale: pip install anthropic"
            ) from e
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key or key.startswith("test_"):
            raise ValueError("ANTHROPIC_API_KEY ausente ou placeholder")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model
        self.name = f"anthropic-{model}"

    def complete(
        self, system: str, user: str,
        json_mode: bool = True, temperature: float = 0.0,
        max_tokens: int = 1024, label: Optional[str] = None,
    ) -> LLMResponse:
        if json_mode:
            user = (user + "\n\nIMPORTANT: Output ONLY valid JSON, no prose, "
                          "no markdown fences. Start with { and end with }.")
        t0 = time.monotonic()
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        content = resp.content[0].text if resp.content else ""
        parsed = _parse_json_tolerant(content) if json_mode else None
        schema_failure = json_mode and parsed is None
        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        cost = cost_tracker.record(
            provider=self.family, model=self.model,
            in_tokens=in_tok, out_tokens=out_tok,
            latency_ms=latency_ms, schema_failure=schema_failure,
            label=label,
        ).cost_usd
        return LLMResponse(
            content=content, parsed=parsed,
            input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=cost, latency_ms=latency_ms,
            schema_failure=schema_failure,
            model=self.model, provider=self.family,
        )


# ============================================================
# OpenAI-compatible base
# ============================================================

class OpenAICompatibleProvider:
    """Base para OpenAI/DeepSeek/Groq/Minimax. Subclasses só setam defaults."""
    family = "openai_compatible"  # subclasses sobrescrevem
    default_model = ""
    default_base_url: Optional[str] = None
    env_var = "OPENAI_API_KEY"
    # Local thinking-models (Ollama qwen3) não respondem em strict json_object —
    # produzem string vazia. Subclasses setam False pra confiar no parser.
    supports_response_format = True

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK ausente. Instale: pip install openai"
            ) from e
        key = api_key or os.getenv(self.env_var)
        if not key:
            raise ValueError(f"{self.env_var} ausente no env")
        self.client = OpenAI(
            api_key=key,
            base_url=base_url or self.default_base_url,
        )
        self.model = model or self.default_model
        self.name = f"{self.family}-{self.model}"

    def complete(
        self, system: str, user: str,
        json_mode: bool = True, temperature: float = 0.0,
        max_tokens: int = 1024, label: Optional[str] = None,
    ) -> LLMResponse:
        # gpt-5 / o-series exigem max_completion_tokens; modelos antigos
        # exigem max_tokens. Tentativa optimista + fallback automático.
        token_param = (
            "max_completion_tokens"
            if self.model.startswith(("gpt-5", "o1", "o3", "o4"))
            else "max_tokens"
        )
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            token_param: max_tokens,
        }
        if json_mode and self.supports_response_format:
            kwargs["response_format"] = {"type": "json_object"}
        t0 = time.monotonic()
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            err = str(e).lower()
            # Alguns providers não aceitam json_object — retry sem
            if json_mode and "response_format" in err:
                kwargs.pop("response_format", None)
                resp = self.client.chat.completions.create(**kwargs)
            # gpt-5 / o-series não aceitam temperature != 1 (ou nem o param)
            elif "temperature" in err and "unsupported" in err:
                kwargs.pop("temperature", None)
                resp = self.client.chat.completions.create(**kwargs)
            # Fallback do max_tokens / max_completion_tokens (caso heurística falhe)
            elif "max_tokens" in err or "max_completion_tokens" in err:
                kwargs.pop("max_tokens", None)
                kwargs.pop("max_completion_tokens", None)
                alt_param = (
                    "max_tokens" if token_param == "max_completion_tokens"
                    else "max_completion_tokens"
                )
                kwargs[alt_param] = max_tokens
                resp = self.client.chat.completions.create(**kwargs)
            else:
                raise
        latency_ms = int((time.monotonic() - t0) * 1000)
        content = resp.choices[0].message.content or ""
        parsed = _parse_json_tolerant(content) if json_mode else None
        schema_failure = json_mode and parsed is None
        in_tok = resp.usage.prompt_tokens if resp.usage else 0
        out_tok = resp.usage.completion_tokens if resp.usage else 0
        cost = cost_tracker.record(
            provider=self.family, model=self.model,
            in_tokens=in_tok, out_tokens=out_tok,
            latency_ms=latency_ms, schema_failure=schema_failure,
            label=label,
        ).cost_usd
        return LLMResponse(
            content=content, parsed=parsed,
            input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=cost, latency_ms=latency_ms,
            schema_failure=schema_failure,
            model=self.model, provider=self.family,
        )


# ============================================================
# Concrete OpenAI-compatible providers
# ============================================================

class OpenAIProvider(OpenAICompatibleProvider):
    family = "openai"
    default_model = "gpt-5-mini"
    env_var = "OPENAI_API_KEY"


class DeepSeekProvider(OpenAICompatibleProvider):
    family = "deepseek"
    default_model = "deepseek-v4-flash"
    default_base_url = "https://api.deepseek.com/v1"
    env_var = "DEEPSEEK_API_KEY"


class GroqProvider(OpenAICompatibleProvider):
    family = "groq"
    default_model = "qwen/qwen3-32b"
    default_base_url = "https://api.groq.com/openai/v1"
    env_var = "GROQ_API_KEY"


class MinimaxProvider(OpenAICompatibleProvider):
    """MiniMax — OpenAI-compatible at api.minimax.io/v1.

    Model is env-selectable via MINIMAX_MODEL (mirrors OLLAMA_MODEL /
    UNSLOTH_MODEL), so the harnesses — which all instantiate providers via
    bare ``cls()`` — can target a specific MiniMax model (e.g. MiniMax-M3)
    without editing each script. Resolution: arg > MINIMAX_MODEL > default.

    Reasoning handling: MiniMax-M3+ are reasoning models that emit
    ``<think>...</think>`` and burn output tokens reasoning before the JSON.
    Two mitigations, applied only when the model looks like a reasoner
    (name contains "m3"; override with MINIMAX_REASONING=1/0):
      1. Skip strict ``response_format=json_object`` — unreliable for
         reasoners — and lean on the prompt's "output ONLY JSON" instruction
         plus the tolerant parser (which strips ``<think>``). Same approach
         as OllamaProvider for qwen3-thinking.
      2. Enforce a higher max_tokens floor so a long reasoning trace doesn't
         truncate the JSON mid-object (the cause of schema-parse failures).
    M2.7 and other non-reasoning models are unaffected.
    """
    family = "minimax"
    default_model = "MiniMax-M2.7"
    default_base_url = "https://api.minimax.io/v1"
    env_var = "MINIMAX_API_KEY"
    # Token floor for reasoning models: room for <think> + the full JSON block.
    reasoning_min_max_tokens = 8192

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(
            model=model or os.getenv("MINIMAX_MODEL"),
            api_key=api_key,
            base_url=base_url,
        )
        flag = os.getenv("MINIMAX_REASONING")
        if flag is not None:
            self.is_reasoning = flag.strip().lower() in ("1", "true", "yes", "on")
        else:
            self.is_reasoning = "m3" in self.model.lower()
        if self.is_reasoning:
            # Trust prompt-based JSON + tolerant parser instead of json_object.
            self.supports_response_format = False

    def complete(
        self, system: str, user: str,
        json_mode: bool = True, temperature: float = 0.0,
        max_tokens: int = 1024, label: Optional[str] = None,
    ) -> LLMResponse:
        if self.is_reasoning:
            max_tokens = max(max_tokens, self.reasoning_min_max_tokens)
        return super().complete(
            system=system, user=user, json_mode=json_mode,
            temperature=temperature, max_tokens=max_tokens, label=label,
        )


class GrokProvider(OpenAICompatibleProvider):
    """xAI Grok — distinto do GroqProvider (api.groq.com, OSS hosting).

    API OpenAI-compatible em https://api.x.ai/v1. Env var XAI_API_KEY
    (canônica nos docs xAI); aceita GROK_API_KEY como alias.
    """
    family = "grok"
    default_model = "grok-4-1-fast-reasoning"
    default_base_url = "https://api.x.ai/v1"
    env_var = "XAI_API_KEY"

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # Aceita GROK_API_KEY como alias — usuários frequentemente confundem
        # com XAI_API_KEY. Resolução: arg > XAI_API_KEY > GROK_API_KEY.
        resolved_key = (
            api_key
            or os.getenv(self.env_var)
            or os.getenv("GROK_API_KEY")
        )
        super().__init__(model=model, api_key=resolved_key, base_url=base_url)


class OllamaProvider(OpenAICompatibleProvider):
    """Local Ollama (qwen3.6:35b-a3b-coding-mxfp8 etc).

    Configurável via env:
      OLLAMA_BASE_URL   (default: http://localhost:11434/v1)
      OLLAMA_MODEL      (default: qwen3.6:35b-a3b-coding-mxfp8)

    Sem API key. Custo registrado como 0 (modelo desconhecido no PRICING).
    Health check via GET /api/tags (endpoint nativo Ollama, sempre 200 quando
    o daemon está up).
    """
    family = "ollama"
    default_model = "qwen3.6:35b-a3b-coding-mxfp8"
    default_base_url = "http://localhost:11434/v1"
    env_var = "OLLAMA_API_KEY"  # opcional
    # Modelos qwen3-thinking via Ollama travam em response_format=json_object
    # (retornam string vazia). Confiamos em prompt-based JSON + tolerant parser.
    supports_response_format = False

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK ausente. Instale: pip install openai"
            ) from e
        resolved_base = (
            base_url
            or os.getenv("OLLAMA_BASE_URL")
            or self.default_base_url
        )
        # Health: ollama nativo /api/tags retorna {models: [...]} se daemon up
        try:
            import urllib.request
            host = resolved_base.split("/")[2]  # ex: localhost:11434
            urllib.request.urlopen(
                f"http://{host}/api/tags", timeout=1.5,
            ).close()
        except Exception as e:
            raise ValueError(
                f"Ollama unreachable at {resolved_base!r} "
                f"(GET /api/tags failed: {type(e).__name__}). "
                f"Inicie com `ollama serve`."
            ) from e

        self.client = OpenAI(
            api_key=api_key or os.getenv(self.env_var) or "ollama",
            base_url=resolved_base,
        )
        self.model = (
            model or os.getenv("OLLAMA_MODEL") or self.default_model
        )
        self.name = f"{self.family}-{self.model}"


class UnslothProvider(OpenAICompatibleProvider):
    """Local Unsloth Studio (qwen-3.6-35b-a3b-gguf etc).

    Configurável via env:
      UNSLOTH_BASE_URL  (default: http://localhost:8888/api)
      UNSLOTH_MODEL     (default: qwen-3.6-35b-a3b-gguf)

    Sem API key. Custo registrado como 0 (cost_tracker fallback p/ modelo
    desconhecido). Latência real é capturada no record.
    """
    family = "unsloth"
    default_model = "qwen-3.6-35b-a3b-gguf"
    default_base_url = "http://localhost:8888/api"
    env_var = "UNSLOTH_API_KEY"  # opcional

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK ausente. Instale: pip install openai"
            ) from e
        resolved_base = (
            base_url
            or os.getenv("UNSLOTH_BASE_URL")
            or self.default_base_url
        )
        # Health check — sem isso, harnesses que tentam tudo iam crashar
        # ao primeiro complete() em vez de skip-ar limpo.
        try:
            import urllib.request
            host = resolved_base.split("/")[2]  # ex: localhost:8888
            urllib.request.urlopen(
                f"http://{host}/", timeout=1.0,
            ).close()
        except Exception as e:
            raise ValueError(
                f"Unsloth endpoint {resolved_base!r} unreachable: "
                f"{type(e).__name__}"
            ) from e

        self.client = OpenAI(
            api_key=api_key or os.getenv(self.env_var) or "sk-local",
            base_url=resolved_base,
        )
        self.model = (
            model or os.getenv("UNSLOTH_MODEL") or self.default_model
        )
        self.name = f"{self.family}-{self.model}"


# ============================================================
# Factory util
# ============================================================

PROVIDER_CLASSES: dict[str, type] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "groq": GroqProvider,
    "minimax": MinimaxProvider,
    "grok": GrokProvider,
    "ollama": OllamaProvider,
    "unsloth": UnslothProvider,
}


def make_provider(family: str, **kwargs):
    """Factory: `make_provider("groq")` → GroqProvider() ou raise."""
    cls = PROVIDER_CLASSES.get(family)
    if not cls:
        raise ValueError(
            f"Unknown provider {family!r}. Known: {list(PROVIDER_CLASSES)}"
        )
    return cls(**kwargs)


def available_providers() -> list[str]:
    """Quais providers têm key válida no env. Útil pra smoke tests."""
    out = []
    for name, cls in PROVIDER_CLASSES.items():
        try:
            cls()
            out.append(name)
        except (ValueError, ImportError):
            pass
    return out
