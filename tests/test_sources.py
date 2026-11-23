from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from intel.news import subject_from
from intel.sources import configured_sources, feeds, get_feed


class ExpandedSourcesTests(TestCase):
    def test_topics_select_dedicated_subscriptions(self):
        self.assertGreaterEqual(len(subject_from("帮我查 F1 新闻")[2]), 5)
        self.assertEqual(subject_from("查 NBA 新闻")[2], ("nba-espn",))
        self.assertEqual(subject_from("Show me the latest news about the Federal Reserve")[2], ("federal-reserve",))
        self.assertEqual(subject_from("查某上市公司的新闻")[2], ())

    def test_legacy_queries_keep_google_and_new_queries_can_select_both(self):
        catalog = feeds()
        legacy = configured_sources(catalog, [], "OpenAI", 24)
        current = configured_sources(catalog, [], "OpenAI", 24, ["google", "bing"])
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy, {key: value for key, value in current.items() if value["news_provider"] == "google"})
        self.assertEqual(set(config["news_provider"] for config in current.values()), {"google", "bing"})

    def test_bing_extracts_publisher_and_unwraps_article_links(self):
        article = "https://example.test/report?id=123&view=full"
        link = "http://www.bing.com/news/apiclick.aspx?" + urlencode({"url": article, "ref": "FexRss"})
        xml = f"""<rss xmlns:b="urn:bing"><channel><item><title>Example headline</title>
            <link>{escape(link)}</link><b:Source>Example Publisher</b:Source>
            <pubDate>Mon, 23 Nov 2026 05:00:00 GMT</pubDate></item></channel></rss>""".encode()
        with patch("intel.sources.build_opener") as opener:
            opener.return_value.open.return_value = BytesIO(xml)
            item, = get_feed({"name": "Bing News", "news_provider": "bing",
                              "url": "https://www.bing.com/news/search?q=example&format=rss"})
        self.assertEqual(item["url"], article)
        self.assertEqual(item["source"], "Example Publisher")
        self.assertEqual(item["news_provider"], "bing")
        self.assertFalse(item["via_news_search"])
