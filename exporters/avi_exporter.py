#!/usr/bin/env python3
"""Read-only Prometheus metrics exporter for VMware Avi Load Balancer (NSX ALB).

Exposes ONLY strictly allowlisted GET endpoints for Prometheus scraping:
  - /metrics/controller
  - /metrics/serviceengine
  - /metrics/serviceengine_interfaces  (per-NIC RX/TX/combined PPS & bytes + SE multi-NIC totals)
  - /metrics/inventory                 (cluster, version, licensing, VS/SE/pool runtime, heartbeats, alerts)
  - /metrics/virtualservice
  - /metrics/pool
  - /healthz

Authenticates to the Avi Controller using a TLS-verified HTTPS session cookie
(/login) and forwards only read-only GET metrics queries. Write methods and
arbitrary API paths are never proxied.

Zero third-party dependencies (Python 3.10+ standard library only).
"""

from __future__ import annotations

import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import ssl
import sys
import threading
import time
import urllib.parse

PORT = int(os.environ.get("AVI_EXPORTER_PORT", "9103"))
AVI_CONTROLLER = os.environ.get("AVI_CONTROLLER", "").strip()
AVI_API_VERSION = os.environ.get("AVI_API_VERSION", "32.1.4").strip()
AVI_TENANT = os.environ.get("AVI_TENANT", "admin").strip()
# Leave AVI_CA_FILE empty to use the system CA trust store, or point to a PEM
# bundle containing your enterprise/internal root CA certificate.
AVI_CA_FILE = os.environ.get("AVI_CA_FILE", "").strip()
AVI_TIMEOUT = float(os.environ.get("AVI_TIMEOUT", "40"))
CACHE_TTL = float(os.environ.get("AVI_CACHE_TTL", "20"))

PROM_ENTITIES = frozenset({"controller", "serviceengine", "virtualservice", "pool"})
ALLOWED_ENTITIES = PROM_ENTITIES | frozenset({"serviceengine_interfaces", "inventory"})

SE_IF_METRICS = (
    "se_if.avg_rx_pkts,"
    "se_if.avg_tx_pkts,"
    "se_if.avg_rx_bytes,"
    "se_if.avg_tx_bytes,"
    "se_if.avg_bandwidth"
)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def unwrap_prometheus_text(raw: bytes) -> str:
    """Normalize Avi prometheus-metrics payload into valid Prometheus exposition text."""
    text = raw.decode("utf-8", errors="replace").strip()
    if text.startswith('"') and text.endswith('"'):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                text = decoded
        except ValueError:
            pass
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def build_upstream_path(entity: str, tenant: str) -> str:
    if entity not in PROM_ENTITIES:
        raise ValueError(f"unsupported Avi prometheus-metrics entity: {entity}")
    if entity == "controller":
        return "/api/analytics/prometheus-metrics/controller"
    qs = urllib.parse.urlencode({"tenant": tenant})
    return f"/api/analytics/prometheus-metrics/{entity}?{qs}"


