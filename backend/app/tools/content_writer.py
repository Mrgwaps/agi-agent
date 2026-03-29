"""
ContentWriterTool — premium long-form content generation.

Implements patterns from:
  - alirezarezvani/claude-skills: content-creator, blog-writer, technical-writer
  - obra/superpowers-lab: elements-of-style writing quality enforcement
  - anthropics/skills: docx/pdf document production patterns

This tool is invoked for any step involving writing substantial content:
ebooks, guides, articles, reports, chapters, tutorials, etc.
It uses a premium LLM with a specialized writing persona and produces
complete, publication-ready Markdown.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ContentWriterTool(BaseTool):
    name = "content_writer"
    description = (
        "Write professional, publication-ready long-form content: ebooks, guides, "
        "articles, reports, tutorials, chapters, or any substantial written piece. "
        "Produces complete, polished Markdown with proper structure, headings, and "
        "actionable content. Never produces outlines or placeholders — always real content."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The topic or title of the content to write",
            },
            "content_type": {
                "type": "string",
                "description": "Type: ebook_chapter, guide_section, article, introduction, conclusion, overview",
                "enum": ["ebook_chapter", "guide_section", "article", "introduction", "conclusion", "overview", "general"],
                "default": "general",
            },
            "outline": {
                "type": "string",
                "description": "Optional outline or section headings to follow",
            },
            "context": {
                "type": "string",
                "description": "Prior research, facts, or notes to incorporate",
            },
            "style": {
                "type": "string",
                "description": "Tone and style: professional, conversational, academic, persuasive",
                "default": "professional",
            },
            "target_audience": {
                "type": "string",
                "description": "Who this content is for (e.g. 'beginner developers', 'small business owners')",
                "default": "general audience",
            },
            "word_count_target": {
                "type": "integer",
                "description": "Approximate target word count",
                "default": 1200,
            },
            "overall_goal": {
                "type": "string",
                "description": "The overarching task goal this content serves",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        from app.services.openrouter import ModelQuality, openrouter_client

        topic: str = input.get("topic", "").strip()
        content_type: str = input.get("content_type", "general")
        outline: str = input.get("outline", "")
        context: str = input.get("context", "")
        style: str = input.get("style", "professional")
        target_audience: str = input.get("target_audience", "general audience")
        word_count_target: int = int(input.get("word_count_target", 1200))
        overall_goal: str = input.get("overall_goal", topic)

        if not topic:
            return {"success": False, "result": None, "error": "topic is required"}

        system_prompt = self._build_system(style, target_audience)
        user_prompt = self._build_user(
            topic, content_type, outline, context, word_count_target, overall_goal
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            max_tokens = max(word_count_target * 2, 3000)  # generous buffer
            text, model, cost = await openrouter_client.chat_completion(
                messages=messages,
                task_type="writing",
                quality=ModelQuality.PREMIUM,
                max_tokens=min(max_tokens, 8192),
                temperature=0.65,
            )
            word_count = len(text.split())
            logger.info(
                "ContentWriterTool: wrote %d words for '%s' using %s (cost=$%.6f)",
                word_count, topic[:60], model, cost,
            )
            return {
                "success": True,
                "result": text,
                "metadata": {
                    "word_count": word_count,
                    "model": model,
                    "cost_usd": cost,
                    "content_type": content_type,
                },
                "error": None,
            }
        except Exception as exc:
            logger.exception("ContentWriterTool error: %s", exc)
            return {"success": False, "result": None, "error": str(exc)}

    def _build_system(self, style: str, audience: str) -> str:
        style_guide = {
            "professional": "authoritative, clear, and precise — like a respected industry expert",
            "conversational": "warm, direct, and engaging — like a knowledgeable friend explaining clearly",
            "academic": "rigorous, well-cited, and methodical — suitable for scholarly audiences",
            "persuasive": "compelling, evidence-driven, and motivating — moves the reader to action",
        }.get(style, "professional, clear, and authoritative")

        return f"""You are a world-class professional writer, author, and content creator with expertise in producing {style_guide} content.

Writing principles (Elements of Style + Content Creator best practices):
1. OMIT NEEDLESS WORDS. Every sentence must earn its place.
2. Use active voice. Strong verbs. Concrete nouns.
3. Lead with the most important point, then support it.
4. Structure content with clear H2/H3 headings that guide the reader.
5. Use specific examples, case studies, and real-world applications.
6. Anticipate reader questions and answer them preemptively.
7. Every section must deliver actionable value — no filler.
8. Write for {audience}. Use their vocabulary, address their concerns.
9. NEVER write outlines, bullet-point summaries, or placeholder text.
   Write COMPLETE, POLISHED, PUBLICATION-READY content.
10. Length targets are MINIMUMS — be comprehensive, not brief."""

    def _build_user(
        self,
        topic: str,
        content_type: str,
        outline: str,
        context: str,
        word_count_target: int,
        overall_goal: str,
    ) -> str:
        type_instructions = {
            "ebook_chapter": (
                "Write a complete ebook chapter. Include:\n"
                "- Engaging chapter opening that hooks the reader\n"
                "- 3-5 major sections with H2 headings\n"
                "- Practical examples or case studies in each section\n"
                "- Key takeaways box at the end\n"
                "- Chapter summary (3-5 bullet points)"
            ),
            "guide_section": (
                "Write a complete guide section. Include:\n"
                "- Clear section introduction explaining what the reader will learn\n"
                "- Step-by-step or concept-by-concept breakdown\n"
                "- Practical tips and real-world applications\n"
                "- Common mistakes to avoid\n"
                "- Section summary"
            ),
            "article": (
                "Write a complete article. Include:\n"
                "- Compelling headline and subheadline\n"
                "- Engaging introduction with a hook\n"
                "- Well-structured body with H2/H3 headings\n"
                "- Concrete examples and evidence\n"
                "- Strong conclusion with key insights"
            ),
            "introduction": (
                "Write a compelling introduction that:\n"
                "- Opens with a powerful hook (story, statistic, or provocative question)\n"
                "- Establishes why this topic matters to the reader\n"
                "- Previews what the reader will gain\n"
                "- Creates anticipation and motivates reading further"
            ),
            "conclusion": (
                "Write a strong conclusion that:\n"
                "- Synthesizes the key insights from the entire work\n"
                "- Reinforces the most important takeaways\n"
                "- Provides clear next steps or calls to action\n"
                "- Ends memorably — leave the reader inspired or motivated"
            ),
        }.get(content_type, "Write comprehensive, well-structured content on this topic.")

        parts = [
            f"Overall project goal: {overall_goal}",
            f"\nContent to write: {topic}",
            f"\nTarget length: approximately {word_count_target} words (this is a minimum — be thorough)",
            f"\n{type_instructions}",
        ]

        if outline:
            parts.append(f"\nOutline/structure to follow:\n{outline}")

        if context:
            parts.append(
                f"\nResearch and context to incorporate:\n{context[:3000]}"
                + ("\n[...additional context truncated...]" if len(context) > 3000 else "")
            )

        parts.append(
            "\nWrite the complete content now. "
            "Do not explain what you're about to write — just write it. "
            "Use proper Markdown formatting."
        )

        return "\n".join(parts)
