#!/usr/bin/env python3
"""Generate cohesive, Grafana 13 (schemaVersion 41) Avi Load Balancer dashboards.

Design principles (native Grafana 11-13 schemaVersion 41):
  - Consistent 24-column grid, executive KPI banner at top, collapsible section rows.
  - Smooth opacity-gradient timeseries with Last / Mean / Max table legends.
  - Gauges and bar gauges for percentage/capacity metrics, solid status badges for UP/DOWN.
  - Top quick-nav bar across all Avi dashboards + click-to-drill-down dataLinks.
  - Unused L7/HTTP/SSL/WAF sections cleanly tucked into collapsed rows so L4/DNS labs
    never stare at empty "No data" walls.
"""

from __future__ import annotations

import json
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboards")
DS = {"type": "prometheus", "uid": "${datasource}"}

NAV_LINKS = [
    {
        "title": "Avi Dashboards",
        "type": "dashboards",
        "tags": ["avi"],
        "asDropdown": True,
        "includeVars": True,
        "keepTime": True,
        "targetBlank": False,
        "icon": "dashboard",
    },
]

UP_DOWN_MAPPINGS = [
    {"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}
]
LEADER_MAPPINGS = [
    {"type": "value", "options": {"0": {"text": "FOLLOWER", "color": "blue"}, "1": {"text": "LEADER", "color": "green"}}}
]

HEALTH_STEPS = [
    {"color": "red", "value": None},
    {"color": "orange", "value": 50},
    {"color": "yellow", "value": 80},
    {"color": "green", "value": 90},
]
PCT_STEPS = [
    {"color": "green", "value": None},
    {"color": "yellow", "value": 70},
    {"color": "orange", "value": 80},
    {"color": "red", "value": 90},
]
UP_STEPS = [
    {"color": "red", "value": None},
    {"color": "green", "value": 1},
]


def ds_var() -> dict:
    return {
        "name": "datasource",
        "label": "Prometheus",
        "type": "datasource",
        "query": "prometheus",
        "refresh": 1,
        "hide": 0,
        "multi": False,
        "includeAll": False,
    }


def qvar(name: str, label: str, query: str, *, multi: bool = False, include_all: bool = False) -> dict:
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DS,
        "query": {"query": query, "refId": "StandardVariableQuery"},
        "refresh": 2,
        "sort": 1,
        "multi": multi,
        "includeAll": include_all,
        "hide": 0,
    }


def row_panel(pid: int, title: str, y: int, *, collapsed: bool = False, panels: list[dict] | None = None) -> dict:
    p: dict = {
        "id": pid,
        "type": "row",
        "title": title,
        "collapsed": collapsed,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": panels if collapsed and panels else [],
    }
    return p


def stat_panel(
    pid: int,
    title: str,
    pos: dict,
    expr: str,
    *,
    unit: str = "short",
    steps: list[dict] | None = None,
    legend: str = "",
    color_mode: str = "value",
    graph_mode: str = "area",
    mappings: list[dict] | None = None,
    links: list[dict] | None = None,
    decimals: int | None = None,
) -> dict:
    defaults: dict = {
        "unit": unit,
        "thresholds": {"mode": "absolute", "steps": steps or [{"color": "green", "value": None}]},
    }
    if mappings:
        defaults["mappings"] = mappings
    if links:
        defaults["links"] = links
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "gridPos": pos,
        "datasource": DS,
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": legend, "refId": "A"}],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": color_mode,
            "graphMode": graph_mode,
            "justifyMode": "auto",
        },
    }


def gauge_panel(
    pid: int,
    title: str,
    pos: dict,
    expr: str,
    *,
    unit: str = "percent",
    min_v: float = 0,
    max_v: float = 100,
    steps: list[dict] | None = None,
    legend: str = "",
    links: list[dict] | None = None,
) -> dict:
    defaults: dict = {
        "unit": unit,
        "min": min_v,
        "max": max_v,
        "thresholds": {"mode": "absolute", "steps": steps or PCT_STEPS},
    }
    if links:
        defaults["links"] = links
    return {
        "id": pid,
        "type": "gauge",
        "title": title,
        "gridPos": pos,
        "datasource": DS,
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": legend, "refId": "A"}],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
        },
    }


def bargauge_panel(
    pid: int,
    title: str,
    pos: dict,
    expr: str,
    *,
    unit: str = "short",
    min_v: float = 0,
    max_v: float | None = 100,
    steps: list[dict] | None = None,
    legend: str = "{{name}}",
    orientation: str = "horizontal",
    links: list[dict] | None = None,
) -> dict:
    defaults: dict = {
        "unit": unit,
        "min": min_v,
        "thresholds": {"mode": "absolute", "steps": steps or HEALTH_STEPS},
    }
    if max_v is not None:
        defaults["max"] = max_v
    if links:
        defaults["links"] = links
    return {
        "id": pid,
        "type": "bargauge",
        "title": title,
        "gridPos": pos,
        "datasource": DS,
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": legend, "refId": "A"}],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": orientation,
            "displayMode": "gradient",
            "valueMode": "color",
            "showUnfilled": True,
        },
    }


def color_override(match_name: str, color: str) -> dict:
    return {
        "matcher": {"id": "byRegexp", "options": match_name},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}],
    }


def ts_panel(
    pid: int,
    title: str,
    pos: dict,
    targets: list[tuple[str, str]],
    *,
    unit: str = "short",
    min_v: float | None = 0,
    max_v: float | None = None,
    line_w: int = 2,
    fill: int = 18,
    overrides: list[dict] | None = None,
    links: list[dict] | None = None,
    legend_table: bool = True,
) -> dict:
    defaults: dict = {
        "unit": unit,
        "custom": {
            "drawStyle": "line",
            "lineInterpolation": "smooth",
            "lineWidth": line_w,
            "fillOpacity": fill,
            "gradientMode": "opacity",
            "showPoints": "never",
            "spanNulls": True,
        },
    }
    if min_v is not None:
        defaults["min"] = min_v
    if max_v is not None:
        defaults["max"] = max_v
    if links:
        defaults["links"] = links
    legend = (
        {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "mean", "max"], "showLegend": True}
        if legend_table
        else {"displayMode": "list", "placement": "bottom", "showLegend": True}
    )
    return {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "gridPos": pos,
        "datasource": DS,
        "targets": [
            {"datasource": DS, "expr": expr, "legendFormat": leg, "refId": chr(65 + i)}
            for i, (expr, leg) in enumerate(targets)
        ],
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {"tooltip": {"mode": "multi", "sort": "desc"}, "legend": legend},
    }


