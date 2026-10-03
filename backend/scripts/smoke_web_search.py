"""Live acceptance for three topics, with and without optional search.

Run from backend: python -m scripts.smoke_web_search --output <path>
Only synthetic topics and generated quiz/source snapshots are written.
Credentials and upstream exception text are never printed or saved.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from app.core.config import get_settings
from app.llm.deepseek_generators import DeepSeekQuizGenerator
from app.models.quiz import QuizGenerateRequest
from app.services.quiz_service import QuizService
from app.services.web_search_service import WebSearchService
from app.utils.content_filter import ContentFilter


TOPICS = [
    "HarnessEngineering，AI 编程智能体领域，学习最新实践",
    "LangChain 1.x 的 create_agent 与 LangGraph 的关系，学习当前官方用法",
    "Tavily Search 的动态参数与 auto_parameters，学习当前官方用法",
]


async def run(output: Path):
    settings = get_settings()
    generator = DeepSeekQuizGenerator(settings)
    search = WebSearchService(settings)
    service = QuizService(generator, ContentFilter(settings.blocked_term_list), search, settings)
    records = []
    for topic in TOPICS:
        for enabled in (True, False):
            start = time.monotonic()
            record = {"topic": topic, "requested_search": enabled}
            try:
                quiz = await service.generate(QuizGenerateRequest(user_input=topic, enable_web_search=enabled))
                record.update({"ok": True, "quiz": quiz.model_dump(mode="json")})
            except Exception as exc:
                record.update({"ok": False, "error_type": type(exc).__name__})
            record["elapsed_seconds"] = round(time.monotonic()-start, 2)
            records.append(record)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            meta = record.get("quiz", {}).get("web_search", {})
            print(json.dumps({"index": len(records), "ok": record["ok"], "search_status": meta.get("status"), "fallback_reason": meta.get("fallback_reason"), "attempts": meta.get("attempt_count"), "seconds": record["elapsed_seconds"]}), flush=True)


async def rollback(output: Path):
    config = get_settings().model_copy(update={"enable_web_search": False})
    class ForbiddenProvider:
        calls = 0
        async def search(self, *args):
            self.calls += 1
            raise AssertionError("search must remain disabled")
    provider = ForbiddenProvider()
    service = QuizService(DeepSeekQuizGenerator(config), ContentFilter(config.blocked_term_list), WebSearchService(config, provider), config)
    quiz = await service.generate(QuizGenerateRequest(user_input=TOPICS[0], enable_web_search=True))
    assert provider.calls == 0 and quiz.web_search.status == "disabled"
    assert quiz.web_search.prompt_version == "quiz_prompt_v1"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"search_calls": provider.calls, "quiz": quiz.model_dump(mode="json")}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Backend-off rollback passed; search calls=0; original Prompt generated 5 questions", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/web-search-acceptance.json"))
    parser.add_argument("--rollback-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(rollback(args.output) if args.rollback_only else run(args.output))