def format_se_interface_metrics(
    analytics_payload: dict,
    se_names: dict[str, str],
    default_tenant: str = "admin",
) -> str:
    """Convert Avi /api/analytics/metrics/serviceengine?obj_id=* JSON into Prometheus text.

    Emits per-interface RX/TX/combined PPS, bytes/sec, bandwidth, plus SE-wide
    combined totals summed across all interfaces (supports single-NIC and multi-NIC SEs).
    """
    per_if: dict[tuple[str, str, str], dict[str, float]] = {}

    for result in analytics_payload.get("results") or []:
        se_uuid = str(result.get("entity_uuid") or "").strip()
        if not se_uuid:
            continue
        for series in result.get("series") or []:
            header = series.get("header") or {}
            metric_name = str(header.get("name") or "").strip()
            iface = str(header.get("obj_id") or "").strip()
            tenant = str(header.get("tenant_uuid") or default_tenant).strip() or default_tenant
            points = series.get("data") or []
            if not metric_name or not iface or not points:
                continue
            val = points[-1].get("value")
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            per_if.setdefault((se_uuid, tenant, iface), {})[metric_name] = fval

    se_totals: dict[tuple[str, str], dict[str, float]] = {}
    for (se_uuid, tenant, _iface), metrics in per_if.items():
        agg = se_totals.setdefault((se_uuid, tenant), {"rx_pps": 0.0, "tx_pps": 0.0, "total_pps": 0.0})
        rx = metrics.get("se_if.avg_rx_pkts", 0.0)
        tx = metrics.get("se_if.avg_tx_pkts", 0.0)
        agg["rx_pps"] += rx
        agg["tx_pps"] += tx
        agg["total_pps"] += rx + tx

    lines: list[str] = [
        "# HELP avi_se_interface_rx_pps Avi Service Engine per-interface received packets per second",
        "# TYPE avi_se_interface_rx_pps gauge",
    ]
    sorted_keys = sorted(per_if.keys())
    for key in sorted_keys:
        se_uuid, tenant, iface = key
        name = se_names.get(se_uuid, se_uuid)
        lbl = (
            f'uuid="{_escape_label(se_uuid)}", type="serviceengine", '
            f'tenant="{_escape_label(tenant)}", name="{_escape_label(name)}", '
            f'interface="{_escape_label(iface)}"'
        )
        rx = per_if[key].get("se_if.avg_rx_pkts")
        if rx is not None:
            lines.append(f"avi_se_interface_rx_pps{{{lbl}}} {rx:.6f}")

    lines.extend([
        "# HELP avi_se_interface_tx_pps Avi Service Engine per-interface transmitted packets per second",
        "# TYPE avi_se_interface_tx_pps gauge",
    ])
    for key in sorted_keys:
        se_uuid, tenant, iface = key
        name = se_names.get(se_uuid, se_uuid)
        lbl = (
            f'uuid="{_escape_label(se_uuid)}", type="serviceengine", '
            f'tenant="{_escape_label(tenant)}", name="{_escape_label(name)}", '
            f'interface="{_escape_label(iface)}"'
        )
        tx = per_if[key].get("se_if.avg_tx_pkts")
        if tx is not None:
            lines.append(f"avi_se_interface_tx_pps{{{lbl}}} {tx:.6f}")

    lines.extend([
        "# HELP avi_se_interface_total_pps Avi Service Engine per-interface combined (RX + TX) packets per second",
        "# TYPE avi_se_interface_total_pps gauge",
    ])
    for key in sorted_keys:
        se_uuid, tenant, iface = key
        name = se_names.get(se_uuid, se_uuid)
        lbl = (
            f'uuid="{_escape_label(se_uuid)}", type="serviceengine", '
            f'tenant="{_escape_label(tenant)}", name="{_escape_label(name)}", '
            f'interface="{_escape_label(iface)}"'
        )
        m = per_if[key]
        if "se_if.avg_rx_pkts" in m or "se_if.avg_tx_pkts" in m:
            total = m.get("se_if.avg_rx_pkts", 0.0) + m.get("se_if.avg_tx_pkts", 0.0)
            lines.append(f"avi_se_interface_total_pps{{{lbl}}} {total:.6f}")

    lines.extend([
        "# HELP avi_se_interface_rx_bytes_per_sec Avi Service Engine per-interface received bytes per second",
        "# TYPE avi_se_interface_rx_bytes_per_sec gauge",
    ])
    for key in sorted_keys:
        se_uuid, tenant, iface = key
        name = se_names.get(se_uuid, se_uuid)
        lbl = (
            f'uuid="{_escape_label(se_uuid)}", type="serviceengine", '
            f'tenant="{_escape_label(tenant)}", name="{_escape_label(name)}", '
            f'interface="{_escape_label(iface)}"'
        )
        v = per_if[key].get("se_if.avg_rx_bytes")
        if v is not None:
            lines.append(f"avi_se_interface_rx_bytes_per_sec{{{lbl}}} {v:.6f}")

    lines.extend([
        "# HELP avi_se_interface_tx_bytes_per_sec Avi Service Engine per-interface transmitted bytes per second",
        "# TYPE avi_se_interface_tx_bytes_per_sec gauge",
    ])
    for key in sorted_keys:
        se_uuid, tenant, iface = key
        name = se_names.get(se_uuid, se_uuid)
        lbl = (
            f'uuid="{_escape_label(se_uuid)}", type="serviceengine", '
            f'tenant="{_escape_label(tenant)}", name="{_escape_label(name)}", '
            f'interface="{_escape_label(iface)}"'
        )
        v = per_if[key].get("se_if.avg_tx_bytes")
        if v is not None:
            lines.append(f"avi_se_interface_tx_bytes_per_sec{{{lbl}}} {v:.6f}")

    lines.extend([
        "# HELP avi_se_interface_bandwidth_bps Avi Service Engine per-interface bandwidth in bits per second",
        "# TYPE avi_se_interface_bandwidth_bps gauge",
    ])
    for key in sorted_keys:
        se_uuid, tenant, iface = key
        name = se_names.get(se_uuid, se_uuid)
        lbl = (
            f'uuid="{_escape_label(se_uuid)}", type="serviceengine", '
            f'tenant="{_escape_label(tenant)}", name="{_escape_label(name)}", '
            f'interface="{_escape_label(iface)}"'
        )
        v = per_if[key].get("se_if.avg_bandwidth")
        if v is not None:
            lines.append(f"avi_se_interface_bandwidth_bps{{{lbl}}} {v:.6f}")

    lines.extend([
        "# HELP avi_se_total_rx_pps Avi Service Engine combined RX packets per second across all interfaces",
        "# TYPE avi_se_total_rx_pps gauge",
    ])
    for (se_uuid, tenant), agg in sorted(se_totals.items()):
        name = se_names.get(se_uuid, se_uuid)
        lbl = f'uuid="{_escape_label(se_uuid)}", type="serviceengine", tenant="{_escape_label(tenant)}", name="{_escape_label(name)}"'
        lines.append(f"avi_se_total_rx_pps{{{lbl}}} {agg['rx_pps']:.6f}")

    lines.extend([
        "# HELP avi_se_total_tx_pps Avi Service Engine combined TX packets per second across all interfaces",
        "# TYPE avi_se_total_tx_pps gauge",
    ])
    for (se_uuid, tenant), agg in sorted(se_totals.items()):
        name = se_names.get(se_uuid, se_uuid)
        lbl = f'uuid="{_escape_label(se_uuid)}", type="serviceengine", tenant="{_escape_label(tenant)}", name="{_escape_label(name)}"'
        lines.append(f"avi_se_total_tx_pps{{{lbl}}} {agg['tx_pps']:.6f}")

    lines.extend([
        "# HELP avi_se_total_pps Avi Service Engine combined total (RX + TX) packets per second across all interfaces",
        "# TYPE avi_se_total_pps gauge",
    ])
    for (se_uuid, tenant), agg in sorted(se_totals.items()):
        name = se_names.get(se_uuid, se_uuid)
        lbl = f'uuid="{_escape_label(se_uuid)}", type="serviceengine", tenant="{_escape_label(tenant)}", name="{_escape_label(name)}"'
        lines.append(f"avi_se_total_pps{{{lbl}}} {agg['total_pps']:.6f}")

    return "\n".join(lines) + "\n"