def table_panel(pid: int, title: str, pos: dict, expr: str, *, unit: str = "short") -> dict:
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "gridPos": pos,
        "datasource": DS,
        "targets": [{"datasource": DS, "expr": expr, "instant": True, "format": "table", "legendFormat": "", "refId": "A"}],
        "transformations": [
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time": True,
                        "__name__": True,
                        "instance": True,
                        "job": True,
                        "tenant": True,
                        "type": True,
                        "uuid": True,
                    }
                },
            }
        ],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"showHeader": True, "cellHeight": "sm"},
    }


def make_dashboard(uid: str, title: str, variables: list[dict], panels: list[dict], *, tags: list[str] | None = None) -> dict:
    full_vars = ([ds_var()] + variables) if variables else []
    return {
        "uid": uid,
        "title": title,
        "tags": tags or ["avi", "load-balancer"],
        "timezone": "browser",
        "schemaVersion": 41,
        "version": 1,
        "refresh": "1m",
        "time": {"from": "now-6h", "to": "now"},
        "editable": True,
        "graphTooltip": 1,
        "links": NAV_LINKS,
        "annotations": {"list": []},
        "templating": {"list": full_vars},
        "panels": panels,
    }


SE_DRILLDOWN = [
    {
        "title": "Inspect Service Engine ${__field.labels.name}",
        "url": "/d/avi-se-specific?var-datasource=${datasource}&var-instance=${instance}&var-tenant=${tenant}&var-serviceengine=${__field.labels.name}&from=${__from}&to=${__to}",
        "targetBlank": False,
    }
]
VS_DRILLDOWN = [
    {
        "title": "Inspect Virtual Service ${__field.labels.name}",
        "url": "/d/avi-vs-specific?var-datasource=${datasource}&var-instance=${instance}&var-tenant=${tenant}&var-virtualservice=${__field.labels.name}&from=${__from}&to=${__to}",
        "targetBlank": False,
    }
]
POOL_DRILLDOWN = [
    {
        "title": "Inspect Pool ${__field.labels.name}",
        "url": "/d/avi-pool-specific?var-datasource=${datasource}&var-instance=${instance}&var-tenant=${tenant}&var-pool=${__field.labels.name}&from=${__from}&to=${__to}",
        "targetBlank": False,
    }
]


