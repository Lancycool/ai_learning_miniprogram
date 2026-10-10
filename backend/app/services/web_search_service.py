"""Optional search enrichment. Failures never become quiz generation errors."""
import asyncio
import ipaddress
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from aiohttp import ClientError

from app.core.config import Settings
from app.core.observability import record_web_search
from app.models.web_search import SearchSource, WebSearchMetadata

logger = logging.getLogger(__name__)
SENSITIVE = re.compile(r"(?:sk-|tvly-)[\w*-]{6,}|(?:api[_ -]?key|password|secret|密码|密钥)\s*[:=：]\s*\S+|(?<!\d)1[3-9]\d{9}(?!\d)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.I)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
INJECTION = re.compile(r"ignore (?:all |previous |the )*(?:instructions|rules)|忽略.{0,10}(?:指令|规则|提示)|system\s*prompt|<\/?(?:system|assistant)>|泄露.{0,6}(?:密钥|密码)", re.I)
PRIMARY_DOMAINS = ("openai.com", "anthropic.com", "langchain.com", "tavily.com", "python.org", "developer.mozilla.org", "learn.microsoft.com")


def public_domain(host: str) -> bool:
    host = host.lower().rstrip(".")
    if not host or host.endswith((".local", ".localhost", ".internal")) or host == "localhost":
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return bool(re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host))


class SearchPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str = Field(min_length=2, max_length=300)
    topic: Literal["general", "news", "finance"] = "general"
    search_depth: Literal["basic", "advanced"] = "advanced"
    max_results: int = Field(default=8, ge=1, le=8)
    time_range: Literal["week", "month", "year"] | None = None
    include_domains: tuple[str, ...] = ()

    @field_validator("include_domains")
    @classmethod
    def validate_domains(cls, value):
        if len(value) > 3 or not all(public_domain(host) for host in value):
            raise ValueError("invalid domains")
        return value

    def params(self) -> dict:
        return self.model_dump(mode="json", exclude={"query"}, exclude_none=True)


class SearchFailure(Exception):
    def __init__(self, reason: str, retryable: bool = False, retry_after: float | None = None):
        super().__init__(reason)
        self.reason, self.retryable, self.retry_after = reason, retryable, retry_after


def build_search_plan(text: str) -> SearchPlan:
    if SENSITIVE.search(text):
        raise SearchFailure("sensitive_input")
    # Long pasted text is reduced to its opening topic, never forwarded wholesale.
    query = re.split(r"[\n。！？!?]", text, maxsplit=1)[0][:180].strip()
    query = re.sub(r"^(?:请|我想|我要)?(?:学习|了解|弄懂|解释|理解)\s*", "", query).strip()
    if len(query) < 2:
        raise SearchFailure("parameter_error")
    terms = re.findall(r"[A-Za-z][A-Za-z0-9]+", query)
    spaced = [re.sub(r"([a-z])([A-Z])", r"\1 \2", term) for term in terms if re.search(r"[a-z][A-Z]", term)]
    if spaced:
        query += " " + " ".join(spaced)
    # Preserve explicit constraints even when they follow the opening topic.
    versions = re.findall(r"(?:版本\s*|\bv)\d+(?:\.\d+){0,3}", text, re.I)
    query = " ".join([query, *versions])[:300].strip()
    topic = "general"
    if re.search(r"新闻|时事|近期事件|news|current events", text, re.I):
        topic = "news"
    elif re.search(r"行情|股价|汇率|市场走势|stock price|exchange rate", text, re.I):
        topic = "finance"
    stable = bool(re.search(r"天空.*蓝|咖啡.*提神|基础概念|什么是光合作用|勾股定理|机会成本", text))
    complex_topic = bool(re.search(r"最新|版本|比较|区别|\bv\d|工程|engineering", text, re.I))
    depth = "basic" if stable and not complex_topic else "advanced"
    window = None
    for pattern, value in [(r"最近(?:一|1)?周|past week", "week"), (r"最近(?:一|1)?个?月|past month", "month"), (r"最近(?:一|1)?年|past year", "year")]:
        if re.search(pattern, text, re.I):
            window = value
            break
    domains = ()
    if re.search(r"官方|站点|site:", text, re.I):
        hosts = re.findall(r"(?:https?://|site:)([A-Za-z0-9.-]+)", text)
        domains = tuple(dict.fromkeys(h.lower() for h in hosts))[:3]
    return SearchPlan(query=query, topic=topic, search_depth=depth, max_results=5 if depth == "basic" else 8, time_range=window, include_domains=domains)


