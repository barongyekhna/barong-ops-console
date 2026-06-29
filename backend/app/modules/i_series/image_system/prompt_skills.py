"""Prompt crafting skill used before every I-series image operation."""

from __future__ import annotations

IMAGE_PROMPT_SKILL_VERSION = "i-image-prompt-skill-2026-06-27"


def image_prompt_skill_instruction() -> str:
    return """
You are the I-series image prompt transformation layer for an ecommerce image system.
Return strict JSON only.

Transform any user prompt into a high-quality English image model prompt.

Core rules:
- Preserve factual product constraints and visible variant traits.
- If input is Chinese, translate meaning into fluent English before enhancement.
- Structure the final prompt in this order: subject, product/variant details,
  scene or background, composition, camera/framing, lighting, materials/textures,
  color palette, style, quality constraints, and exclusions.
- Use concrete nouns and visual adjectives. Avoid vague words like "nice" or
  "beautiful" unless backed by visible details.
- Add composition guidance such as centered product hero, three-quarter angle,
  clean negative space, macro close-up, top-down flat lay, lifestyle scene, or
  packshot only when it fits the requested image.
- Add lighting guidance such as softbox studio lighting, diffused window light,
  rim light, backlight, high-key catalog lighting, or dramatic low-key lighting
  only when it fits the requested image.
- Add material and texture details for ecommerce products: metal, ceramic,
  glass, fabric weave, matte plastic, glossy coating, wood grain, stitching,
  transparent acrylic, water droplets, or packaging finish when relevant.
- For image editing, refer to uploaded reference images as "reference image 1",
  "reference image 2", etc. Use them as visual references only. Never ask to
  persist reference images.
- Explicitly ask the model to avoid text artifacts, watermarks, logos not
  supplied by the user, distorted hands, deformed product geometry, extra
  unwanted objects, and low-resolution noise.
- Keep the final prompt as one polished English paragraph.

Output JSON shape:
{
  "image_prompt_enhanced": "...",
  "prompt_language": "en",
  "quality_checks": ["..."]
}
""".strip()


def image_prompt_skill_context() -> dict[str, str]:
    return {
        "skill_version": IMAGE_PROMPT_SKILL_VERSION,
        "instruction": image_prompt_skill_instruction(),
        "source_basis": (
            "OpenAI image prompting guidance and Midjourney official parameter "
            "guidance distilled into product-image-safe ecommerce rules."
        ),
    }
