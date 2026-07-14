import unittest
from unittest.mock import patch

import requests


class ExternalAPIErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_failure_returns_empty_results(self):
        from context import websearch

        self.assertEqual(websearch.web_search("headache"), [])

    async def test_web_content_failure_returns_fallback_text(self):
        from context import websearch

        self.assertEqual(websearch.fetch_web_content("https://example.com"), "Failed to fetch content.")

    async def test_pubmed_search_failure_returns_empty_results(self):
        from context.sources.pubmed import PubMedClient
        from context.sources import pubmed

        with patch.object(pubmed, "ncbi_get", side_effect=requests.Timeout("slow")):
            self.assertEqual(PubMedClient().search("headache"), [])

    async def test_pubmed_bad_xml_returns_empty_results(self):
        from context.sources.pubmed import PubMedClient

        self.assertEqual(PubMedClient()._parse_pubmed_xml("<not xml"), [])

    async def test_openalex_search_failure_returns_empty_results(self):
        from context.sources.openalex import OpenAlexClient
        from context.sources import openalex

        with patch.object(openalex.requests, "get", side_effect=requests.Timeout("slow")):
            self.assertEqual(await OpenAlexClient().search_directly("headache"), [])


if __name__ == "__main__":
    unittest.main()