def classify_failure(error) -> SearchFailure:
    if isinstance(error, SearchFailure):
        return error
    if isinstance(error, TimeoutError):
        return SearchFailure("timeout", True)
    value = str(error)  # Used only for classification; never logged or returned.
    match = re.search(r"(?:Error|status(?:_code)?)\s*[:=]?\s*(\d{3})", value, re.I)
    status = int(match.group(1)) if match else None
    if status == 429:
        return SearchFailure("rate_limited", True)
    if status in (401, 403):
        return SearchFailure("authentication_error")
    if status in (432, 433):
        return SearchFailure("quota_exhausted")
    if status and status >= 500:
        return SearchFailure("upstream_error", True)
    if re.search(r"No search results|empty results", value, re.I):
        return SearchFailure("empty_results")
    if isinstance(error, (ConnectionError, OSError, ClientError)):
        return SearchFailure("connection_error", True)
    return SearchFailure("tool_error")


def normalize_results(raw, plan: SearchPlan) -> list[SearchSource]:
    if not isinstance(raw, dict):
        raise classify_failure(raw)
    if "error" in raw:
        raise classify_failure(raw["error"])
    rows = raw.get("results")
    if not isinstance(rows, list) or not rows:
        raise SearchFailure("empty_results")
    query = re.sub(r"\W", "", plan.query.lower())
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", plan.query.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", plan.query)
    tokens += [word[i:i+2] for word in chinese for i in range(len(word)-1) if word[i:i+2] not in {"最新", "学习", "最近", "一个", "官方"}]
    results, seen, remaining = [], set(), 6000
    # Prefer clearly official-looking results, without treating the ranking as verification.
    def source_rank(row):
        try:
            host = (urlsplit(str(row.get("url", ""))).hostname or "").lower()
        except ValueError:
            host = ""
        return not any(host == domain or host.endswith("."+domain) for domain in (*PRIMARY_DOMAINS, *plan.include_domains))
    rows = sorted((r for r in rows if isinstance(r, dict)), key=source_rank)
    for row in rows:
        if len(results) >= 8 or remaining < 100:
            break
        url, title, body = row.get("url"), row.get("title"), row.get("content")
        if not all(isinstance(v, str) for v in (url, title, body)):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not public_domain(parsed.hostname or "") or parsed.username or parsed.password or len(url) > 500 or SENSITIVE.search(url):
                continue
        except ValueError:
            continue
        text = CONTROL.sub("", body).strip()
        title = CONTROL.sub("", title).strip()[:200]
        combined = re.sub(r"\W", "", (title + " " + text).lower())
        relevant = query in combined or any(re.sub(r"\W", "", token) in combined for token in tokens)
        if not relevant or not text or INJECTION.search(text + title) or SENSITIVE.search(text):
            continue
        key = url.rstrip("/")
        if key in seen or any(s.content == text[:1500] for s in results):
            continue
        seen.add(key)
        overhead = len(title) + len(url) + 60
        text = text[:min(1500, remaining - overhead)]
        if not text:
            continue
        remaining -= overhead + len(text)
        date = row.get("published_date")
        results.append(SearchSource(source_id=f"src_{len(results)+1}", title=title or "参考资料", url=url, content=text, published_at=date[:40] if isinstance(date, str) else None))
    if not results:
        raise SearchFailure("no_usable_results")
    return results


class TavilySearchProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def search(self, plan: SearchPlan, timeout: float):
        # Imports and credential access happen only after the effective switch check.
        from langchain_tavily import TavilySearch
        from langchain_tavily._utilities import TavilySearchAPIWrapper
        import aiohttp

        key = self.settings.tavily_api_key.get_secret_value()
        if not key:
            raise SearchFailure("missing_api_key")

        class BoundedWrapper(TavilySearchAPIWrapper):
            http_timeout: float = timeout

            async def raw_results_async(self, **params):
                params = {k: v for k, v in params.items() if v is not None}
                headers = {"Authorization": f"Bearer {self.tavily_api_key.get_secret_value()}", "X-Client-Source": "langchain-tavily"}
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.http_timeout)) as session:
                    async with session.post("https://api.tavily.com/search", json=params, headers=headers, allow_redirects=False) as response:
                        if response.status != 200:
                            delay = None
                            retry = response.headers.get("Retry-After")
                            if retry:
                                try:
                                    delay = max(0.0, float(retry))
                                except ValueError:
                                    try:
                                        delay = max(0.0, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                                    except (ValueError, TypeError, OverflowError):
                                        pass
                            error = classify_failure(f"Error {response.status}")
                            raise SearchFailure(error.reason, error.retryable, delay)
                        # The tool response is bounded before JSON parsing.
                        chunks, size = [], 0
                        async for chunk in response.content.iter_chunked(65536):
                            size += len(chunk)
                            if size > 1_000_000:
                                raise SearchFailure("response_too_large")
                            chunks.append(chunk)
                        return json.loads(b"".join(chunks))

        try:
            tool = TavilySearch(api_wrapper=BoundedWrapper(tavily_api_key=key), **plan.params(), include_answer=False, include_raw_content=False, include_images=False, auto_parameters=False, handle_tool_error=False)
        except Exception as exc:
            raise SearchFailure("tool_init_error") from exc
        try:
            return await tool.ainvoke({"query": plan.query})
        except aiohttp.ClientError as exc:
            raise SearchFailure("connection_error", True) from exc


class WebSearchService:
    def __init__(self, settings: Settings, provider=None, clock=time.monotonic, sleep=asyncio.sleep):
        self.settings = settings
        self.provider = provider or TavilySearchProvider(settings)
        self.clock, self.sleep = clock, sleep
        self.slots = asyncio.Semaphore(settings.tavily_max_concurrency)
        self.failures = 0
        self.last_failure = 0.0
        self.open_until = 0.0
        self.probing = False

    def log(self, metadata: WebSearchMetadata, request_id: str, started: float):
        try:
            fields = {"search_request_id": request_id, "search_status": metadata.status, "search_params": metadata.effective_params, "elapsed_ms": round((self.clock()-started)*1000), "error_type": metadata.fallback_reason, "attempt_count": metadata.attempt_count, "prompt_path": metadata.prompt_version}
            emit = logger.warning if metadata.status == "fallback" else logger.info
            emit("quiz_web_search %s", json.dumps(fields, ensure_ascii=False), extra=fields)
        except Exception:
            pass  # Logging infrastructure cannot block the original quiz chain.

    async def enrich(self, text: str, option: bool | None, deadline: float, request_id: str) -> WebSearchMetadata:
        started = self.clock()
        requested = self.settings.enable_web_search if option is None else option
        enabled = self.settings.enable_web_search and (option is not False)
        meta = WebSearchMetadata(requested=requested, enabled=enabled, status="fallback" if enabled else "disabled")
        if not enabled:
            self.log(meta, request_id, started)
            return meta
        acquired, probe = False, False
        try:
            plan = build_search_plan(text)
            meta.effective_params = plan.params()
            budget = min(started + self.settings.tavily_search_budget_seconds, deadline - self.settings.request_timeout_seconds)
            if budget <= self.clock():
                raise SearchFailure("search_budget_insufficient")
            if self.open_until:
                if self.clock() < self.open_until or self.probing:
                    raise SearchFailure("circuit_open")
                self.probing = probe = True
            try:
                async with asyncio.timeout(min(self.settings.tavily_queue_timeout_seconds, budget-self.clock())):
                    await self.slots.acquire()
                    acquired = True
            except TimeoutError as exc:
                raise SearchFailure("queue_timeout") from exc
            for attempt in range(self.settings.tavily_max_retries + 1):
                limit = self.settings.tavily_search_timeout_seconds if attempt == 0 else self.settings.tavily_fallback_timeout_seconds
                remaining = budget - self.clock()
                if remaining <= 0:
                    raise SearchFailure("search_budget_insufficient")
                meta.effective_params = plan.params()
                meta.attempt_count += 1
                try:
                    async with asyncio.timeout(min(limit, remaining)):
                        raw = await self.provider.search(plan, min(limit, remaining))
                        sources = normalize_results(raw, plan)
                    meta.sources, meta.context_used, meta.status = sources, True, "success"
                    meta.prompt_version = "quiz_prompt_web_v1"
                    self.failures, self.open_until = 0, 0.0
                    break
                except Exception as exc:
                    failure = classify_failure(exc)
                    if failure.retryable:
                        now = self.clock()
                        self.failures = self.failures+1 if now-self.last_failure <= 60 else 1
                        self.last_failure = now
                        if probe or self.failures >= self.settings.tavily_circuit_failure_threshold:
                            self.open_until = now+self.settings.tavily_circuit_cooldown_seconds
                    elif failure.reason in {"empty_results", "no_usable_results"}:
                        # The upstream responded normally; absence of useful
                        # evidence is a per-query fallback, not a service outage.
                        self.failures, self.open_until = 0, 0.0
                    elif probe:
                        self.open_until = self.clock()+self.settings.tavily_circuit_cooldown_seconds
                    if not failure.retryable or attempt == self.settings.tavily_max_retries or probe or self.open_until > self.clock():
                        raise failure from exc
                    delay = failure.retry_after if failure.retry_after is not None else 0.5+random.uniform(0, 0.25)
                    if self.clock()+delay+self.settings.tavily_fallback_timeout_seconds > budget:
                        raise failure from exc
                    await self.sleep(delay)
                    plan = plan.model_copy(update={"search_depth": "basic", "max_results": 5})
        except Exception as exc:
            meta.fallback_reason = classify_failure(exc).reason
            meta.sources, meta.context_used, meta.status = [], False, "fallback"
            meta.prompt_version = "quiz_prompt_v1"
        finally:
            if acquired:
                self.slots.release()
            if probe:
                self.probing = False
            record_web_search(meta.status, self.clock() - started)
        self.log(meta, request_id, started)
        return meta
