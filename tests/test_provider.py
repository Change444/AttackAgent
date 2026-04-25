from __future__ import annotations

import unittest

from attack_agent.provider import LocalHTTPCompetitionProvider, TransportResponse


class ProviderTests(unittest.TestCase):
    def test_http_provider_maps_start_response(self) -> None:
        def transport(method, path, payload):
            self.assertEqual("POST", method)
            self.assertEqual("/start_challenge", path)
            return TransportResponse(
                status=200,
                payload={"instance": {"instance_id": "i1", "challenge_id": "c1", "target": "http://demo", "status": "running", "metadata": {}}},
            )

        provider = LocalHTTPCompetitionProvider("http://localhost", transport=transport)
        instance = provider.start_challenge("c1")
        self.assertEqual("i1", instance.instance_id)

    def test_http_provider_timeout_is_mapped(self) -> None:
        def transport(method, path, payload):
            raise RuntimeError("provider_timeout")

        provider = LocalHTTPCompetitionProvider("http://localhost", transport=transport)
        with self.assertRaisesRegex(RuntimeError, "provider_timeout"):
            provider.list_challenges()


if __name__ == "__main__":
    unittest.main()
