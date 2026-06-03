"""OpenRouter direction-decision helper for Binance OpenRouter Trader."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Literal, Optional, TypeVar

try:
    from pydantic import BaseModel, Field
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight test environments
    class BaseModel:
        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

        @classmethod
        def model_validate_json(cls, raw_json: str):
            return cls(**json.loads(raw_json))

        @classmethod
        def model_json_schema(cls) -> dict[str, Any]:
            return {
                "type": "object",
                "properties": {"decision": {"type": "string", "enum": ["LONG", "SHORT"]}},
                "required": ["decision"],
                "additionalProperties": False,
            }

        def model_dump(self) -> dict[str, Any]:
            return dict(self.__dict__)

        def model_dump_json(self, indent: Optional[int] = None) -> str:
            return json.dumps(self.model_dump(), indent=indent, ensure_ascii=False)

    def Field(default: Any = None, **_kwargs: Any) -> Any:
        return default

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight test environments
    class _RequestsFallback:
        def post(self, *_args, **_kwargs):
            raise ModuleNotFoundError("requests is required to call OpenRouter APIs")

    requests = _RequestsFallback()

from src.infra.env_loader import get_openrouter_api_key
from src.infra.logger import format_log_details, get_logger

logger = get_logger("openrouter_trader")

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_GENERATE_MAX_RETRIES = 3
OPENROUTER_DIRECTION_MODEL = "deepseek/deepseek-v4-flash"
OPENROUTER_MAX_REASONING_EFFORT = "xhigh"
OPENROUTER_APP_TITLE = "binance-openrouter-trader"
_ONE_MILLION = 1_000_000

_OPENROUTER_MODEL_PRICING_USD_PER_MILLION: dict[str, dict[str, float]] = {
    OPENROUTER_DIRECTION_MODEL: {
        "input": 0.0983,
        "output": 0.1966,
    }
}

_SYSTEM_PROMPT = (
    "You are a world-class USDT-M perpetual futures trader. "
    "Use only the supplied symbol and close-price payload. "
    "Return exactly one JSON decision."
)

DecisionT = TypeVar("DecisionT", bound=BaseModel)


class TradeDirectionDecision(BaseModel):
    """Structured OpenRouter response for one pure symbol direction decision."""

    decision: Literal["LONG", "SHORT"] = Field(
        description="Return exactly one direction decision, LONG or SHORT, based on the supplied close-price data."
    )


@dataclass
class OpenRouterStructuredResponse(Generic[DecisionT]):
    """Container for a parsed OpenRouter decision plus raw diagnostics."""

    decision: DecisionT
    raw_response: str
    usage_metadata: dict[str, Any]
    response_payload: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    reasoning_details: list[dict[str, Any]] = field(default_factory=list)


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _to_jsonable(method())
            except Exception:
                pass
    return str(value)


def _safe_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _normalize_positive_price(value: Any, *, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive number") from exc
    if parsed <= 0.0:
        raise ValueError(f"{field_name} must be a positive number")
    return parsed


def _normalize_close_prices(values: Any) -> list[float]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError("close price payload must be a list")
    close_prices: list[float] = []
    for value in values:
        close_prices.append(_normalize_positive_price(value, field_name="close_price"))
    if not close_prices:
        raise ValueError("close price payload must not be empty")
    return close_prices


def _build_direction_input_payload(
    *,
    symbol: str,
    reference_price: float,
    timeframe_ohlcv: Dict[str, Any],
) -> Dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    if not isinstance(timeframe_ohlcv, dict) or not timeframe_ohlcv:
        raise ValueError("timeframe_ohlcv is required")

    normalized_timeframes: dict[str, list[float]] = {}
    for timeframe, close_values in timeframe_ohlcv.items():
        normalized_timeframe = str(timeframe or "").strip()
        if not normalized_timeframe:
            raise ValueError("timeframe key is required")
        normalized_timeframes[normalized_timeframe] = _normalize_close_prices(close_values)

    return {
        "symbol": normalized_symbol,
        "reference_price": _normalize_positive_price(reference_price, field_name="reference_price"),
        "timeframes": normalized_timeframes,
    }


def _format_direction_prompt(payload: Dict[str, Any]) -> str:
    symbol = str(payload.get("symbol") or "the supplied symbol").strip().upper() or "the supplied symbol"
    return (
        f"You are a world-class {symbol} trader.\n"
        "Use your best judgment to decide whether LONG or SHORT offers the higher expected value.\n"
        "Return JSON only: {\"decision\":\"LONG\"} or {\"decision\":\"SHORT\"}.\n"
        f"Market payload:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def _build_direction_prompt(
    *,
    symbol: str,
    reference_price: float,
    timeframe_ohlcv: Dict[str, Any],
) -> str:
    payload = _build_direction_input_payload(
        symbol=symbol,
        reference_price=reference_price,
        timeframe_ohlcv=timeframe_ohlcv,
    )
    return _format_direction_prompt(payload)


def _decision_json_schema(response_model: type[DecisionT]) -> dict[str, Any]:
    schema = response_model.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "trade_direction_decision",
            "strict": True,
            "schema": schema,
        },
    }


def estimate_openrouter_cost(
    usage_metadata: Optional[dict[str, Any]],
    *,
    model: str = OPENROUTER_DIRECTION_MODEL,
) -> Optional[dict[str, Any]]:
    usage = usage_metadata if isinstance(usage_metadata, dict) else {}
    pricing = _OPENROUTER_MODEL_PRICING_USD_PER_MILLION.get(str(model or "").strip())
    if not usage or not pricing:
        return None

    prompt_tokens = _safe_non_negative_int(usage.get("prompt_tokens"))
    completion_tokens = _safe_non_negative_int(usage.get("completion_tokens"))
    input_cost_usd = prompt_tokens * pricing["input"] / _ONE_MILLION
    output_cost_usd = completion_tokens * pricing["output"] / _ONE_MILLION
    return {
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": _safe_non_negative_int(usage.get("total_tokens")),
        "input_cost_usd": round(input_cost_usd, 12),
        "output_cost_usd": round(output_cost_usd, 12),
        "total_cost_usd": round(input_cost_usd + output_cost_usd, 12),
    }


def _is_retryable_openrouter_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return True
    return code == 429 or 500 <= code < 600


def _extract_message_payload(response_payload: Dict[str, Any]) -> Dict[str, Any]:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message")
    return message if isinstance(message, dict) else {}


def _extract_content_text(message_payload: Dict[str, Any]) -> str:
    content = message_payload.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        pieces: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    pieces.append(text)
            elif isinstance(item, str):
                pieces.append(item)
        return "".join(pieces).strip()
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return ""


def _normalize_reasoning_details(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in (_to_jsonable(row) for row in value) if isinstance(item, dict)]


def _save_direction_analysis_data(
    *,
    cycle_dir: str,
    prompt: str,
    prompt_payload: Dict[str, Any],
    raw_response: str,
    decision: Any,
    usage_metadata: Optional[Dict[str, Any]],
    response_payload: Optional[Dict[str, Any]],
    reasoning: str,
    reasoning_details: list[dict[str, Any]],
    model: str,
    reasoning_effort: str,
    decision_mode: str = "direction",
) -> Dict[str, str]:
    saved_paths: Dict[str, str] = {}
    try:
        if cycle_dir:
            os.makedirs(cycle_dir, exist_ok=True)
            normalized_mode = str(decision_mode or "direction").strip().lower() or "direction"
            input_path = os.path.join(cycle_dir, f"openrouter_ai_{normalized_mode}_input.json")
            output_path = os.path.join(cycle_dir, f"openrouter_ai_{normalized_mode}_output.json")
            with open(input_path, "w", encoding="utf-8") as file_obj:
                json.dump(
                    {
                        "model": model,
                        "reasoning_effort": reasoning_effort,
                        "decision_mode": normalized_mode,
                        "prompt": prompt,
                        "payload": prompt_payload,
                    },
                    file_obj,
                    indent=2,
                    ensure_ascii=False,
                )
            with open(output_path, "w", encoding="utf-8") as file_obj:
                json.dump(
                    {
                        "model": model,
                        "reasoning_effort": reasoning_effort,
                        "decision_mode": normalized_mode,
                        "decision": decision.model_dump(),
                        "raw_response": raw_response,
                        "reasoning": reasoning,
                        "reasoning_details": reasoning_details,
                        "usage_metadata": usage_metadata or {},
                        "estimated_cost": estimate_openrouter_cost(usage_metadata, model=model),
                        "response_payload": response_payload or {},
                    },
                    file_obj,
                    indent=2,
                    ensure_ascii=False,
                )
            saved_paths = {"input_path": input_path, "output_path": output_path}
    except Exception as exc:
        logger.warning("Failed to save OpenRouter AI analysis data: %s", exc)
    return saved_paths


def _call_openrouter_structured_decision(
    *,
    prompt: str,
    reasoning_effort: str,
    response_model: type[DecisionT],
    model: str = OPENROUTER_DIRECTION_MODEL,
    max_tokens: int = 8192,
    context_label: str = "direction",
) -> Optional[OpenRouterStructuredResponse[DecisionT]]:
    api_key = get_openrouter_api_key()
    normalized_reasoning_effort = str(reasoning_effort or OPENROUTER_MAX_REASONING_EFFORT).strip().lower()
    if normalized_reasoning_effort == "max":
        normalized_reasoning_effort = OPENROUTER_MAX_REASONING_EFFORT

    payload = {
        "model": str(model or OPENROUTER_DIRECTION_MODEL).strip() or OPENROUTER_DIRECTION_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "reasoning": {
            "effort": normalized_reasoning_effort,
            "exclude": False,
        },
        "response_format": _decision_json_schema(response_model),
        "max_tokens": max(1, int(max_tokens)),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": OPENROUTER_APP_TITLE,
    }

    last_error: Optional[Exception] = None
    for attempt in range(1, OPENROUTER_GENERATE_MAX_RETRIES + 1):
        try:
            logger.info(
                "OpenRouter futures decision call starting | %s",
                format_log_details(
                    {
                        "context": context_label,
                        "attempt": attempt,
                        "max_retries": OPENROUTER_GENERATE_MAX_RETRIES,
                        "model": payload["model"],
                        "reasoning_effort": normalized_reasoning_effort,
                        "prompt_chars": len(prompt or ""),
                    }
                ),
            )
            response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
            if getattr(response, "status_code", 200) >= 400:
                error = RuntimeError(f"OpenRouter HTTP {response.status_code}: {getattr(response, 'text', '')}")
                setattr(error, "status_code", response.status_code)
                raise error

            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise ValueError(f"OpenRouter returned unexpected payload: {response_payload!r}")
            message_payload = _extract_message_payload(response_payload)
            raw_response = _extract_content_text(message_payload)
            decision = response_model.model_validate_json(raw_response)
            usage_metadata = response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else {}
            reasoning = str(message_payload.get("reasoning") or "")
            reasoning_details = _normalize_reasoning_details(message_payload.get("reasoning_details"))

            logger.info(
                "OpenRouter futures decision call succeeded | %s",
                format_log_details(
                    {
                        "context": context_label,
                        "model": payload["model"],
                        "decision": getattr(decision, "decision", None),
                        "reasoning_chars": len(reasoning),
                        "reasoning_details": len(reasoning_details),
                        "usage": usage_metadata,
                    }
                ),
            )
            return OpenRouterStructuredResponse(
                decision=decision,
                raw_response=raw_response,
                usage_metadata=dict(usage_metadata),
                response_payload=response_payload,
                reasoning=reasoning,
                reasoning_details=reasoning_details,
            )
        except Exception as exc:
            last_error = exc
            if not _is_retryable_openrouter_error(exc) or attempt >= OPENROUTER_GENERATE_MAX_RETRIES:
                break
            sleep_seconds = min(8.0, 2.0 ** (attempt - 1))
            logger.warning(
                "OpenRouter futures %s call failed (attempt %s/%s): %s. Retrying in %ss.",
                context_label,
                attempt,
                OPENROUTER_GENERATE_MAX_RETRIES,
                exc,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)

    if last_error is not None:
        logger.error("OpenRouter futures %s call failed: %s", context_label, last_error, exc_info=True)
    return None


def evaluate_trade_direction(
    *,
    cycle_dir: str,
    symbol: str,
    reference_price: float,
    timeframe_ohlcv: Dict[str, Any],
    reasoning_effort: str,
    model: str = OPENROUTER_DIRECTION_MODEL,
    max_tokens: int = 8192,
    analysis_sink: Optional[Dict[str, Any]] = None,
    decision_mode: str = "direction",
) -> Optional[TradeDirectionDecision]:
    """Request one pure symbol LONG/SHORT direction decision and persist artifacts."""
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        logger.error("evaluate_trade_direction requires a symbol")
        return None

    try:
        prompt_payload = _build_direction_input_payload(
            symbol=normalized_symbol,
            reference_price=reference_price,
            timeframe_ohlcv=timeframe_ohlcv,
        )
        prompt = _format_direction_prompt(prompt_payload)
    except Exception as exc:
        logger.error("Invalid OpenRouter direction prompt payload: %s", exc)
        return None

    call_result = _call_openrouter_structured_decision(
        prompt=prompt,
        reasoning_effort=reasoning_effort,
        response_model=TradeDirectionDecision,
        model=model,
        max_tokens=max_tokens,
        context_label=decision_mode,
    )
    if call_result is None:
        return None

    decision = call_result.decision
    normalized_value = str(getattr(decision, "decision", "") or "").strip().upper()
    if normalized_value not in {"LONG", "SHORT"}:
        logger.error("OpenRouter returned invalid direction decision=%s", normalized_value)
        return None

    normalized_decision = TradeDirectionDecision(decision=normalized_value)
    saved_paths = _save_direction_analysis_data(
        cycle_dir=cycle_dir,
        prompt=prompt,
        prompt_payload=prompt_payload,
        raw_response=call_result.raw_response or normalized_decision.model_dump_json(indent=2),
        decision=normalized_decision,
        usage_metadata=call_result.usage_metadata,
        response_payload=call_result.response_payload,
        reasoning=call_result.reasoning,
        reasoning_details=call_result.reasoning_details,
        model=model,
        reasoning_effort=reasoning_effort,
        decision_mode=decision_mode,
    )

    if isinstance(analysis_sink, dict):
        analysis_sink.update(
            {
                "model": model,
                "reasoning_effort": reasoning_effort,
                "decision_mode": decision_mode,
                "decision": normalized_decision.model_dump(),
                "raw_response": call_result.raw_response,
                "reasoning": call_result.reasoning,
                "reasoning_details": list(call_result.reasoning_details),
                "usage_metadata": dict(call_result.usage_metadata or {}),
                "estimated_cost": estimate_openrouter_cost(call_result.usage_metadata, model=model),
                "response_payload": dict(call_result.response_payload or {}),
                **saved_paths,
            }
        )

    return normalized_decision


def evaluate_entry_direction(**kwargs: Any) -> Optional[TradeDirectionDecision]:
    """Compatibility alias for a single entry-direction decision."""
    return evaluate_trade_direction(**kwargs)


__all__ = [
    "OPENROUTER_DIRECTION_MODEL",
    "OPENROUTER_MAX_REASONING_EFFORT",
    "OpenRouterStructuredResponse",
    "TradeDirectionDecision",
    "estimate_openrouter_cost",
    "evaluate_entry_direction",
    "evaluate_trade_direction",
]