def format_inventory_metrics(
    *,
    cluster_runtime: dict,
    cluster_version: dict,
    license_ledger: dict,
    vs_inventory: dict,
    se_inventory: dict,
    se_groups: dict,
    pool_inventory: dict,
    alerts_payload: dict,
    default_tenant: str = "admin",
) -> str:
    """Emit Avi cluster, licensing, VS, SE, pool, and alert inventory gauges."""
    lines: list[str] = []

    ver = str(cluster_version.get("Version") or "unknown")
    lines.extend([
        "# HELP avi_controller_version_info Avi controller running version (always 1)",
        "# TYPE avi_controller_version_info gauge",
        f'avi_controller_version_info{{type="controller", version="{_escape_label(ver)}"}} 1',
    ])

    nodes = cluster_runtime.get("node_states") or []
    active_members = sum(1 for n in nodes if n.get("state") == "CLUSTER_ACTIVE")
    lines.extend([
        "# HELP avi_cluster_active_members Number of active Avi controller cluster nodes",
        "# TYPE avi_cluster_active_members gauge",
        f'avi_cluster_active_members{{type="controller"}} {active_members}',
        "# HELP avi_cluster_node_is_leader Whether an Avi controller node is cluster leader (1=leader, 0=follower)",
        "# TYPE avi_cluster_node_is_leader gauge",
    ])
    for n in nodes:
        nname = str(n.get("name") or "unknown")
        role = str(n.get("role") or "")
        state = str(n.get("state") or "")
        is_leader = 1 if role == "CLUSTER_LEADER" else 0
        lines.append(
            f'avi_cluster_node_is_leader{{type="controller", node="{_escape_label(nname)}", state="{_escape_label(state)}"}} {is_leader}'
        )

    lines.extend([
        "# HELP avi_license_cores_available Total licensed Avi service cores",
        "# TYPE avi_license_cores_available gauge",
        "# HELP avi_license_cores_consumed Consumed Avi service cores",
        "# TYPE avi_license_cores_consumed gauge",
        "# HELP avi_license_cores_used_percent Percentage of licensed Avi service cores consumed",
        "# TYPE avi_license_cores_used_percent gauge",
    ])
    for tu in license_ledger.get("tier_usages") or []:
        tier = str(tu.get("tier") or "unknown")
        usage = tu.get("usage") or {}
        avail = float(usage.get("available") or 0.0)
        consumed = float(usage.get("consumed") or 0.0)
        pct = (consumed / avail * 100.0) if avail > 0 else 0.0
        tlbl = f'type="controller", tier="{_escape_label(tier)}"'
        lines.append(f"avi_license_cores_available{{{tlbl}}} {avail:.4f}")
        lines.append(f"avi_license_cores_consumed{{{tlbl}}} {consumed:.4f}")
        lines.append(f"avi_license_cores_used_percent{{{tlbl}}} {pct:.4f}")

    seg_max_vs: dict[str, int] = {}
    for seg in se_groups.get("results") or []:
        if seg.get("uuid"):
            seg_max_vs[str(seg["uuid"])] = int(seg.get("max_vs_per_se") or 0)

    se_uuid_to_name: dict[str, str] = {}
    for item in se_inventory.get("results") or []:
        cfg = item.get("config") or {}
        if cfg.get("uuid"):
            se_uuid_to_name[str(cfg["uuid"])] = str(cfg.get("name") or cfg["uuid"])

    vs_results = vs_inventory.get("results") or []
    vs_total = len(vs_results)
    vs_up = 0
    vs_count_by_se: dict[str, int] = {}
    vs_oper_lines: list[str] = []
    vs_pct_se_lines: list[str] = []
    vs_hosted_lines: list[str] = []

    for item in vs_results:
        cfg = item.get("config") or {}
        rt = item.get("runtime") or {}
        vs_uuid = str(cfg.get("uuid") or "")
        vs_name = str(cfg.get("name") or vs_uuid)
        tenant = default_tenant
        state = str((rt.get("oper_status") or {}).get("state") or "UNKNOWN")
        is_up = 1 if state == "OPER_UP" else 0
        vs_up += is_up
        pct_ses = float(rt.get("percent_ses_up") or 0.0)
        vlbl = f'uuid="{_escape_label(vs_uuid)}", type="virtualservice", tenant="{_escape_label(tenant)}", name="{_escape_label(vs_name)}"'
        vs_oper_lines.append(f'avi_vs_oper_status{{{vlbl}, state="{_escape_label(state)}"}} {is_up}')
        vs_pct_se_lines.append(f"avi_vs_percent_ses_up{{{vlbl}}} {pct_ses:.2f}")

        seen_ses: set[str] = set()
        for vip in rt.get("vip_summary") or []:
            for se_entry in vip.get("service_engine") or []:
                se_uuid = str(se_entry.get("uuid") or "")
                if not se_uuid or se_uuid in seen_ses:
                    continue
                seen_ses.add(se_uuid)
                vs_count_by_se[se_uuid] = vs_count_by_se.get(se_uuid, 0) + 1
                se_name = se_uuid_to_name.get(se_uuid) or str((se_entry.get("mgmt_ip") or {}).get("addr") or se_uuid)
                primary = "true" if se_entry.get("primary") else "false"
                active = 1 if se_entry.get("active_on_se") else 0
                vs_hosted_lines.append(
                    f'avi_vs_hosted_on_se{{{vlbl}, se_name="{_escape_label(se_name)}", primary="{primary}"}} {active}'
                )

    vs_up_pct = (vs_up / vs_total * 100.0) if vs_total > 0 else 100.0
    lines.extend([
        "# HELP avi_vs_total_count Total configured Avi Virtual Services",
        "# TYPE avi_vs_total_count gauge",
        f'avi_vs_total_count{{type="controller", tenant="{_escape_label(default_tenant)}"}} {vs_total}',
        "# HELP avi_vs_up_count Number of Avi Virtual Services in OPER_UP state",
        "# TYPE avi_vs_up_count gauge",
        f'avi_vs_up_count{{type="controller", tenant="{_escape_label(default_tenant)}"}} {vs_up}',
        "# HELP avi_vs_up_percent Percentage of Avi Virtual Services in OPER_UP state",
        "# TYPE avi_vs_up_percent gauge",
        f'avi_vs_up_percent{{type="controller", tenant="{_escape_label(default_tenant)}"}} {vs_up_pct:.2f}',
        "# HELP avi_vs_oper_status Virtual Service operational status (1=OPER_UP, 0=other)",
        "# TYPE avi_vs_oper_status gauge",
        *vs_oper_lines,
        "# HELP avi_vs_percent_ses_up Percentage of assigned Service Engines UP for this Virtual Service",
        "# TYPE avi_vs_percent_ses_up gauge",
        *vs_pct_se_lines,
        "# HELP avi_vs_hosted_on_se Virtual Service placement on Service Engines (1=active_on_se)",
        "# TYPE avi_vs_hosted_on_se gauge",
        *vs_hosted_lines,
    ])

    se_oper_lines: list[str] = []
    se_hb_lines: list[str] = []
    se_vscount_lines: list[str] = []
    se_cap_lines: list[str] = []
    se_up_count = 0
    se_results = se_inventory.get("results") or []
    for item in se_results:
        cfg = item.get("config") or {}
        rt = item.get("runtime") or {}
        se_uuid = str(cfg.get("uuid") or "")
        se_name = str(cfg.get("name") or se_uuid)
        state = str((rt.get("oper_status") or {}).get("state") or "UNKNOWN")
        is_up = 1 if state == "OPER_UP" else 0
        se_up_count += is_up
        hb = rt.get("hb_status") or {}
        misses = int(hb.get("num_hb_misses") or 0)
        vs_cnt = vs_count_by_se.get(se_uuid, 0)
        seg_uuid = str(cfg.get("se_group_ref") or "").rstrip("/").split("/")[-1]
        max_vs = seg_max_vs.get(seg_uuid, 0)
        cap_pct = (vs_cnt / max_vs * 100.0) if max_vs > 0 else 0.0
        slbl = f'uuid="{_escape_label(se_uuid)}", type="serviceengine", tenant="{_escape_label(default_tenant)}", name="{_escape_label(se_name)}"'
        se_oper_lines.append(f'avi_se_oper_status{{{slbl}, state="{_escape_label(state)}"}} {is_up}')
        se_hb_lines.append(f"avi_se_missed_heartbeats{{{slbl}}} {misses}")
        se_vscount_lines.append(f"avi_se_vs_count{{{slbl}}} {vs_cnt}")
        se_cap_lines.append(f"avi_se_vs_capacity_used_percent{{{slbl}}} {cap_pct:.2f}")

    lines.extend([
        "# HELP avi_se_total_count Total Avi Service Engines",
        "# TYPE avi_se_total_count gauge",
        f'avi_se_total_count{{type="controller", tenant="{_escape_label(default_tenant)}"}} {len(se_results)}',
        "# HELP avi_se_up_count Number of Avi Service Engines in OPER_UP state",
        "# TYPE avi_se_up_count gauge",
        f'avi_se_up_count{{type="controller", tenant="{_escape_label(default_tenant)}"}} {se_up_count}',
        "# HELP avi_se_oper_status Service Engine operational status (1=OPER_UP, 0=other)",
        "# TYPE avi_se_oper_status gauge",
        *se_oper_lines,
        "# HELP avi_se_missed_heartbeats Service Engine consecutive missed heartbeats",
        "# TYPE avi_se_missed_heartbeats gauge",
        *se_hb_lines,
        "# HELP avi_se_vs_count Number of Virtual Services placed on this Service Engine",
        "# TYPE avi_se_vs_count gauge",
        *se_vscount_lines,
        "# HELP avi_se_vs_capacity_used_percent Percentage of max_vs_per_se capacity used on this Service Engine",
        "# TYPE avi_se_vs_capacity_used_percent gauge",
        *se_cap_lines,
    ])

    pool_oper_lines: list[str] = []
    pool_total_lines: list[str] = []
    pool_en_lines: list[str] = []
    pool_up_lines: list[str] = []
    for item in pool_inventory.get("results") or []:
        cfg = item.get("config") or {}
        rt = item.get("runtime") or {}
        p_uuid = str(cfg.get("uuid") or "")
        p_name = str(cfg.get("name") or p_uuid)
        state = str((rt.get("oper_status") or {}).get("state") or "UNKNOWN")
        is_up = 1 if state == "OPER_UP" else 0
        plbl = f'uuid="{_escape_label(p_uuid)}", type="pool", tenant="{_escape_label(default_tenant)}", name="{_escape_label(p_name)}"'
        pool_oper_lines.append(f'avi_pool_oper_status{{{plbl}, state="{_escape_label(state)}"}} {is_up}')
        pool_total_lines.append(f"avi_pool_servers_total{{{plbl}}} {int(rt.get('num_servers') or 0)}")
        pool_en_lines.append(f"avi_pool_servers_enabled{{{plbl}}} {int(rt.get('num_servers_enabled') or 0)}")
        pool_up_lines.append(f"avi_pool_servers_up{{{plbl}}} {int(rt.get('num_servers_up') or 0)}")

    lines.extend([
        "# HELP avi_pool_oper_status Pool operational status (1=OPER_UP, 0=other)",
        "# TYPE avi_pool_oper_status gauge",
        *pool_oper_lines,
        "# HELP avi_pool_servers_total Total configured servers in pool",
        "# TYPE avi_pool_servers_total gauge",
        *pool_total_lines,
        "# HELP avi_pool_servers_enabled Enabled servers in pool",
        "# TYPE avi_pool_servers_enabled gauge",
        *pool_en_lines,
        "# HELP avi_pool_servers_up Healthy UP servers in pool",
        "# TYPE avi_pool_servers_up gauge",
        *pool_up_lines,
    ])

    alert_counts = {"ALERT_HIGH": 0, "ALERT_MEDIUM": 0, "ALERT_LOW": 0}
    for a in alerts_payload.get("results") or []:
        lvl = str(a.get("level") or "ALERT_LOW")
        alert_counts[lvl] = alert_counts.get(lvl, 0) + 1
    lines.extend([
        "# HELP avi_controller_alerts_count Active Avi controller alerts by severity level",
        "# TYPE avi_controller_alerts_count gauge",
    ])
    for lvl, cnt in sorted(alert_counts.items()):
        lines.append(f'avi_controller_alerts_count{{type="controller", level="{_escape_label(lvl)}"}} {cnt}')

    return "\n".join(lines) + "\n"


