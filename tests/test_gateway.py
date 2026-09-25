import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag_platform.gateway import ChatGateway, GatewayError, Price, PriceTable, Route, classify_status, routes_from_env
from support import FakeServer, ScriptedReply, completion


MESSAGES = [{"role": "user", "content": "hello"}]
PRICES = PriceTable({"model-a": Price(2.0, 8.0), "model-b": Price(1.0, 4.0)})


def gateway(server: FakeServer, sleeps: list[float] | None = None, **options) -> ChatGateway:
    routes = options.pop("routes", [
        Route("primary", f"{server.url}/primary/v1", "model-a", "TEST_GATEWAY_KEY"),
        Route("fallback", f"{server.url}/fallback/v1", "model-b", "TEST_GATEWAY_KEY"),
    ])
    recorder = sleeps if sleeps is not None else []
    return ChatGateway(routes, PRICES, sleep=recorder.append, environ={"TEST_GATEWAY_KEY": "fake-key"}, **options)


PRIMARY = "/primary/v1/chat/completions"
FALLBACK = "/fallback/v1/chat/completions"


class RoutingTests(unittest.TestCase):
    def test_success_reports_usage_and_cost(self):
        with FakeServer({PRIMARY: [ScriptedReply(body=completion("ok", 1000, 500))]}) as server:
            response = gateway(server).complete(MESSAGES)
        self.assertEqual((response.content, response.route, response.model), ("ok", "primary", "model-a"))
        self.assertEqual(response.usage.total_tokens, 1500)
        self.assertAlmostEqual(response.cost_usd, (1000 * 2.0 + 500 * 8.0) / 1_000_000)
        self.assertEqual(len(response.attempts), 1)

    def test_request_is_openai_compatible_and_carries_bearer_from_env(self):
        with FakeServer({PRIMARY: [ScriptedReply(body=completion("ok"))]}) as server:
            gateway(server).complete(MESSAGES, temperature=0)
            request = server.requests_to(PRIMARY)[0]
        self.assertEqual(request["body"], {"model": "model-a", "messages": MESSAGES, "temperature": 0})
        self.assertEqual(request["headers"]["Authorization"], "Bearer fake-key")

    def test_missing_key_sends_no_authorization_header(self):
        with FakeServer({PRIMARY: [ScriptedReply(body=completion("ok"))]}) as server:
            ChatGateway([Route("primary", f"{server.url}/primary/v1", "model-a", "UNSET_KEY")], environ={}).complete(MESSAGES)
            self.assertNotIn("Authorization", server.requests_to(PRIMARY)[0]["headers"])

    def test_rate_limit_is_retried_with_backoff_then_succeeds(self):
        replies = [ScriptedReply(429, {"error": "slow down"}), ScriptedReply(body=completion("ok"))]
        sleeps: list[float] = []
        with FakeServer({PRIMARY: replies}) as server:
            response = gateway(server, sleeps, backoff_seconds=0.5).complete(MESSAGES)
        self.assertEqual([attempt.error_kind for attempt in response.attempts], ["rate_limited", None])
        self.assertEqual(sleeps, [0.5])

    def test_retry_after_header_overrides_backoff_within_cap(self):
        replies = [ScriptedReply(429, {}, headers={"Retry-After": "30"}), ScriptedReply(body=completion("ok"))]
        sleeps: list[float] = []
        with FakeServer({PRIMARY: replies}) as server:
            gateway(server, sleeps, max_backoff_seconds=2.0).complete(MESSAGES)
        self.assertEqual(sleeps, [2.0])

    def test_server_errors_exhaust_primary_then_fall_back(self):
        sleeps: list[float] = []
        with FakeServer({PRIMARY: [ScriptedReply(503, {})], FALLBACK: [ScriptedReply(body=completion("from fallback", 10, 10))]}) as server:
            response = gateway(server, sleeps, backoff_seconds=0.1).complete(MESSAGES)
            primary_calls = len(server.requests_to(PRIMARY))
        self.assertEqual((response.route, response.model, response.content), ("fallback", "model-b", "from fallback"))
        self.assertEqual(primary_calls, 3)
        self.assertEqual(sleeps, [0.1, 0.2])
        self.assertAlmostEqual(response.cost_usd, (10 * 1.0 + 10 * 4.0) / 1_000_000)

    def test_timeout_is_retried(self):
        replies = [ScriptedReply(body=completion("late"), delay_seconds=1.0), ScriptedReply(body=completion("ok"))]
        with FakeServer({PRIMARY: replies}) as server:
            response = gateway(server, timeout_seconds=0.2).complete(MESSAGES)
        self.assertEqual(response.attempts[0].error_kind, "timeout")
        self.assertEqual(response.content, "ok")

    def test_bad_request_is_not_retried_and_does_not_fall_back(self):
        with FakeServer({PRIMARY: [ScriptedReply(400, {"error": "bad"})], FALLBACK: [ScriptedReply(body=completion("x"))]}) as server:
            with self.assertRaises(GatewayError) as caught:
                gateway(server).complete(MESSAGES)
            self.assertEqual(len(server.requests_to(PRIMARY)), 1)
            self.assertEqual(server.requests_to(FALLBACK), [])
        self.assertEqual((caught.exception.kind, caught.exception.status, caught.exception.retryable), ("bad_request", 400, False))

    def test_auth_failure_skips_to_fallback_without_retry(self):
        with FakeServer({PRIMARY: [ScriptedReply(401, {})], FALLBACK: [ScriptedReply(body=completion("ok"))]}) as server:
            response = gateway(server).complete(MESSAGES)
            self.assertEqual(len(server.requests_to(PRIMARY)), 1)
        self.assertEqual([attempt.error_kind for attempt in response.attempts], ["auth", None])

    def test_all_routes_failing_raises_with_every_attempt(self):
        with FakeServer({PRIMARY: [ScriptedReply(500, {})], FALLBACK: [ScriptedReply(502, {})]}) as server:
            with self.assertRaises(GatewayError) as caught:
                gateway(server, max_attempts_per_route=2).complete(MESSAGES)
        self.assertEqual(caught.exception.kind, "routes_exhausted")
        self.assertEqual([(attempt.route, attempt.status) for attempt in caught.exception.attempts], [("primary", 500), ("primary", 500), ("fallback", 502), ("fallback", 502)])

    def test_unreachable_route_is_a_network_error_and_falls_back(self):
        with FakeServer({FALLBACK: [ScriptedReply(body=completion("ok"))]}) as server:
            routes = [Route("dead", "http://127.0.0.1:9/v1", "model-a"), Route("fallback", f"{server.url}/fallback/v1", "model-b")]
            response = gateway(server, routes=routes, max_attempts_per_route=1).complete(MESSAGES)
        self.assertEqual(response.attempts[0].error_kind, "network")

    def test_malformed_payload_is_invalid_response(self):
        replies = {PRIMARY: [ScriptedReply(body={"choices": []})], FALLBACK: [ScriptedReply(body=completion("x"))]}
        with FakeServer(replies) as server:
            with self.assertRaises(GatewayError) as caught:
                gateway(server).complete(MESSAGES)
        self.assertEqual(caught.exception.kind, "invalid_response")

    def test_non_json_body_is_invalid_response(self):
        with FakeServer({PRIMARY: [ScriptedReply(raw=b"<html>")]}) as server:
            with self.assertRaises(GatewayError) as caught:
                gateway(server).complete(MESSAGES)
        self.assertEqual(caught.exception.kind, "invalid_response")

    def test_attempt_records_never_contain_the_key(self):
        with FakeServer({PRIMARY: [ScriptedReply(429, {}), ScriptedReply(body=completion("ok"))]}) as server:
            response = gateway(server).complete(MESSAGES)
        self.assertNotIn("fake-key", json.dumps(response.attribution()))