def build_all() -> dict[str, dict]:
    dashboards: dict[str, dict] = {}

    # 1. Index Hub
    dashboards["Avi-dashboards.json"] = make_dashboard(
        "avi-dashboards",
        "Avi Dashboards",
        [],
        [
            {
                "id": 1,
                "type": "dashlist",
                "title": "VMware Avi Load Balancer Dashboards",
                "gridPos": {"h": 12, "w": 24, "x": 0, "y": 0},
                "options": {
                    "keepTime": True,
                    "includeVars": False,
                    "showStarred": False,
                    "showRecentlyViewed": False,
                    "showSearch": True,
                    "showHeadings": True,
                    "maxItems": 20,
                    "query": "",
                    "tags": ["avi"],
                },
            }
        ],
    )

    # 2. Avi — Summary (Executive Overview + Drill-Down Hub)
    dashboards["Avi-Summary.json"] = make_dashboard(
        "avi-summary",
        "Avi — Summary (Overview)",
        [
            qvar("instance", "Controller", 'label_values({type="controller"},instance)'),
            qvar("tenant", "Tenant", 'label_values({type="virtualservice",instance=~"$instance"},tenant)'),
        ],
        [
            row_panel(100, "Executive Fleet Health & Capacity", 0),
            stat_panel(1, "VS UP", {"h": 4, "w": 3, "x": 0, "y": 1}, 'avi_vs_up_count{instance="$instance", tenant="$tenant"}', color_mode="background_solid", graph_mode="none", steps=UP_STEPS),
            stat_panel(2, "% VS UP", {"h": 4, "w": 3, "x": 3, "y": 1}, 'avi_vs_up_percent{instance="$instance", tenant="$tenant"}', unit="percent", color_mode="background_solid", graph_mode="none", steps=[{"color": "red", "value": None}, {"color": "orange", "value": 80}, {"color": "green", "value": 100}]),
            stat_panel(3, "SEs UP", {"h": 4, "w": 3, "x": 6, "y": 1}, 'avi_se_up_count{instance="$instance", tenant="$tenant"}', color_mode="background_solid", graph_mode="none", steps=UP_STEPS),
            stat_panel(4, "Active Cluster Nodes", {"h": 4, "w": 3, "x": 9, "y": 1}, 'avi_cluster_active_members{instance="$instance"}', color_mode="background_solid", graph_mode="none", steps=UP_STEPS),
            stat_panel(5, "Total SE PPS (All NICs)", {"h": 4, "w": 3, "x": 12, "y": 1}, 'sum(avi_se_total_pps{instance="$instance", tenant="$tenant"})', unit="pps", decimals=1),
            stat_panel(6, "Total Bandwidth", {"h": 4, "w": 3, "x": 15, "y": 1}, 'sum(avi_se_if_avg_bandwidth{instance="$instance", tenant="$tenant"})', unit="bps"),
            stat_panel(7, "Total CPS", {"h": 4, "w": 3, "x": 18, "y": 1}, 'sum(avi_l4_client_avg_new_established_conns{instance="$instance", tenant="$tenant", type="virtualservice"})', decimals=1),
            gauge_panel(8, "Licensed Cores %", {"h": 4, "w": 3, "x": 21, "y": 1}, 'max(avi_license_cores_used_percent{instance="$instance"})', steps=PCT_STEPS),

            row_panel(101, "Live Status & Drill-Down (Click any SE, VS, or Pool)", 5),
            bargauge_panel(9, "Service Engine Healthscores (Click to Drill Down)", {"h": 6, "w": 8, "x": 0, "y": 6}, 'avi_healthscore_health_score_value{instance="$instance", tenant="$tenant", type="serviceengine"}', steps=HEALTH_STEPS, links=SE_DRILLDOWN),
            bargauge_panel(10, "Virtual Service Healthscores (Click to Drill Down)", {"h": 6, "w": 8, "x": 8, "y": 6}, 'avi_healthscore_health_score_value{instance="$instance", tenant="$tenant", type="virtualservice"}', steps=HEALTH_STEPS, links=VS_DRILLDOWN),
            bargauge_panel(11, "Pool Backend Uptime % (Click to Drill Down)", {"h": 6, "w": 8, "x": 16, "y": 6}, 'avi_l4_server_avg_server_uptime{instance="$instance", tenant="$tenant", type="pool"}', unit="percent", legend="{{name}} ({{server}})", steps=HEALTH_STEPS, links=POOL_DRILLDOWN),

            row_panel(102, "Traffic, Packet Rate & Service Engine Resources", 12),
            ts_panel(
                12,
                "Service Engine Combined PPS (All NICs, RX+TX)",
                {"h": 8, "w": 12, "x": 0, "y": 13},
                [
                    ('avi_se_total_pps{instance="$instance", tenant="$tenant"}', "{{name}} Combined (RX+TX)"),
                    ('avi_se_total_rx_pps{instance="$instance", tenant="$tenant"}', "{{name}} RX"),
                    ('avi_se_total_tx_pps{instance="$instance", tenant="$tenant"}', "{{name}} TX"),
                ],
                unit="pps",
                overrides=[
                    color_override(".*Combined.*", "green"),
                    color_override(".*RX.*", "light-blue"),
                    color_override(".*TX.*", "purple"),
                ],
                links=SE_DRILLDOWN,
            ),
            ts_panel(
                13,
                "Service Engine CPU % & Memory %",
                {"h": 8, "w": 12, "x": 12, "y": 13},
                [
                    ('avi_se_stats_avg_cpu_usage{instance="$instance", tenant="$tenant"}', "{{name}} CPU %"),
                    ('avi_se_stats_avg_mem_usage{instance="$instance", tenant="$tenant"}', "{{name}} Overall Mem %"),
                    ('avi_se_stats_avg_connection_mem_usage{instance="$instance", tenant="$tenant"}', "{{name}} Conn Mem %"),
                ],
                unit="percent",
                max_v=100,
                links=SE_DRILLDOWN,
            ),
            ts_panel(
                14,
                "Total SE vs Virtual Service Bandwidth",
                {"h": 7, "w": 12, "x": 0, "y": 21},
                [
                    ('sum(avi_se_if_avg_bandwidth{instance="$instance", tenant="$tenant"})', "Total SE Bandwidth"),
                    ('sum(avi_l4_client_avg_bandwidth{instance="$instance", tenant="$tenant", type="virtualservice"})', "Total VS Bandwidth"),
                ],
                unit="bps",
            ),
            ts_panel(
                15,
                "Controller CPU %, Memory % & Disk %",
                {"h": 7, "w": 12, "x": 12, "y": 21},
                [
                    ('avi_controller_stats_avg_cpu_usage{instance="$instance", type="controller"}', "Controller CPU %"),
                    ('avi_controller_stats_avg_mem_usage{instance="$instance", type="controller"}', "Controller Mem %"),
                    ('avi_controller_stats_avg_disk_usage{instance="$instance", type="controller"}', "Controller Disk %"),
                ],
                unit="percent",
                max_v=100,
            ),

            row_panel(103, "Inventory, Cluster & Alerts", 28),
            ts_panel(
                16,
                "Pool Backend Servers (Total / Enabled / UP)",
                {"h": 6, "w": 8, "x": 0, "y": 29},
                [
                    ('avi_pool_servers_total{instance="$instance", tenant="$tenant"}', "{{name}} Total"),
                    ('avi_pool_servers_enabled{instance="$instance", tenant="$tenant"}', "{{name}} Enabled"),
                    ('avi_pool_servers_up{instance="$instance", tenant="$tenant"}', "{{name}} UP"),
                ],
                links=POOL_DRILLDOWN,
            ),
            ts_panel(
                17,
                "Licensed Service Cores (Consumed vs Available)",
                {"h": 6, "w": 8, "x": 8, "y": 29},
                [
                    ('avi_license_cores_consumed{instance="$instance"}', "Consumed Cores"),
                    ('avi_license_cores_available{instance="$instance"}', "Available Cores"),
                ],
            ),
            ts_panel(
                18,
                "Active Avi Controller Alerts by Severity",
                {"h": 6, "w": 8, "x": 16, "y": 29},
                [('avi_controller_alerts_count{instance="$instance"}', "{{level}}")],
                overrides=[
                    color_override("ALERT_HIGH", "red"),
                    color_override("ALERT_MEDIUM", "orange"),
                    color_override("ALERT_LOW", "yellow"),
                ],
            ),
        ],
    )

    # 3. Avi — Controller
    dashboards["Avi-Controller.json"] = make_dashboard(
        "avi-controller",
        "Avi — Controller",
        [qvar("instance", "Controller", 'label_values({type="controller"},instance)')],
        [
            row_panel(100, "Controller Cluster & Fleet Counts", 0),
            stat_panel(1, "Cluster Leader", {"h": 4, "w": 4, "x": 0, "y": 1}, 'avi_cluster_node_is_leader{instance="$instance"}', legend="{{node}}", color_mode="background_solid", graph_mode="none", mappings=LEADER_MAPPINGS, steps=[{"color": "blue", "value": None}, {"color": "green", "value": 1}]),
            stat_panel(2, "Active Cluster Nodes", {"h": 4, "w": 4, "x": 4, "y": 1}, 'avi_cluster_active_members{instance="$instance"}', color_mode="background_solid", graph_mode="none", steps=UP_STEPS),
            stat_panel(3, "Virtual Services UP", {"h": 4, "w": 4, "x": 8, "y": 1}, 'avi_vs_up_count{instance="$instance"}', graph_mode="none"),
            stat_panel(4, "Service Engines UP", {"h": 4, "w": 4, "x": 12, "y": 1}, 'avi_se_up_count{instance="$instance"}', graph_mode="none"),
            stat_panel(5, "Backend Servers UP", {"h": 4, "w": 4, "x": 16, "y": 1}, 'sum(avi_pool_servers_up{instance="$instance"})', graph_mode="none"),
            gauge_panel(6, "Licensed Cores Used %", {"h": 4, "w": 4, "x": 20, "y": 1}, 'max(avi_license_cores_used_percent{instance="$instance"})', steps=PCT_STEPS),

            row_panel(101, "Controller Compute, Memory & Storage I/O", 5),
            ts_panel(7, "Controller CPU %", {"h": 8, "w": 12, "x": 0, "y": 6}, [('avi_controller_stats_avg_cpu_usage{instance="$instance", type="controller"}', "{{name}} CPU %")], unit="percent", max_v=100),
            ts_panel(8, "Controller Memory % (Avg / Max)", {"h": 8, "w": 12, "x": 12, "y": 6}, [
                ('avi_controller_stats_avg_mem_usage{instance="$instance", type="controller"}', "{{name}} Avg Mem %"),
                ('avi_controller_stats_max_mem_usage{instance="$instance", type="controller"}', "{{name}} Max Mem %"),
            ], unit="percent", max_v=100),
            ts_panel(9, "Average Disk Utilization %", {"h": 8, "w": 12, "x": 0, "y": 14}, [('avi_controller_stats_avg_disk_usage{instance="$instance", type="controller"}', "{{name}} Disk %")], unit="percent", max_v=100),
            ts_panel(10, "Disk Read / Write Throughput", {"h": 8, "w": 12, "x": 12, "y": 14}, [
                ('avi_controller_stats_avg_disk_write_bytes{instance="$instance", type="controller"}', "{{name}} Write"),
                ('avi_controller_stats_avg_disk_read_bytes{instance="$instance", type="controller"}', "{{name}} Read"),
            ], unit="Bps", overrides=[color_override(".*Write.*", "purple"), color_override(".*Read.*", "light-blue")]),
            ts_panel(11, "Active Avi Controller Alerts", {"h": 6, "w": 24, "x": 0, "y": 22}, [('avi_controller_alerts_count{instance="$instance"}', "{{level}}")], overrides=[color_override("ALERT_HIGH", "red"), color_override("ALERT_MEDIUM", "orange")]),
        ],
    )

    # 4. Avi — Service Engine Specific (Multi-NIC Per-Interface PPS + SE Memory + Health + Drops)
    dashboards["Avi-Service-Engine-Specific.json"] = make_dashboard(
        "avi-se-specific",
        "Avi — Service Engine Specific",
        [
            qvar("instance", "Controller", 'label_values({type="serviceengine"},instance)'),
            qvar("tenant", "Tenant", 'label_values({type="serviceengine",instance=~"$instance"},tenant)'),
            qvar("serviceengine", "Service Engine", 'label_values({instance=~"$instance",tenant="$tenant",type="serviceengine"},name)'),
        ],
        [
            row_panel(100, "Service Engine Status & Capacity", 0),
            stat_panel(1, "SE Oper Status", {"h": 4, "w": 3, "x": 0, "y": 1}, 'avi_se_oper_status{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', color_mode="background_solid", graph_mode="none", mappings=UP_DOWN_MAPPINGS, steps=UP_STEPS),
            stat_panel(2, "Healthscore", {"h": 4, "w": 3, "x": 3, "y": 1}, 'avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', color_mode="background_solid", graph_mode="none", steps=HEALTH_STEPS),
            gauge_panel(3, "CPU %", {"h": 4, "w": 3, "x": 6, "y": 1}, 'avi_se_stats_avg_cpu_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', steps=PCT_STEPS),
            gauge_panel(4, "Overall Memory %", {"h": 4, "w": 3, "x": 9, "y": 1}, 'avi_se_stats_avg_mem_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', steps=PCT_STEPS),
            gauge_panel(5, "Conn Memory %", {"h": 4, "w": 3, "x": 12, "y": 1}, 'avi_se_stats_avg_connection_mem_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', steps=PCT_STEPS),
            stat_panel(6, "VS Hosted", {"h": 4, "w": 3, "x": 15, "y": 1}, 'avi_se_vs_count{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', graph_mode="none"),
            stat_panel(7, "Missed Heartbeats", {"h": 4, "w": 3, "x": 18, "y": 1}, 'avi_se_missed_heartbeats{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', color_mode="background_solid", graph_mode="none", steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 3}]),
            stat_panel(8, "Active NICs", {"h": 4, "w": 3, "x": 21, "y": 1}, 'count(avi_se_interface_total_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"})', graph_mode="none"),

            row_panel(101, "Multi-NIC Per-Interface & Combined SE Packet Rate (PPS)", 5),
            stat_panel(9, "Combined SE Total PPS (All NICs, RX+TX)", {"h": 4, "w": 8, "x": 0, "y": 6}, 'avi_se_total_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', unit="pps", decimals=1, steps=[{"color": "green", "value": None}, {"color": "orange", "value": 2500}, {"color": "red", "value": 5000}]),
            stat_panel(10, "Combined SE RX PPS (All NICs)", {"h": 4, "w": 8, "x": 8, "y": 6}, 'avi_se_total_rx_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', unit="pps", decimals=1, steps=[{"color": "light-blue", "value": None}]),
            stat_panel(11, "Combined SE TX PPS (All NICs)", {"h": 4, "w": 8, "x": 16, "y": 6}, 'avi_se_total_tx_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', unit="pps", decimals=1, steps=[{"color": "purple", "value": None}]),
            ts_panel(
                12,
                "Per-Interface Combined PPS (RX + TX per NIC)",
                {"h": 8, "w": 12, "x": 0, "y": 10},
                [('avi_se_interface_total_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "{{interface}} (RX+TX)")],
                unit="pps",
            ),
            ts_panel(
                13,
                "Entire SE Combined PPS (All NICs: Total / RX / TX)",
                {"h": 8, "w": 12, "x": 12, "y": 10},
                [
                    ('avi_se_total_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "SE Combined Total (RX+TX)"),
                    ('avi_se_total_rx_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "SE Combined RX"),
                    ('avi_se_total_tx_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "SE Combined TX"),
                ],
                unit="pps",
                overrides=[
                    color_override(".*Total.*", "green"),
                    color_override(".*RX.*", "light-blue"),
                    color_override(".*TX.*", "purple"),
                ],
            ),
            ts_panel(
                14,
                "Per-Interface RX PPS (Each NIC)",
                {"h": 7, "w": 12, "x": 0, "y": 18},
                [('avi_se_interface_rx_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "{{interface}} RX")],
                unit="pps",
            ),
            ts_panel(
                15,
                "Per-Interface TX PPS (Each NIC)",
                {"h": 7, "w": 12, "x": 12, "y": 18},
                [('avi_se_interface_tx_pps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "{{interface}} TX")],
                unit="pps",
            ),
            ts_panel(
                16,
                "Per-Interface Bandwidth (bps)",
                {"h": 7, "w": 12, "x": 0, "y": 25},
                [('avi_se_interface_bandwidth_bps{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "{{interface}}")],
                unit="bps",
            ),
            ts_panel(
                17,
                "SE Total Bandwidth (Total / TX / RX)",
                {"h": 7, "w": 12, "x": 12, "y": 25},
                [
                    ('avi_se_if_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Total Bandwidth"),
                    ('avi_se_if_avg_rx_bytes{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"} * 8', "RX bps"),
                    ('avi_se_if_avg_tx_bytes{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"} * 8', "TX bps"),
                ],
                unit="bps",
                overrides=[
                    color_override("Total.*", "green"),
                    color_override("RX.*", "light-blue"),
                    color_override("TX.*", "purple"),
                ],
            ),

            row_panel(102, "Service Engine Memory, CPU & Health History", 32),
            ts_panel(
                18,
                "SE Memory Usage Breakdown (%)",
                {"h": 8, "w": 12, "x": 0, "y": 33},
                [
                    ('avi_se_stats_avg_mem_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Overall Memory %"),
                    ('avi_se_stats_avg_connection_mem_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Connection Memory %"),
                    ('avi_se_stats_avg_dynamic_mem_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Dynamic Memory %"),
                    ('avi_se_stats_avg_shared_memory_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Shared Memory %"),
                    ('avi_se_stats_avg_packet_buffer_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Packet Buffer %"),
                ],
                unit="percent",
                max_v=100,
            ),
            ts_panel(
                19,
                "SE CPU % & Healthscore History",
                {"h": 8, "w": 12, "x": 12, "y": 33},
                [
                    ('avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Healthscore"),
                    ('avi_se_stats_avg_cpu_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "CPU %"),
                ],
                unit="percent",
                max_v=100,
                overrides=[color_override("Healthscore", "green"), color_override("CPU.*", "orange")],
            ),

            row_panel(103, "Connections, Capacity & Packet Drops", 41),
            ts_panel(
                20,
                "SE Connections / sec (CPS) & VS Capacity %",
                {"h": 7, "w": 12, "x": 0, "y": 42},
                [
                    ('avi_se_stats_avg_connections{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "SE CPS"),
                    ('avi_se_vs_capacity_used_percent{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "VS Capacity %"),
                ],
            ),
            ts_panel(
                21,
                "Packet Drops, Buffer Pressure & Interface Errors",
                {"h": 7, "w": 12, "x": 12, "y": 42},
                [
                    ('avi_se_stats_sum_connection_dropped_memory_limit{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Conn Dropped (Mem Limit)"),
                    ('avi_se_stats_sum_packet_dropped_packet_buffer_stressed{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Pkts Dropped (Buf Stressed)"),
                    ('avi_se_stats_sum_mbstats_mbuf_allocation_failures{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Mbuf Alloc Failures"),
                    ('avi_se_if_sum_ierrors{instance=~"$instance", tenant=~"$tenant", type="serviceengine", name="$serviceengine"}', "Interface RX Errors"),
                ],
                overrides=[color_override(".*", "red")],
            ),
        ],
    )

    # 5. Avi — Service Engines Total (Fleet Comparison + Multi-NIC PPS)
    dashboards["Avi-Service-Engines-Total.json"] = make_dashboard(
        "avi-se-total",
        "Avi — Service Engines Total",
        [
            qvar("instance", "Controller", 'label_values({type="serviceengine"},instance)', multi=True, include_all=True),
            qvar("tenant", "Tenant", 'label_values({type="serviceengine",instance=~"$instance"},tenant)', multi=True, include_all=True),
        ],
        [
            row_panel(100, "Service Engine Fleet Overview (Click any SE to Drill Down)", 0),
            bargauge_panel(1, "SE Healthscores", {"h": 6, "w": 8, "x": 0, "y": 1}, 'avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="serviceengine"}', steps=HEALTH_STEPS, links=SE_DRILLDOWN),
            bargauge_panel(2, "SE Overall Memory %", {"h": 6, "w": 8, "x": 8, "y": 1}, 'avi_se_stats_avg_mem_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine"}', unit="percent", steps=PCT_STEPS, links=SE_DRILLDOWN),
            bargauge_panel(3, "SE Connection Memory %", {"h": 6, "w": 8, "x": 16, "y": 1}, 'avi_se_stats_avg_connection_mem_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine"}', unit="percent", steps=PCT_STEPS, links=SE_DRILLDOWN),

            row_panel(101, "Multi-NIC Combined & Per-Interface Packet Rates", 7),
            ts_panel(4, "Combined Total PPS per SE (All NICs, RX+TX)", {"h": 8, "w": 12, "x": 0, "y": 8}, [('avi_se_total_pps{instance=~"$instance", tenant=~"$tenant"}', "{{name}} Total (RX+TX)")], unit="pps", links=SE_DRILLDOWN),
            ts_panel(5, "Per-Interface Combined PPS (All SEs / All NICs)", {"h": 8, "w": 12, "x": 12, "y": 8}, [('avi_se_interface_total_pps{instance=~"$instance", tenant=~"$tenant"}', "{{name}} / {{interface}} (RX+TX)")], unit="pps", links=SE_DRILLDOWN),

            row_panel(102, "Bandwidth, CPU, CPS & Heartbeats", 16),
            ts_panel(6, "Total SE Bandwidth & Top 5 SE Bandwidth", {"h": 7, "w": 12, "x": 0, "y": 17}, [
                ('sum(avi_se_if_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="serviceengine"})', "Fleet Total Bandwidth"),
                ('topk(5, avi_se_if_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="serviceengine"})', "{{name}}"),
            ], unit="bps", links=SE_DRILLDOWN),
            ts_panel(7, "Top 5 SE CPU %", {"h": 7, "w": 12, "x": 12, "y": 17}, [('topk(5, avi_se_stats_avg_cpu_usage{instance=~"$instance", tenant=~"$tenant", type="serviceengine"})', "{{name}} CPU %")], unit="percent", max_v=100, links=SE_DRILLDOWN),
            ts_panel(8, "SE Connections / sec (CPS)", {"h": 7, "w": 8, "x": 0, "y": 24}, [('avi_se_stats_avg_connections{instance=~"$instance", tenant=~"$tenant", type="serviceengine"}', "{{name}} CPS")], links=SE_DRILLDOWN),
            ts_panel(9, "VS per SE & Capacity Used %", {"h": 7, "w": 8, "x": 8, "y": 24}, [
                ('avi_se_vs_count{instance=~"$instance", tenant=~"$tenant"}', "{{name}} VS Count"),
                ('avi_se_vs_capacity_used_percent{instance=~"$instance", tenant=~"$tenant"}', "{{name}} Cap %"),
            ], links=SE_DRILLDOWN),
            ts_panel(10, "SE Missed Heartbeats & Oper Status (1=UP)", {"h": 7, "w": 8, "x": 16, "y": 24}, [
                ('avi_se_missed_heartbeats{instance=~"$instance", tenant=~"$tenant"}', "{{name}} Missed HB"),
                ('avi_se_oper_status{instance=~"$instance", tenant=~"$tenant"}', "{{name}} Oper UP"),
            ], links=SE_DRILLDOWN),
        ],
    )

    # 6. Avi — Virtual Services Total
    dashboards["Avi-Virtual-Services-Total.json"] = make_dashboard(
        "avi-vs-total",
        "Avi — Virtual Services Total",
        [
            qvar("instance", "Controller", 'label_values({type="virtualservice"},instance)', multi=True, include_all=True),
            qvar("tenant", "Tenant", 'label_values({type="virtualservice",instance=~"$instance"},tenant)', multi=True, include_all=True),
        ],
        [
            row_panel(100, "Virtual Service Fleet Health (Click any VS to Drill Down)", 0),
            bargauge_panel(1, "VS Healthscores", {"h": 6, "w": 12, "x": 0, "y": 1}, 'avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="virtualservice"}', steps=HEALTH_STEPS, links=VS_DRILLDOWN),
            stat_panel(2, "VS Operational Status", {"h": 6, "w": 12, "x": 12, "y": 1}, 'avi_vs_oper_status{instance=~"$instance", tenant=~"$tenant", type="virtualservice"}', legend="{{name}}", color_mode="background_solid", graph_mode="none", mappings=UP_DOWN_MAPPINGS, steps=UP_STEPS, links=VS_DRILLDOWN),

            row_panel(101, "Top Virtual Service Traffic & Connections", 7),
            ts_panel(3, "Top 10 — Bandwidth", {"h": 7, "w": 8, "x": 0, "y": 8}, [('topk(10, avi_l4_client_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="virtualservice"})', "{{name}}")], unit="bps", links=VS_DRILLDOWN),
            ts_panel(4, "Top 10 — Connections / sec (CPS)", {"h": 7, "w": 8, "x": 8, "y": 8}, [('topk(10, avi_l4_client_avg_new_established_conns{instance=~"$instance", tenant=~"$tenant", type="virtualservice"})', "{{name}}")], links=VS_DRILLDOWN),
            ts_panel(5, "Top 10 — Concurrent Connections", {"h": 7, "w": 8, "x": 16, "y": 8}, [('topk(10, avi_l4_client_avg_complete_conns{instance=~"$instance", tenant=~"$tenant", type="virtualservice"})', "{{name}}")], links=VS_DRILLDOWN),
            ts_panel(6, "Top 10 — RX Packets / sec", {"h": 7, "w": 12, "x": 0, "y": 15}, [('topk(10, avi_l4_client_avg_rx_pkts{instance=~"$instance", tenant=~"$tenant", type="virtualservice"})', "{{name}} RX")], unit="pps", links=VS_DRILLDOWN),
            ts_panel(7, "Top 10 — TX Packets / sec", {"h": 7, "w": 12, "x": 12, "y": 15}, [('topk(10, avi_l4_client_avg_tx_pkts{instance=~"$instance", tenant=~"$tenant", type="virtualservice"})', "{{name}} TX")], unit="pps", links=VS_DRILLDOWN),
            row_panel(
                102,
                "SSL / L7 Metrics (Expand when HTTPS Virtual Services are active)",
                22,
                collapsed=True,
                panels=[
                    ts_panel(8, "Top 10 — SSL TPS", {"h": 7, "w": 24, "x": 0, "y": 23}, [('topk(10, avi_l7_client_avg_ssl_handshakes_new{instance=~"$instance", tenant=~"$tenant", type="virtualservice"})', "{{name}}")], links=VS_DRILLDOWN),
                ],
            ),
        ],
    )

    # 7. Avi — Virtual Service Specific (L4 + DNS front-and-center; L7/SSL collapsed cleanly!)
    dashboards["Avi-Virtual-Services-Specific.json"] = make_dashboard(
        "avi-vs-specific",
        "Avi — Virtual Service Specific",
        [
            qvar("instance", "Controller", 'label_values({type="virtualservice"},instance)'),
            qvar("tenant", "Tenant", 'label_values({type="virtualservice",instance=~"$instance"},tenant)'),
            qvar("virtualservice", "Virtual Service", 'label_values({instance="$instance",tenant="$tenant",type="virtualservice"},name)'),
        ],
        [
            row_panel(100, "Virtual Service Status & Key KPIs", 0),
            stat_panel(1, "Oper Status", {"h": 4, "w": 4, "x": 0, "y": 1}, 'avi_vs_oper_status{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', color_mode="background_solid", graph_mode="none", mappings=UP_DOWN_MAPPINGS, steps=UP_STEPS),
            stat_panel(2, "Healthscore", {"h": 4, "w": 4, "x": 4, "y": 1}, 'avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', color_mode="background_solid", graph_mode="none", steps=HEALTH_STEPS),
            stat_panel(3, "% SEs UP", {"h": 4, "w": 4, "x": 8, "y": 1}, 'avi_vs_percent_ses_up{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', unit="percent", graph_mode="none", steps=HEALTH_STEPS),
            stat_panel(4, "Bandwidth", {"h": 4, "w": 4, "x": 12, "y": 1}, 'avi_l4_client_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', unit="bps"),
            stat_panel(5, "CPS", {"h": 4, "w": 4, "x": 16, "y": 1}, 'avi_l4_client_avg_new_established_conns{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', decimals=1),
            stat_panel(6, "Open Connections", {"h": 4, "w": 4, "x": 20, "y": 1}, 'avi_l4_client_max_open_conns{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}'),

            row_panel(101, "L4 Traffic, Packets & Timing", 5),
            ts_panel(7, "VS Bandwidth", {"h": 7, "w": 8, "x": 0, "y": 6}, [('avi_l4_client_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Bandwidth")], unit="bps"),
            ts_panel(8, "Connections / sec & Concurrent Conns", {"h": 7, "w": 8, "x": 8, "y": 6}, [
                ('avi_l4_client_avg_new_established_conns{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "New Conns / s"),
                ('avi_l4_client_avg_complete_conns{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Complete Conns / s"),
                ('avi_l4_client_max_open_conns{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Max Open Conns"),
            ]),
            ts_panel(9, "Client RTT & Lossy Connections", {"h": 7, "w": 8, "x": 16, "y": 6}, [
                ('avi_l4_client_avg_total_rtt{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Client RTT (ms)"),
                ('avi_l4_client_avg_lossy_connections{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Lossy Conns"),
            ], unit="ms"),
            ts_panel(10, "VS RX & TX Packets / sec", {"h": 7, "w": 12, "x": 0, "y": 13}, [
                ('avi_l4_client_avg_rx_pkts{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "RX PPS"),
                ('avi_l4_client_avg_tx_pkts{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "TX PPS"),
            ], unit="pps", overrides=[color_override("RX.*", "light-blue"), color_override("TX.*", "purple")]),
            ts_panel(11, "VS Healthscore & Hosted on Service Engines", {"h": 7, "w": 12, "x": 12, "y": 13}, [
                ('avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Healthscore"),
                ('avi_vs_hosted_on_se{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"} * 100', "SE {{se_name}} (primary={{primary}})"),
            ], max_v=100),

            row_panel(102, "DNS Virtual Service Telemetry", 20),
            ts_panel(12, "DNS Queries / sec (Complete / TCP / A / AAAA)", {"h": 7, "w": 12, "x": 0, "y": 21}, [
                ('avi_dns_client_avg_complete_queries{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Complete Queries"),
                ('avi_dns_client_avg_req_type_a{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Type A"),
                ('avi_dns_client_avg_req_type_aaaa{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Type AAAA"),
                ('avi_dns_client_avg_tcp_queries{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "TCP Queries"),
            ], unit="ops"),
            ts_panel(13, "DNS Errors, Invalid Queries & NXDOMAIN / sec", {"h": 7, "w": 12, "x": 12, "y": 21}, [
                ('avi_dns_client_avg_errored_queries{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Errored Queries"),
                ('avi_dns_client_avg_invalid_queries{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Invalid Queries"),
                ('avi_dns_client_avg_local_nxdomains{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Local NXDOMAIN"),
            ], unit="ops", overrides=[color_override("Errored.*", "red"), color_override("Invalid.*", "orange")]),

            row_panel(
                103,
                "L7 HTTP / SSL / ApDex Diagnostics (Expand for HTTP/HTTPS Virtual Services)",
                28,
                collapsed=True,
                panels=[
                    ts_panel(14, "SSL Statistics / sec", {"h": 7, "w": 12, "x": 0, "y": 29}, [
                        ('avi_l7_client_avg_ssl_connections{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "SSL Conns"),
                        ('avi_l7_client_avg_ssl_handshakes_new{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "New SSL Handshakes"),
                    ]),
                    ts_panel(15, "4xx / 5xx HTTP Status Codes", {"h": 7, "w": 12, "x": 12, "y": 29}, [
                        ('avi_l7_client_avg_resp_4xx{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "4xx"),
                        ('avi_l7_client_avg_resp_4xx_avi_errors{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "4xx Avi"),
                        ('avi_l7_client_avg_resp_5xx{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "5xx"),
                        ('avi_l7_client_avg_resp_5xx_avi_errors{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "5xx Avi"),
                    ], overrides=[color_override("5xx.*", "red"), color_override("4xx.*", "orange")]),
                    ts_panel(16, "Client Data Transfer Time & ApDex", {"h": 7, "w": 24, "x": 0, "y": 36}, [
                        ('avi_l7_client_avg_client_data_transfer_time{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Client Data Transfer (ms)"),
                        ('avi_l4_client_apdexc{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "L4 ApDex"),
                        ('avi_l7_client_apdexr{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "L7 ApDex"),
                    ]),
                ],
            ),
        ],
    )

    # 8. Avi — Pool Specific
    dashboards["Avi-Pool-Specific.json"] = make_dashboard(
        "avi-pool-specific",
        "Avi — Pool Specific",
        [
            qvar("instance", "Controller", 'label_values({type="pool"},instance)'),
            qvar("tenant", "Tenant", 'label_values({type="pool",instance=~"$instance"},tenant)'),
            qvar("pool", "Pool", 'label_values({instance=~"$instance",tenant="$tenant",type="pool"},name)'),
        ],
        [
            row_panel(100, "Pool Status & Member Summary", 0),
            stat_panel(1, "Pool Oper Status", {"h": 4, "w": 4, "x": 0, "y": 1}, 'avi_pool_oper_status{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', color_mode="background_solid", graph_mode="none", mappings=UP_DOWN_MAPPINGS, steps=UP_STEPS),
            stat_panel(2, "Servers UP", {"h": 4, "w": 4, "x": 4, "y": 1}, 'avi_pool_servers_up{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', color_mode="background_solid", graph_mode="none", steps=UP_STEPS),
            stat_panel(3, "Servers Enabled / Total", {"h": 4, "w": 4, "x": 8, "y": 1}, 'avi_pool_servers_enabled{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', graph_mode="none"),
            stat_panel(4, "Healthscore", {"h": 4, "w": 4, "x": 12, "y": 1}, 'avg(avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"})', color_mode="background_solid", graph_mode="none", steps=HEALTH_STEPS),
            stat_panel(5, "Pool Bandwidth", {"h": 4, "w": 4, "x": 16, "y": 1}, 'sum(avi_l4_server_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"})', unit="bps"),
            stat_panel(6, "Pool CPS", {"h": 4, "w": 4, "x": 20, "y": 1}, 'sum(avi_l4_server_avg_new_established_conns{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"})', decimals=1),

            row_panel(101, "Pool Member Traffic, Latency & Connections", 5),
            ts_panel(7, "Pool Member Bandwidth", {"h": 7, "w": 8, "x": 0, "y": 6}, [('avi_l4_server_avg_bandwidth{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}}")], unit="bps"),
            ts_panel(8, "Connections / sec & Open Connections", {"h": 7, "w": 8, "x": 8, "y": 6}, [
                ('avi_l4_server_avg_new_established_conns{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} CPS"),
                ('avi_l4_server_avg_open_conns{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} Open"),
            ]),
            ts_panel(9, "Server RTT & Healthscore", {"h": 7, "w": 8, "x": 16, "y": 6}, [
                ('avi_l4_server_avg_total_rtt{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} RTT (ms)"),
                ('avi_healthscore_health_score_value{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} Health"),
            ]),
            ts_panel(10, "Pool Member RX & TX Packets / sec", {"h": 7, "w": 12, "x": 0, "y": 13}, [
                ('avi_l4_server_avg_rx_pkts{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} RX PPS"),
                ('avi_l4_server_avg_tx_pkts{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} TX PPS"),
            ], unit="pps", overrides=[color_override(".*RX.*", "light-blue"), color_override(".*TX.*", "purple")]),
            ts_panel(11, "Pool Members Count (Total / Enabled / UP) & Lossy Conns", {"h": 7, "w": 12, "x": 12, "y": 13}, [
                ('avi_pool_servers_total{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "Total"),
                ('avi_pool_servers_enabled{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "Enabled"),
                ('avi_pool_servers_up{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "UP"),
                ('avi_l4_server_avg_lossy_connections{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} Lossy"),
            ]),

            row_panel(102, "Pool Member Cumulative Totals (Selected Range)", 20),
            table_panel(12, "Total TX Packets by Member", {"h": 6, "w": 6, "x": 0, "y": 21}, 'sum_over_time(avi_l4_server_avg_tx_pkts{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}[$__range]) * 60'),
            table_panel(13, "Total RX Packets by Member", {"h": 6, "w": 6, "x": 6, "y": 21}, 'sum_over_time(avi_l4_server_avg_rx_pkts{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}[$__range]) * 60'),
            table_panel(14, "Total TX Bytes by Member", {"h": 6, "w": 6, "x": 12, "y": 21}, 'sum_over_time(avi_l4_server_avg_tx_bytes{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}[$__range]) * 60', unit="bytes"),
            table_panel(15, "Total RX Bytes by Member", {"h": 6, "w": 6, "x": 18, "y": 21}, 'sum_over_time(avi_l4_server_avg_rx_bytes{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}[$__range]) * 60', unit="bytes"),

            row_panel(
                103,
                "L7 Server Response Timing (Expand for HTTP Pools)",
                27,
                collapsed=True,
                panels=[
                    ts_panel(16, "Avg Server Side Latency & App Response Time", {"h": 7, "w": 24, "x": 0, "y": 28}, [
                        ('avi_l7_server_avg_resp_latency{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} Resp Latency"),
                        ('avi_l7_server_avg_application_response_time{instance=~"$instance", tenant=~"$tenant", type="pool", name="$pool"}', "{{server}} App Response"),
                    ], unit="ms"),
                ],
            ),
        ],
    )

    # 9. Avi — Virtual Services WAF & HTTP Sizing
    dashboards["Avi-Virtual-Services-WAF-Sizing.json"] = make_dashboard(
        "avi-vs-waf-sizing",
        "Avi — Virtual Services WAF & HTTP Sizing",
        [
            qvar("instance", "Controller", 'label_values({type="virtualservice"},instance)'),
            qvar("tenant", "Tenant", 'label_values({type="virtualservice",instance=~"$instance"},tenant)'),
            qvar("virtualservice", "Virtual Service", 'label_values({instance=~"$instance",tenant="$tenant",type="virtualservice"},name)'),
        ],
        [
            row_panel(100, "End-to-End Latency & WAF Inspection", 0),
            ts_panel(1, "End-to-End Timing (ms)", {"h": 7, "w": 24, "x": 0, "y": 1}, [
                ('avi_l4_client_avg_total_rtt{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Client RTT"),
                ('avi_l7_client_avg_client_data_transfer_time{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Client Data Transfer"),
                ('avi_l4_server_avg_total_rtt{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Server RTT"),
                ('avi_l7_server_avg_application_response_time{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "App Response Time"),
            ], unit="ms"),
            ts_panel(2, "WAF Requests (Evaluated / Matched / Rejected / Disabled)", {"h": 7, "w": 12, "x": 0, "y": 8}, [
                ('avi_l7_client_avg_waf_evaluated{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Evaluated"),
                ('avi_l7_client_avg_waf_matched{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Matched"),
                ('avi_l7_client_avg_waf_rejected{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Rejected"),
                ('avi_l7_client_avg_waf_disabled{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Disabled"),
            ], overrides=[color_override("Rejected", "red"), color_override("Matched", "orange")]),
            ts_panel(3, "HTTP Method Mix (GET / POST / WAF Bypass %)", {"h": 7, "w": 12, "x": 12, "y": 8}, [
                ('avi_l7_client_pct_get_reqs{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "GET %"),
                ('avi_l7_client_pct_post_reqs{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "POST %"),
                ('avi_l7_client_pct_waf_disabled{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "WAF Bypass %"),
            ], unit="percent", max_v=100),

            row_panel(101, "HTTP Payload & Header Sizing Profiles", 15),
            ts_panel(4, "Total HTTP Responses", {"h": 7, "w": 8, "x": 0, "y": 16}, [('avi_l7_client_sum_total_responses{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Responses")]),
            ts_panel(5, "Average POST Bytes", {"h": 7, "w": 8, "x": 8, "y": 16}, [('avi_l7_client_avg_post_bytes{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "POST Bytes")], unit="bytes"),
            ts_panel(6, "Average URI Length", {"h": 7, "w": 8, "x": 16, "y": 16}, [('avi_l7_client_avg_uri_length{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "URI Length")]),
            ts_panel(7, "Average HTTP Header Count", {"h": 7, "w": 8, "x": 0, "y": 23}, [('avi_l7_client_avg_http_headers_count{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Header Count")]),
            ts_panel(8, "Average HTTP Header Bytes", {"h": 7, "w": 8, "x": 8, "y": 23}, [('avi_l7_client_avg_http_headers_bytes{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Header Bytes")], unit="bytes"),
            ts_panel(9, "Average HTTP Parameter Count", {"h": 7, "w": 8, "x": 16, "y": 23}, [('avi_l7_client_avg_http_params_count{instance=~"$instance", tenant=~"$tenant", type="virtualservice", name="$virtualservice"}', "Param Count")]),
        ],
    )

    return dashboards


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for filename, doc in build_all().items():
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        print(f"Built {filename:38s} uid={doc['uid']:20s} schema={doc['schemaVersion']} top_panels={len(doc['panels'])}")


if __name__ == "__main__":
    main()
