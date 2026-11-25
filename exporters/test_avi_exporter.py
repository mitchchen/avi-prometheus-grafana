#!/usr/bin/env python3
"""Unit tests for the strictly read-only Avi Prometheus exporter."""

from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import threading
import unittest

import avi_exporter


class FakeAviClient:
    def __init__(self, fail: bool = False) -> None:
        self.tenant = "admin"
        self.fail = fail
        self.calls: list[tuple[str, str | None]] = []

    def fetch_metrics(self, entity: str, tenant: str | None = None) -> str:
        self.calls.append((entity, tenant))
        if self.fail:
            raise RuntimeError("controller unreachable")
        return f'# ok {entity}\navi_test_metric{{type="{entity}",tenant="{tenant}"}} 1.0\n'


class AviExporterTest(unittest.TestCase):
    def _start_server(self, client: FakeAviClient, cache_ttl: float = 10.0):
        server = ThreadingHTTPServer(("127.0.0.1", 0), avi_exporter.make_handler(client, cache_ttl=cache_ttl))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server.server_address[1]

    def _req(self, port: int, method: str, path: str) -> tuple[int, str]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            return resp.status, resp.read().decode("utf-8")
        finally:
            conn.close()

    def test_unwrap_prometheus_text(self) -> None:
        raw = b'"# Successfully gathered 1 metrics\\navi_controller_stats_avg_cpu_usage{type=\\"controller\\"} 1.5\\n"'
        unwrapped = avi_exporter.unwrap_prometheus_text(raw)
        self.assertEqual(
            unwrapped,
            '# Successfully gathered 1 metrics\navi_controller_stats_avg_cpu_usage{type="controller"} 1.5\n',
        )

    def test_format_se_interface_metrics_multi_nic(self) -> None:
        payload = {
            "results": [
                {
                    "entity_uuid": "se-1",
                    "series": [
                        {"header": {"name": "se_if.avg_rx_pkts", "obj_id": "eth1", "tenant_uuid": "admin"}, "data": [{"value": 100.0}]},
                        {"header": {"name": "se_if.avg_tx_pkts", "obj_id": "eth1", "tenant_uuid": "admin"}, "data": [{"value": 50.0}]},
                        {"header": {"name": "se_if.avg_rx_pkts", "obj_id": "eth2", "tenant_uuid": "admin"}, "data": [{"value": 25.5}]},
                        {"header": {"name": "se_if.avg_tx_pkts", "obj_id": "eth2", "tenant_uuid": "admin"}, "data": [{"value": 14.5}]},
                        {"header": {"name": "se_if.avg_bandwidth", "obj_id": "eth1", "tenant_uuid": "admin"}, "data": [{"value": 40000.0}]},
                    ],
                }
            ]
        }
        text = avi_exporter.format_se_interface_metrics(payload, {"se-1": "avi-se-01"})
        self.assertIn('avi_se_interface_rx_pps{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01", interface="eth1"} 100.000000', text)
        self.assertIn('avi_se_interface_tx_pps{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01", interface="eth1"} 50.000000', text)
        self.assertIn('avi_se_interface_total_pps{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01", interface="eth1"} 150.000000', text)
        self.assertIn('avi_se_interface_total_pps{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01", interface="eth2"} 40.000000', text)
        self.assertIn('avi_se_total_rx_pps{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01"} 125.500000', text)
        self.assertIn('avi_se_total_tx_pps{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01"} 64.500000', text)
        self.assertIn('avi_se_total_pps{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01"} 190.000000', text)

    def test_allowlisted_entities_and_caching(self) -> None:
        client = FakeAviClient()
        port = self._start_server(client, cache_ttl=60.0)

        status, body = self._req(port, "GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, "ok\n")

        for entity in ("controller", "serviceengine", "serviceengine_interfaces", "inventory", "virtualservice", "pool"):
            status, body = self._req(port, "GET", f"/metrics/{entity}?tenant=admin")
            self.assertEqual(status, 200)
            self.assertIn(f'type="{entity}"', body)

        status, _ = self._req(port, "GET", "/metrics/controller?tenant=admin")
        self.assertEqual(status, 200)
        self.assertEqual(len(client.calls), 6)

    def test_format_inventory_metrics(self) -> None:
        text = avi_exporter.format_inventory_metrics(
            cluster_runtime={"node_states": [{"name": "198.51.100.10", "state": "CLUSTER_ACTIVE", "role": "CLUSTER_LEADER"}]},
            cluster_version={"Version": "32.1.4"},
            license_ledger={"tier_usages": [{"tier": "ENTERPRISE", "usage": {"available": 8.0, "consumed": 6.0}}]},
            vs_inventory={
                "results": [
                    {
                        "config": {"uuid": "vs-1", "name": "vs-app-443"},
                        "runtime": {
                            "oper_status": {"state": "OPER_UP"},
                            "percent_ses_up": 100,
                            "vip_summary": [{"service_engine": [{"uuid": "se-1", "primary": True, "active_on_se": True}]}],
                        },
                    }
                ]
            },
            se_inventory={
                "results": [
                    {
                        "config": {"uuid": "se-1", "name": "avi-se-01", "se_group_ref": "https://c/api/serviceenginegroup/seg-1"},
                        "runtime": {"oper_status": {"state": "OPER_UP"}, "hb_status": {"num_hb_misses": 0}},
                    }
                ]
            },
            se_groups={"results": [{"uuid": "seg-1", "max_vs_per_se": 10}]},
            pool_inventory={
                "results": [
                    {
                        "config": {"uuid": "pool-1", "name": "pool-app-443"},
                        "runtime": {"oper_status": {"state": "OPER_UP"}, "num_servers": 2, "num_servers_enabled": 2, "num_servers_up": 2},
                    }
                ]
            },
            alerts_payload={"results": [{"level": "ALERT_MEDIUM"}]},
        )
        self.assertIn('avi_controller_version_info{type="controller", version="32.1.4"} 1', text)
        self.assertIn('avi_license_cores_used_percent{type="controller", tier="ENTERPRISE"} 75.0000', text)
        self.assertIn('avi_vs_oper_status{uuid="vs-1", type="virtualservice", tenant="admin", name="vs-app-443", state="OPER_UP"} 1', text)
        self.assertIn('avi_vs_hosted_on_se{uuid="vs-1", type="virtualservice", tenant="admin", name="vs-app-443", se_name="avi-se-01", primary="true"} 1', text)
        self.assertIn('avi_se_vs_count{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01"} 1', text)
        self.assertIn('avi_se_vs_capacity_used_percent{uuid="se-1", type="serviceengine", tenant="admin", name="avi-se-01"} 10.00', text)
        self.assertIn('avi_pool_servers_up{uuid="pool-1", type="pool", tenant="admin", name="pool-app-443"} 2', text)
        self.assertIn('avi_controller_alerts_count{type="controller", level="ALERT_MEDIUM"} 1', text)

    def test_blocks_writes_and_arbitrary_paths(self) -> None:
        client = FakeAviClient()
        port = self._start_server(client)

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            status, _ = self._req(port, method, "/metrics/controller")
            self.assertEqual(status, 405, f"expected 405 for {method}")

        for bad_path in ("/", "/api/pool", "/api/user", "/metrics/user", "/metrics/controller/extra"):
            status, _ = self._req(port, "GET", bad_path)
            self.assertEqual(status, 404, f"expected 404 for {bad_path}")
        self.assertEqual(client.calls, [])

    def test_upstream_failure_returns_502_without_crashing(self) -> None:
        client = FakeAviClient(fail=True)
        port = self._start_server(client)
        status, body = self._req(port, "GET", "/metrics/controller")
        self.assertEqual(status, 502)
        self.assertIn("upstream error", body)


if __name__ == "__main__":
    unittest.main()
