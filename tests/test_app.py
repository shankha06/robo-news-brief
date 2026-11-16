import asyncio
import gzip
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from starlette.requests import Request

import app


class ScoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app._cache._data.clear()

    async def test_daily_score_requests_parse_event_status_and_home_away(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"events": [{"id": "1", "date": "2026-11-15T20:00Z",
                "status": {"type": {"state": "post", "shortDetail": "After penalties"}},
                "competitions": [{"competitors": [
                    {"homeAway": "away", "team": {"displayName": "France"}, "score": "1"},
                    {"homeAway": "home", "team": {"displayName": "England"}, "score": "2"}
                ]}]}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with patch.object(app, "_http_client", client), patch.object(app, "_SCORE_FETCH_SEM", asyncio.Semaphore(6)):
                matches = await app._fetch_league_scores("uefa.nations", "Nations League", "UNL", "20261115")
        self.assertEqual(requests[0].url.params["dates"], "20261115")
        self.assertEqual(matches[0]["home"], "England")
        self.assertEqual(matches[0]["away"], "France")
        self.assertEqual(matches[0]["status_detail"], "After penalties")

    async def test_refresh_keeps_internationals_and_prioritizes_live(self):
        requests = []

        async def fetch(code, name, short, date):
            requests.append(date)
            return [{"event_id": code + date, "league_code": code, "league_short": short,
                     "home": "England" if short == "UNL" else "Liverpool", "away": "France",
                     "date": date, "state": "in" if short == "UNL" else "post"}]

        with patch.object(app, "_fetch_league_scores", fetch):
            matches = await app._refresh_scores()
        self.assertTrue(all("-" not in date for date in requests))
        self.assertEqual(matches[0]["state"], "in")
        self.assertIn("UNL", {match["league_short"] for match in matches})

    def test_major_fixture_beats_minor_fixture(self):
        important = {"home": "England", "away": "France", "league_short": "UNL", "stage": "Final"}
        minor = {"home": "Small Club", "away": "Other Club", "league_short": "L1"}
        self.assertGreater(app._score_match(important), app._score_match(minor))

    async def test_one_failed_league_does_not_break_other_results(self):
        async def fetch(code, name, short, date):
            if code == "eng.1":
                raise ValueError("Malformed upstream result")
            return [{"event_id": code + date, "league_code": code, "league_short": short,
                     "home": "England", "away": "France", "date": date, "state": "post"}]

        with patch.object(app, "_fetch_league_scores", fetch):
            matches = await app._refresh_scores()
        self.assertTrue(matches)
        self.assertNotIn("eng.1", {match["league_code"] for match in matches})


class ResearchRankingTests(unittest.TestCase):
    def item(self, title, description="", source="arXiv CS.IR", days=0):
        return {
            "title": title, "description": description, "source": source,
            "published": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),
            "link": "https://example.com/paper",
        }

    def test_substantive_paper_beats_model_hype(self):
        paper = self.item("Efficient dense retrieval with compact embeddings",
                          "Code and dataset released; ablation evaluation measures memory and latency.")
        hype = self.item("GPT-5 breakthrough beats Claude: unprecedented SOTA", source="Google AI News")
        self.assertGreater(app._score_ai_article(paper), app._score_ai_article(hype))

    def test_short_keywords_do_not_match_inside_words(self):
        self.assertEqual(app._tag_ai_article(self.item("Fragmented cartography in Mali")), "ML")

    def test_technical_blogs_are_not_penalized_as_soft_news(self):
        blog = self.item("How to evaluate dense retrieval", "Benchmark code and experiments", "HuggingFace")
        hype = self.item("Introducing a breakthrough", source="HuggingFace")
        self.assertGreater(app._score_ai_article(blog), app._score_ai_article(hype))

    def test_week_old_research_is_still_discoverable(self):
        recent = self.item("Dense retrieval evaluation", "Code and dataset")
        older = self.item("Dense retrieval evaluation", "Code and dataset", days=7)
        self.assertGreater(app._score_ai_article(older), app._score_ai_article(recent) * 0.45)

    def test_expert_tutorial_beats_fresh_keyword_rich_benchmark(self):
        tutorial = self.item("Conformal prediction under distribution shift",
                             "A derivation and worked example with a notebook, baselines, "
                             "confidence intervals and production trade-offs.", "Sebastian Raschka", days=100)
        benchmark = self.item("A benchmark for multimodal LLM agents and reasoning",
                             "We introduce a new dataset and evaluation benchmark.")
        self.assertGreater(app._score_ai_article(tutorial), app._score_ai_article(benchmark))

    def test_classical_ml_and_statistics_topics_are_covered(self):
        for title, expected in (("Gradient boosting on tabular data", "Tabular"),
                                ("Causal inference with treatment effects", "Causal"),
                                ("Conformal prediction for uncertainty", "Statistics"),
                                ("Time series forecasting", "Time Series")):
            with self.subTest(title=title):
                self.assertEqual(app._tag_ai_article(self.item(title)), expected)

    def test_advanced_introduction_is_not_treated_as_beginner_noise(self):
        advanced = self.item("Introduction to causal inference",
                             "Derivation, implementation and failure modes with baselines.")
        thin = self.item("Introduction to causal inference", "A quick overview.")
        self.assertGreater(app._score_ai_article(advanced), app._score_ai_article(thin) + 10)

    def test_learning_signals_are_grounded_in_text(self):
        self.assertEqual(app._learning_signals(self.item("A new model")), [])
        self.assertIn("Evaluation & reliability", app._learning_signals(self.item("Data leakage and failure modes")))

    def test_recent_publisher_model_launch_is_not_generic_marketing(self):
        release = self.item("Introducing Claude: a new reasoning model", "Now available with model weights", "Anthropic")
        self.assertEqual(app._research_kind(release), "release")
        self.assertGreater(app._score_ai_article(release), 20)
        old = self.item(release["title"], release["description"], "Anthropic", days=60)
        self.assertNotEqual(app._research_kind(old), "release")

    def test_release_slots_do_not_remove_technical_reading(self):
        releases = [self.item(f"Introducing GPT model {index}", "A new language model", "OpenAI") for index in range(10)]
        blog = self.item("Bayesian inference derivation", "Proof and baselines", "Sebastian Raschka")
        results = app._process_feeds(releases + [blog], "ai_research")
        self.assertEqual(results[0]["kind"], "release")
        self.assertLessEqual(sum(item["kind"] == "release" for item in results), 4)
        self.assertIn("blog", [item["kind"] for item in results])

    def test_community_hype_is_not_a_confirmed_model_release(self):
        item = self.item("Introducing Claude: new model released", "State of the art", "HN AI")
        self.assertEqual(app._research_kind(item), "community")

    def test_publisher_release_precedes_community_model_conversions(self):
        release = self.item("Introducing Gemini: new model", "Now available", "DeepMind")
        conversions = []
        for index in range(10):
            item = self.item(f"Quantized model {index}", "", "HF Model Releases")
            item.update(model_id=f"community/conversion-{index}", trending_score=1000)
            conversions.append(item)
        results = app._process_feeds(conversions + [release], "ai_research")
        self.assertEqual(results[0]["source"], "DeepMind")
        self.assertLessEqual(sum(item["source"] == "HF Model Releases" for item in results), 2)

    def test_customer_conversion_story_is_not_a_methodology_lesson(self):
        story = self.item("Example grows product signups with conversion optimization", source="OpenAI")
        self.assertEqual(app._learning_signals(story), [])
        self.assertLess(app._score_ai_article(story), 9)

    def test_curated_feed_preserves_cited_arxiv_papers(self):
        feed = b'''<rss><channel><item><title>Conformal prediction: a derivation</title>
        <link>https://example.com/post</link><description><![CDATA[Implementation and proof.
        <a href="https://arxiv.org/abs/2107.07511v2">Paper</a>
        <a href="https://arxiv.org/pdf/2107.07511.pdf">PDF</a>
        <a href="https://example.com/abs/1234.56789">Not arXiv</a>]]></description>
        </item></channel></rss>'''
        item = app._parse_feed("Sebastian Raschka", feed)[0]
        self.assertEqual(item["citedPapers"], ["2107.07511"])

    def test_revisited_foundational_paper_preserves_original_date(self):
        paper = self.item("Conformal prediction with uncertainty quantification", "Proof and baselines",
                          "Expert-cited Papers", days=1000)
        original_date = paper["published"]
        paper.update(citedBy=["Sebastian Raschka"], citedAt=datetime.now(timezone.utc).isoformat())
        self.assertGreater(app._score_ai_article(paper), 15)
        self.assertEqual(paper["published"], original_date)

    def test_core_data_science_topics_survive_popular_ai_papers(self):
        papers = [self.item(f"Multimodal agents LLM benchmark {index}", "Ablation implementation",
                            "HF Daily Papers") for index in range(25)]
        statistics = self.item("Conformal prediction theory", "Proof and confidence interval", "arXiv stat.ML")
        result = app._process_feeds(papers + [statistics], "ai_research")
        self.assertIn("Statistics", [item["tag"] for item in result])

    def test_authored_learning_material_is_not_crowded_out_by_vendor_posts(self):
        vendors = [self.item(f"Production implementation for LLM systems {index}",
                             "Ablation, proof and implementation in production.", "Nvidia AI")
                   for index in range(20)]
        authors = [self.item(f"Conformal prediction notebook {index}", "Proof and baselines",
                             source, days=120)
                   for index, source in enumerate(("BAIR", "Sebastian Raschka", "Maarten Grootendorst"))]
        results = app._process_feeds(vendors + authors, "ai_research")
        self.assertTrue({item["source"] for item in authors}.issubset({item["source"] for item in results}))
        self.assertLessEqual(sum(item["source"] == "Nvidia AI" for item in results), 2)

    def test_papers_do_not_crowd_out_technical_blogs(self):
        papers = [self.item(f"LLM agent evaluation {index}", "Ablation and implementation", "HF Daily Papers")
                  for index in range(25)]
        blogs = [self.item(f"Statistical inference example {index}", "Derivation and notebook",
                           source, days=90)
                 for index, source in enumerate(("BAIR", "Chip Huyen", "Lil'Log", "Sebastian Raschka"))]
        result = app._process_feeds(papers + blogs, "ai_research")
        self.assertEqual(sum(item["kind"] == "blog" for item in result), 4)
        self.assertLessEqual(sum(item["tag"] == "Agents" for item in result), 6)

    def test_community_discussion_cannot_dominate_learning_feed(self):
        items = [self.item(f"Tabular model production {index}", "Implementation baselines",
                           source)
                 for index, source in enumerate(["HN AI", "r/MachineLearning", "r/LocalLLaMA"] * 8)]
        result = app._process_feeds(items, "ai_research")
        self.assertLessEqual(len(result), 2)

    def test_generic_topic_words_are_not_independent_corroboration(self):
        first = self.item("Alpha benchmark for LLM agents")
        second = self.item("Beta benchmark for LLM agents", source="HF Daily Papers")
        ranked = app._process_feeds([first, second], "ai_research")
        target = next(item for item in ranked if item["title"] == first["title"])
        self.assertAlmostEqual(target["score"], app._score_ai_article(first), places=4)

    def test_scans_past_first_eight_entries_and_keeps_abstract(self):
        entries = [f"<item><title>Unrelated topic {index}</title><link>https://example.com/{index}</link></item>"
                   for index in range(50)]
        abstract = "Background. " * 20 + "Dense retrieval embeddings with code, dataset and latency evaluation."
        entries.append(f"<item><title>Efficient dense retrieval</title><link>https://arxiv.org/abs/2601.12345</link>"
                       f"<description>{abstract}</description></item>")
        feed = ("<rss><channel>" + "".join(entries) + "</channel></rss>").encode()
        items = app._parse_feed("arXiv CS.IR", feed)
        self.assertEqual(len(items), 40)
        self.assertEqual(items[0]["title"], "Efficient dense retrieval")
        self.assertIn("latency evaluation", items[0]["description"])

    def test_atom_alternate_link_and_namespaced_date(self):
        feed = b'''<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>Retrieval evaluation</title><link rel="self" href="https://example.com/api"/>
        <link rel="alternate" href="https://example.com/post"/>
        <updated>2026-11-01T10:00:00Z</updated><summary>Dataset and code</summary></entry></feed>'''
        item = app._parse_feed("HuggingFace", feed)[0]
        self.assertEqual(item["link"], "https://example.com/post")
        self.assertEqual(item["published"], "2026-11-01T10:00:00+00:00")

    def test_rdf_feed(self):
        feed = b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
        <item><title>Dense retrieval</title><link>https://example.com/post</link>
        <dc:date>2026-11-01</dc:date></item></rdf:RDF>'''
        self.assertTrue(app._parse_feed("arXiv CS.IR", feed)[0]["published"])

    def test_merges_paper_versions_and_preserves_votes_without_mutation(self):
        paper = self.item("Dense retrieval study")
        paper["link"] = "https://arxiv.org/abs/2601.12345v2"
        curated = self.item("Dense retrieval study (updated)", "Code and dataset released", "HF Daily Papers")
        curated.update(link="https://arxiv.org/pdf/2601.12345.pdf", upvotes=42)
        result = app._process_feeds([paper, curated], "ai_research")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["upvotes"], 42)
        self.assertEqual(result[0]["description"], curated["description"])
        self.assertNotIn("score", paper)
        self.assertNotIn("_fp", result[0])
        self.assertNotIn("_coverage", result[0])

    def test_distinct_titles_sharing_long_prefix_survive(self):
        prefix = "Understanding the implications of efficient embedding models for "
        items = [self.item(prefix + suffix) for suffix in ("retrieval", "classification")]
        self.assertEqual(len(app._process_feeds(items, "ai_research")), 2)

    def test_source_diversity(self):
        papers = [self.item(f"Dense retrieval experiment {index}") for index in range(25)]
        blog = self.item("Evaluating search systems", "Benchmark code", "Simon Willison")
        results = app._process_feeds(papers + [blog], "ai_research")
        self.assertIn("Simon Willison", [item["source"] for item in results])
        self.assertLessEqual(sum(item["source"].startswith("arXiv") for item in results), 8)


class FeedConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app._cache._data.clear()
        app._inflight.clear()
        app._feed_subscribers.clear()
        self.semaphore_patch = patch.object(app, "_FEED_FETCH_SEM", asyncio.Semaphore(6))
        self.semaphore_patch.start()

    async def asyncTearDown(self):
        tasks = list(app._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.semaphore_patch.stop()

    def request(self, category="ai_research"):
        return Request({"type": "http", "path_params": {"category": category}, "headers": []})

    async def test_model_discovery_uses_trends_and_does_not_relabel_old_models(self):
        now = datetime.now(timezone.utc)
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=[
                {"id": "google/gemma-new", "createdAt": now.isoformat(), "trendingScore": 100, "likes": 50},
                {"id": "google/old-popular-model", "createdAt": (now - timedelta(days=365)).isoformat(),
                 "lastModified": now.isoformat(), "trendingScore": 1000, "likes": 10000},
            ])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with patch.object(app, "_http_client", client):
                releases = await app._fetch_model_releases()
                await app._fetch_hf_trending_models()
        self.assertEqual(requests[0].url.params["sort"], "trendingScore")
        self.assertEqual(len(requests), 1)
        self.assertEqual([item["model_id"] for item in releases], ["google/gemma-new"])

    async def test_cited_paper_enrichment_is_batched_bounded_and_attributed(self):
        items = [{"title": "Conformal prediction derivation", "description": "Proof and implementation",
                  "source": "Sebastian Raschka", "published": "2026-11-01T00:00:00+00:00",
                  "citedPapers": [f"2601.{index:05}" for index in range(20)]}]
        calls = []

        async def fetch(name, url):
            calls.append((name, url))
            return [{"title": "Conformal prediction", "link": "https://arxiv.org/abs/2601.00000v2",
                     "published": "2026-01-01T00:00:00+00:00"}]

        with patch.object(app, "_fetch_feed_throttled", fetch):
            papers = await app._fetch_cited_papers(items)
        self.assertEqual(len(calls), 1)
        query = app.urllib.parse.parse_qs(app.urllib.parse.urlsplit(calls[0][1]).query)
        self.assertEqual(len(query["id_list"][0].split(",")), 12)
        self.assertEqual(papers[0]["citedBy"], ["Sebastian Raschka"])
        self.assertEqual(papers[0]["published"], "2026-01-01T00:00:00+00:00")

    async def test_concurrent_json_and_stream_share_refresh(self):
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def fetch(name, url):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return [{"title": "Dense retrieval", "source": name, "link": url}]

        async def consume():
            response = await app.api_news_stream(self.request("football"))
            return "".join([chunk async for chunk in response.body_iterator])

        with patch.dict(app.RSS_FEEDS, {"football": [("Test", "https://example.com/feed")]}), patch.object(app, "_fetch_feed", fetch):
            streams = [asyncio.create_task(consume()) for _ in range(5)]
            requests = [asyncio.create_task(app._fetch_all_feeds("football")) for _ in range(5)]
            await started.wait()
            release.set()
            output = await asyncio.gather(*streams, *requests)
        self.assertEqual(calls, 1)
        self.assertTrue(all("event: done" in stream for stream in output[:5]))
        self.assertFalse(app._feed_subscribers)

    async def test_research_stream_uses_research_ttl(self):
        app._set_cache("feeds_ai_research", [{"title": "Cached research"}])
        app._cache._data["feeds_ai_research"]["ts"] -= app.CACHE_TTL + 1
        with patch.object(app, "_refresh_feeds", side_effect=AssertionError("Unexpected refresh")):
            response = await app.api_news_stream(self.request())
            output = "".join([chunk async for chunk in response.body_iterator])
        self.assertIn("Cached research", output)

    async def test_empty_results_retry_quickly(self):
        app._set_cache("feeds_ai_research", [])
        app._cache._data["feeds_ai_research"]["ts"] -= 31
        self.assertIsNone(app._cached_feed_result("ai_research"))

    async def test_cancelled_request_does_not_cancel_shared_refresh(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def refresh(category):
            started.set()
            await release.wait()
            return [{"title": "Finished"}]

        with patch.object(app, "_refresh_feeds", refresh):
            request = asyncio.create_task(app._fetch_all_feeds("football"))
            await started.wait()
            shared = app._inflight["feeds_football"]
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            self.assertFalse(shared.cancelled())
            release.set()
            self.assertEqual((await shared)[0]["title"], "Finished")

    async def test_fetch_concurrency_is_bounded(self):
        active = 0
        peak = 0
        six_started = asyncio.Event()
        release = asyncio.Event()

        async def fetch(name, url):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            if active == 6:
                six_started.set()
            await release.wait()
            active -= 1
            return []

        with patch.object(app, "_fetch_feed", fetch):
            tasks = [asyncio.create_task(app._fetch_feed_throttled(str(index), "https://example.com"))
                     for index in range(24)]
            await asyncio.wait_for(six_started.wait(), 1)
            self.assertEqual(peak, 6)
            release.set()
            await asyncio.gather(*tasks)
        self.assertEqual(peak, 6)

    async def test_partial_results_and_stream_disconnect(self):
        release = asyncio.Event()

        async def fetch(name, url):
            if name == "Slow":
                await release.wait()
            return [{"title": name, "link": url, "source": name}]

        feeds = [("Fast", "https://example.com/fast"), ("Slow", "https://example.com/slow")]
        with patch.dict(app.RSS_FEEDS, {"football": feeds}), patch.object(app, "_fetch_feed", fetch):
            response = await app.api_news_stream(self.request("football"))
            first = await asyncio.wait_for(anext(response.body_iterator), 1)
            self.assertIn("Fast", first)
            shared = app._inflight["feeds_football"]
            await response.body_iterator.aclose()
            self.assertFalse(shared.done())
            self.assertFalse(app._feed_subscribers)
            release.set()
            self.assertEqual(len(await shared), 2)

    async def test_huggingface_fetch_is_shared_and_cached(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            items = [{"title": "Shared paper"}]
            app._set_cache("hf_daily_papers", items)
            return items

        with patch.object(app, "_load_hf_daily_papers", load):
            tasks = [asyncio.create_task(app._fetch_hf_daily_papers()) for _ in range(8)]
            await started.wait()
            release.set()
            await asyncio.gather(*tasks)
            await app._fetch_hf_daily_papers()
        self.assertEqual(calls, 1)


class FeedHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app._feed_items_cache.clear()
        app._feed_http_cache.clear()
        app._cb = app.CircuitBreaker()

    async def test_conditional_headers_require_cached_items(self):
        requests = []
        feed = b"<rss><channel><item><title>Research</title><link>https://example.com/post</link></item></channel></rss>"

        def handle(request):
            requests.append(request)
            if request.headers.get("if-none-match"):
                return httpx.Response(304)
            return httpx.Response(200, content=gzip.compress(feed), headers={"etag": "version1", "content-encoding": "gzip"})

        url = "https://example.com/feed"
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with patch.object(app, "_http_client", client):
                first = await app._fetch_feed("Test", url)
                second = await app._fetch_feed("Test", url)
                app._feed_items_cache.clear()
                third = await app._fetch_feed("Test", url)
        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertEqual(requests[1].headers.get("if-none-match"), "version1")
        self.assertNotIn("if-none-match", requests[2].headers)

    async def test_oversized_and_invalid_feeds_keep_stale_items(self):
        url = "https://example.com/feed"
        stale = [{"title": "Last good paper"}]
        app._feed_items_cache[url] = stale
        app._feed_http_cache[url] = {"etag": "good"}
        for body in (b"x" * 1024, b"invalid XML"):
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=body, headers={"etag": "bad"})
            )) as client:
                with patch.object(app, "_http_client", client), patch.object(app, "_FEED_MAX_BYTES", 128):
                    result = await app._fetch_feed("Test", url)
            self.assertEqual(result, stale)
            self.assertEqual(app._feed_http_cache[url]["etag"], "good")


class ResponseCacheTests(unittest.TestCase):
    def test_only_advertises_supported_content_encodings(self):
        self.assertNotIn("br", app.HEADERS["Accept-Encoding"].split(", "))

    def test_compressed_cache_retains_identity(self):
        app._gz_cache.clear()
        data = [{"title": "Research"}]
        request = Request({"type": "http", "headers": [(b"accept-encoding", b"gzip")]})
        response = app._json_gz_response(data, request)
        self.assertEqual(json.loads(gzip.decompress(response.body)), data)
        self.assertIs(app._gz_cache[id(data)][0], data)


if __name__ == "__main__":
    unittest.main()