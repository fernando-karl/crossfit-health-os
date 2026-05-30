"""
OCR Lab Report Parser
Extract biomarkers from PDF lab reports using OpenAI GPT-4 Vision.

Flow:
1. User uploads PDF or image of lab report
2. PDF pages converted to images (if PDF)
3. Images sent to GPT-4o with structured extraction prompt
4. Returns list of parsed biomarkers with values and reference ranges
"""
import base64
import io
import logging

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

EXTRACTION_PROMPT = """Analyze this lab report image and extract ALL biomarker readings.

For each biomarker found, return a JSON array of objects with these fields:
- "name": biomarker name in English (e.g., "Hemoglobin", "Glucose", "TSH")
- "value": numeric value as a float
- "unit": measurement unit (e.g., "mg/dL", "g/dL", "mIU/L")
- "reference_min": lower reference range (float or null)
- "reference_max": upper reference range (float or null)
- "status": "normal", "low", or "high" based on reference range
- "category": one of "hematology", "metabolic", "lipid", "thyroid", "liver", "kidney", "vitamin", "hormone", "inflammatory", "other"

Important:
- Extract ALL values visible in the report
- If reference range shows "up to X", set reference_min=null and reference_max=X
- If reference range shows "X - Y", set reference_min=X and reference_max=Y
- Handle Portuguese lab terms (hemograma, glicemia, colesterol, etc.)
- Return ONLY the JSON array, no other text"""


async def _image_to_base64(image_bytes: bytes) -> str:
    """Convert image bytes to base64 data URL."""
    return base64.b64encode(image_bytes).decode("utf-8")


async def _pdf_to_images(pdf_bytes: bytes) -> list[bytes]:
    """
    Convert PDF pages to images.
    Uses pdf2image if available, falls back to sending raw bytes.
    """
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=200, fmt="jpeg")
        result = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            result.append(buf.getvalue())
        return result
    except ImportError:
        logger.warning("pdf2image not installed, attempting direct image analysis")
        return [pdf_bytes]
    except Exception as e:
        logger.error(f"PDF conversion failed: {e}")
        raise ValueError(f"Could not convert PDF: {e}")


async def parse_lab_report(
    file_bytes: bytes,
    filename: str = "",
    content_type: str = "",
) -> list[dict]:
    """
    Parse lab report and extract biomarkers using GPT-4o Vision.

    Args:
        file_bytes: Raw file content
        filename: Original filename
        content_type: MIME type

    Returns:
        List of biomarker dicts with name, value, unit, reference range, status
    """
    is_pdf = (
        content_type == "application/pdf"
        or filename.lower().endswith(".pdf")
    )

    if is_pdf:
        images = await _pdf_to_images(file_bytes)
    else:
        images = [file_bytes]

    all_biomarkers = []

    for page_bytes in images:
        b64 = await _image_to_base64(page_bytes)

        # Detect image type
        if page_bytes[:4] == b"\x89PNG":
            media_type = "image/png"
        else:
            media_type = "image/jpeg"

        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
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
                max_tokens=4096,
                temperature=0,
            )

            content = response.choices[0].message.content.strip()

            # Parse JSON from response (handle markdown code blocks)
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]

            import json
            biomarkers = json.loads(content)

            if isinstance(biomarkers, list):
                all_biomarkers.extend(biomarkers)
            else:
                logger.warning(f"Unexpected response format: {type(biomarkers)}")

        except Exception as e:
            logger.error(f"GPT-4o Vision extraction failed: {e}", exc_info=True)
            continue

    # Deduplicate by name (keep last occurrence = most recent page)
    seen = {}
    for bm in all_biomarkers:
        seen[bm.get("name", "").lower()] = bm

    return list(seen.values())