class ClassificationAndPricingTests(unittest.TestCase):
    def test_status_classification(self):
        expected = {429: "rate_limited", 408: "timeout", 500: "server_error", 503: "server_error", 401: "auth", 403: "auth", 404: "not_found", 400: "bad_request", 422: "bad_request"}
        self.assertEqual({status: classify_status(status) for status in expected}, expected)

    def test_unpriced_model_has_null_cost(self):
        self.assertIsNone(PRICES.cost("unknown-model", 10, 10))

    def test_price_table_loads_from_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps({"m": {"input_per_million": 3, "output_per_million": 6}}), encoding="utf-8")
            self.assertAlmostEqual(PriceTable.from_json(path).cost("m", 1_000_000, 500_000), 6.0)

    def test_routes_from_env(self):
        self.assertEqual(routes_from_env({}), [])
        routes = routes_from_env({"RAG_GATEWAY_BASE_URL": "http://gw/v1", "RAG_GATEWAY_MODEL": "a", "RAG_GATEWAY_FALLBACK_MODEL": "b"})
        self.assertEqual([(route.name, route.model, route.base_url) for route in routes], [("primary", "a", "http://gw/v1"), ("fallback", "b", "http://gw/v1")])

    def test_empty_route_list_is_rejected(self):
        with self.assertRaises(ValueError):
            ChatGateway([])


if __name__ == "__main__":
    unittest.main()
