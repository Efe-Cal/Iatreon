import unittest
from unittest.mock import patch

import requests

from context.errors import ExternalServiceError


class ExternalAPIErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_failure_raises_external_service_error(self):
        from context import websearch

        with (
            patch.object(websearch, "make_exa_client", side_effect=requests.Timeout("slow")),
            self.assertRaises(ExternalServiceError),
        ):
            websearch.web_search("headache")

    async def test_web_content_failure_raises_external_service_error(self):
        from context import websearch

        with (
            patch.object(websearch, "make_exa_client", side_effect=requests.Timeout("slow")),
            self.assertRaises(ExternalServiceError),
        ):
            websearch.fetch_web_content("https://example.com")

    async def test_pubmed_search_failure_raises_external_service_error(self):
        from context.sources.pubmed import PubMedClient
        from context.sources import pubmed

        with patch.object(pubmed, "ncbi_get", side_effect=requests.Timeout("slow")):
            with self.assertRaises(ExternalServiceError):
                PubMedClient().search("headache")

    async def test_pubmed_bad_xml_raises_external_service_error(self):
        from context.sources.pubmed import PubMedClient

        with self.assertRaises(ExternalServiceError):
            PubMedClient()._parse_pubmed_xml("<not xml")

    async def test_openalex_search_failure_returns_empty_results(self):
        from context.sources.openalex import OpenAlexClient
        from context.sources import openalex

        with patch.object(openalex.requests, "get", side_effect=requests.Timeout("slow")):
            self.assertEqual(await OpenAlexClient().search_directly("headache"), [])


if __name__ == "__main__":
    unittest.main()