class AviMetricsClient:
    """Thread-safe, strictly read-only Avi Controller metrics session client."""

    def __init__(
        self,
        controller: str,
        username: str,
        password: str,
        api_version: str = AVI_API_VERSION,
        tenant: str = AVI_TENANT,
        ca_file: str = AVI_CA_FILE,
        timeout: float = AVI_TIMEOUT,
    ) -> None:
        self.controller = controller
        self.username = username
        self.password = password
        self.api_version = api_version
        self.tenant = tenant
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        self._lock = threading.Lock()
        self._cookies: dict[str, str] = {}

    def _request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPSConnection(self.controller, timeout=self.timeout, context=self.ssl_context)
        req_headers = {
            "Referer": f"https://{self.controller}",
            "X-Avi-Version": self.api_version,
            "X-Avi-Tenant": self.tenant,
        }
        if headers:
            req_headers.update(headers)
        if self._cookies:
            req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        try:
            conn.request(method, path, body=body, headers=req_headers)
            resp = conn.getresponse()
            data = resp.read()
            for line in resp.msg.get_all("Set-Cookie") or []:
                for k, morsel in SimpleCookie(line).items():
                    self._cookies[k] = morsel.value
            return resp.status, data
        finally:
            conn.close()

    def _login(self) -> None:
        self._cookies.clear()
        payload = json.dumps({"username": self.username, "password": self.password}).encode("utf-8")
        status, data = self._request(
            "POST",
            "/login",
            body=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if status != 200 or "sessionid" not in self._cookies:
            raise RuntimeError(f"Avi login failed with HTTP {status}: {data[:200].decode('utf-8', 'replace')}")

    def _get_authed(self, path: str, tenant: str, accept: str) -> bytes:
        if not self._cookies:
            self._login()
        status, data = self._request(
            "GET",
            path,
            headers={"Accept": accept, "X-Avi-Tenant": tenant},
        )
        if status in (401, 403, 419):
            self._login()
            status, data = self._request(
                "GET",
                path,
                headers={"Accept": accept, "X-Avi-Tenant": tenant},
            )
        if status != 200:
            raise RuntimeError(f"Avi GET {path} failed with HTTP {status}")
        return data

    def fetch_metrics(self, entity: str, tenant: str | None = None) -> str:
        eff_tenant = (tenant or self.tenant).strip() or self.tenant
        if entity == "serviceengine_interfaces":
            return self.fetch_se_interface_metrics(tenant=eff_tenant)
        if entity == "inventory":
            return self.fetch_inventory_metrics(tenant=eff_tenant)
        path = build_upstream_path(entity, eff_tenant)
        with self._lock:
            data = self._get_authed(path, eff_tenant, "text/plain, application/json")
        return unwrap_prometheus_text(data)

    def _get_json(self, path: str, tenant: str) -> dict:
        raw = self._get_authed(path, tenant, "application/json")
        return json.loads(raw.decode("utf-8"))

    def fetch_inventory_metrics(self, tenant: str | None = None) -> str:
        eff_tenant = (tenant or self.tenant).strip() or self.tenant
        with self._lock:
            cluster_runtime = self._get_json("/api/cluster/runtime", eff_tenant)
            cluster_version = self._get_json("/api/cluster/version", eff_tenant)
            try:
                license_ledger = self._get_json("/api/licensing/ledger/details", eff_tenant)
            except Exception:
                license_ledger = {}
            vs_inv = self._get_json("/api/virtualservice-inventory?page_size=200", eff_tenant)
            se_inv = self._get_json("/api/serviceengine-inventory?page_size=200", eff_tenant)
            se_groups = self._get_json("/api/serviceenginegroup?fields=max_vs_per_se&page_size=200", eff_tenant)
            pool_inv = self._get_json("/api/pool-inventory?page_size=200", eff_tenant)
            try:
                alerts = self._get_json("/api/alert?page_size=100", eff_tenant)
            except Exception:
                alerts = {}
        return format_inventory_metrics(
            cluster_runtime=cluster_runtime,
            cluster_version=cluster_version,
            license_ledger=license_ledger,
            vs_inventory=vs_inv,
            se_inventory=se_inv,
            se_groups=se_groups,
            pool_inventory=pool_inv,
            alerts_payload=alerts,
            default_tenant=eff_tenant,
        )

    def fetch_se_interface_metrics(self, tenant: str | None = None) -> str:
        eff_tenant = (tenant or self.tenant).strip() or self.tenant
        qs = urllib.parse.urlencode({
            "tenant": eff_tenant,
            "metric_id": SE_IF_METRICS,
            "obj_id": "*",
            "limit": "1",
            "step": "60",
        })
        metrics_path = f"/api/analytics/metrics/serviceengine?{qs}"
        with self._lock:
            se_raw = self._get_authed("/api/serviceengine?page_size=200", eff_tenant, "application/json")
            metrics_raw = self._get_authed(metrics_path, eff_tenant, "application/json")
        se_list = json.loads(se_raw.decode("utf-8"))
        se_names = {
            str(se["uuid"]): str(se.get("name") or se["uuid"])
            for se in (se_list.get("results") or [])
            if se.get("uuid")
        }
        analytics = json.loads(metrics_raw.decode("utf-8"))
        return format_se_interface_metrics(analytics, se_names, default_tenant=eff_tenant)


def make_handler(client: AviMetricsClient, cache_ttl: float = CACHE_TTL):
    cache_lock = threading.Lock()
    cache: dict[tuple[str, str], tuple[float, str]] = {}

    class Handler(BaseHTTPRequestHandler):
        def _send_text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/healthz":
                self._send_text(200, "ok\n")
                return

            if not parsed.path.startswith("/metrics/"):
                self._send_text(404, "not found\n")
                return

            entity = parsed.path[len("/metrics/") :].strip("/")
            if entity not in ALLOWED_ENTITIES:
                self._send_text(404, "unsupported metrics entity\n")
                return

            query = urllib.parse.parse_qs(parsed.query)
            tenant = (query.get("tenant") or [client.tenant])[0].strip() or client.tenant
            cache_key = (entity, tenant)

            now = time.monotonic()
            with cache_lock:
                entry = cache.get(cache_key)
                if entry is not None and (now - entry[0]) <= cache_ttl:
                    self._send_text(200, entry[1], "text/plain; version=0.0.4; charset=utf-8")
                    return

            try:
                body = client.fetch_metrics(entity, tenant=tenant)
            except Exception as exc:  # noqa: BLE001 - exporter must stay alive when controller is down/rebooting
                sys.stderr.write(f"avi-exporter error ({entity}): {type(exc).__name__}: {exc}\n")
                sys.stderr.flush()
                self._send_text(502, f"# avi-exporter upstream error ({entity})\n")
                return

            with cache_lock:
                cache[cache_key] = (time.monotonic(), body)
            self._send_text(200, body, "text/plain; version=0.0.4; charset=utf-8")

        def do_POST(self) -> None:
            self._send_text(405, "method not allowed\n")

        def do_PUT(self) -> None:
            self._send_text(405, "method not allowed\n")

        def do_PATCH(self) -> None:
            self._send_text(405, "method not allowed\n")

        def do_DELETE(self) -> None:
            self._send_text(405, "method not allowed\n")

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def main() -> None:
    username = os.environ.get("AVI_USERNAME", "").strip()
    password = os.environ.get("AVI_PASSWORD", "").strip()
    if not AVI_CONTROLLER or not username or not password:
        sys.stderr.write("AVI_CONTROLLER, AVI_USERNAME, and AVI_PASSWORD must be set\n")
        sys.exit(2)

    client = AviMetricsClient(
        controller=AVI_CONTROLLER,
        username=username,
        password=password,
        api_version=AVI_API_VERSION,
        tenant=AVI_TENANT,
        ca_file=AVI_CA_FILE,
        timeout=AVI_TIMEOUT,
    )
    server = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(client, cache_ttl=CACHE_TTL))
    server.serve_forever()


if __name__ == "__main__":
    main()
