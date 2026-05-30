"""
Meal photo analyzer.

Sends a plate/meal image to GPT-4o Vision and returns an estimated breakdown:
total calories + macros, plus a list of identified foods with portion guesses.
Falls back to a deterministic rule-based stub when no OPENAI_API_KEY is set or
the API call fails — keeps the UI testable in dev/CI without external deps.
"""
from __future__ import annotations

import base64
import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


_PROMPT = """You are a nutritionist analyzing a meal photo.

Identify each visible food item and estimate:
- portion size (e.g., "1 cup cooked", "150g", "1 piece")
- calories (kcal)
- protein (grams)
- carbs (grams)
- fat (grams)

Return ONLY a JSON object with this exact shape (no markdown, no commentary):
{
  "foods": [
    {"name": "<food in pt-BR>", "portion": "<portion>", "calories": <int>, "protein_g": <int>, "carbs_g": <int>, "fat_g": <int>}
  ],
  "totals": {"calories": <int>, "protein_g": <int>, "carbs_g": <int>, "fat_g": <int>},
  "description": "<one short sentence summarizing the meal in pt-BR>",
  "confidence": "<low|medium|high>"
}

If the image does not contain food, return: {"foods": [], "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}, "description": "Sem comida identificada", "confidence": "low"}

Be conservative with portion sizes when uncertain. Round all numbers to integers."""


def _detect_media_type(image_bytes: bytes, fallback: str = "image/jpeg") -> str:
    if image_bytes[:4] == b"\x89PNG":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def _stub_response(reason: str) -> dict:
    """Deterministic placeholder when AI is unavailable. Keeps the UI testable."""
    return {
        "foods": [],
        "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
        "description": "",
        "confidence": "unavailable",
        "ai_used": False,
        "reason": reason,
    }


async def parse_meal_photo(image_bytes: bytes, content_type: str = "") -> dict:
    """Analyze a meal photo and return estimated macros + identified foods."""
    if not settings.OPENAI_API_KEY:
        return _stub_response("No OPENAI_API_KEY configured")

    media_type = _detect_media_type(image_bytes, fallback=content_type or "image/jpeg")
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=1200,
            temperature=0,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            # Strip a leading ```json ... ``` fence the model occasionally adds.
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        parsed = json.loads(content)
        parsed.setdefault("foods", [])
        parsed.setdefault("totals", {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0})
        parsed.setdefault("description", "")
        parsed.setdefault("confidence", "medium")
        parsed["ai_used"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 — never fail the request on AI errors
        logger.error("Meal photo parsing failed: %s", exc, exc_info=True)
        return _stub_response(f"AI parse error: {type(exc).__name__}")
