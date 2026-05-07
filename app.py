from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import platform
import socket
import subprocess
import time
from typing import Any

import paho.mqtt.client as mqtt
import psutil


MQTT_HOST = os.getenv("MQTT_HOST", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "jj/windows/system/status")
MQTT_CLIENT_ID = os.getenv(
    "MQTT_CLIENT_ID",
    f"windows-system-monitor-{socket.gethostname().replace(' ', '-').replace('_', '-')}",
)
MQTT_QOS = int(os.getenv("MQTT_QOS", "0"))
MQTT_RETAIN = os.getenv("MQTT_RETAIN", "false").strip().lower() in {"1", "true", "yes", "on"}

PUBLISH_INTERVAL_SECONDS = float(os.getenv("PUBLISH_INTERVAL_SECONDS", "5"))
CPU_PERCENT_INTERVAL_SECONDS = float(os.getenv("CPU_PERCENT_INTERVAL_SECONDS", "0.2"))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger("windows_system_mqtt_publisher")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bytes_per_second_to_mbps(bytes_per_second: float) -> float:
    return round(bytes_per_second * 8 / 1_000_000, 3)


def run_powershell_json(script: str) -> Any:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=4,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def read_cpu_temperature_from_hardware_monitor() -> dict[str, Any]:
    script = r"""
$namespaces = @('root/LibreHardwareMonitor', 'root/OpenHardwareMonitor')
foreach ($ns in $namespaces) {
  try {
    $sensors = Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop |
      Where-Object { $_.SensorType -eq 'Temperature' -and ($_.Name -match 'CPU|Package|Core') } |
      Select-Object Name, Value
    if ($sensors) {
      $best = $sensors | Sort-Object @{ Expression = {
        if ($_.Name -match 'Package') { 0 }
        elseif ($_.Name -match 'CPU') { 1 }
        else { 2 }
      }} | Select-Object -First 1
      [pscustomobject]@{
        celsius = [math]::Round([double]$best.Value, 1)
        source = $ns
        sensor = $best.Name
      } | ConvertTo-Json -Compress
      exit 0
    }
  } catch {}
}
"""
    result = run_powershell_json(script)
    if isinstance(result, dict) and result.get("celsius") is not None:
        return {
            "celsius": result.get("celsius"),
            "source": result.get("source"),
            "sensor": result.get("sensor"),
            "available": True,
        }
    return {"celsius": None, "source": None, "sensor": None, "available": False}


def read_cpu_temperature_from_thermal_zone() -> dict[str, Any]:
    script = r"""
try {
  $zones = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop |
    Where-Object { $_.CurrentTemperature -gt 0 } |
    ForEach-Object {
      [pscustomobject]@{
        celsius = [math]::Round(($_.CurrentTemperature / 10) - 273.15, 1)
        instance = $_.InstanceName
      }
    }
  if ($zones) {
    $best = $zones | Sort-Object celsius -Descending | Select-Object -First 1
    [pscustomobject]@{
      celsius = $best.celsius
      source = 'root/wmi/MSAcpi_ThermalZoneTemperature'
      sensor = $best.instance
    } | ConvertTo-Json -Compress
  }
} catch {}
"""
    result = run_powershell_json(script)
    if isinstance(result, dict) and result.get("celsius") is not None:
        return {
            "celsius": result.get("celsius"),
            "source": result.get("source"),
            "sensor": result.get("sensor"),
            "available": True,
        }
    return {"celsius": None, "source": None, "sensor": None, "available": False}


def read_cpu_temperature() -> dict[str, Any]:
    hardware_monitor = read_cpu_temperature_from_hardware_monitor()
    if hardware_monitor["available"]:
        return hardware_monitor

    thermal_zone = read_cpu_temperature_from_thermal_zone()
    if thermal_zone["available"]:
        return thermal_zone

    return {
        "celsius": None,
        "source": None,
        "sensor": None,
        "available": False,
        "note": "Windows does not expose CPU temperature consistently. Run LibreHardwareMonitor or OpenHardwareMonitor to publish CPU temperature through WMI.",
    }


def read_disk_usage() -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    for partition in psutil.disk_partitions(all=False):
        if not partition.fstype:
            continue

        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError):
            continue

        disks.append(
            {
                "device": partition.device,
                "mountpoint": partition.mountpoint,
                "fstype": partition.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "used_percent": usage.percent,
            }
        )
    return disks


def read_disk_io(previous: psutil._common.sdiskio | None, elapsed_seconds: float) -> tuple[dict[str, Any], psutil._common.sdiskio]:
    current = psutil.disk_io_counters()
    if previous is None or current is None or elapsed_seconds <= 0:
        return (
            {
                "read_bytes_per_second": 0,
                "write_bytes_per_second": 0,
                "read_mbps": 0,
                "write_mbps": 0,
            },
            current,
        )

    read_bps = max(0, (current.read_bytes - previous.read_bytes) / elapsed_seconds)
    write_bps = max(0, (current.write_bytes - previous.write_bytes) / elapsed_seconds)
    return (
        {
            "read_bytes_per_second": round(read_bps, 1),
            "write_bytes_per_second": round(write_bps, 1),
            "read_mbps": bytes_per_second_to_mbps(read_bps),
            "write_mbps": bytes_per_second_to_mbps(write_bps),
        },
        current,
    )


def read_network_usage(
    previous: psutil._common.snetio | None,
    elapsed_seconds: float,
) -> tuple[dict[str, Any], psutil._common.snetio]:
    current = psutil.net_io_counters()
    if previous is None or elapsed_seconds <= 0:
        return (
            {
                "bytes_sent_per_second": 0,
                "bytes_recv_per_second": 0,
                "upload_mbps": 0,
                "download_mbps": 0,
                "total_bytes_sent": current.bytes_sent,
                "total_bytes_recv": current.bytes_recv,
            },
            current,
        )

    sent_bps = max(0, (current.bytes_sent - previous.bytes_sent) / elapsed_seconds)
    recv_bps = max(0, (current.bytes_recv - previous.bytes_recv) / elapsed_seconds)
    return (
        {
            "bytes_sent_per_second": round(sent_bps, 1),
            "bytes_recv_per_second": round(recv_bps, 1),
            "upload_mbps": bytes_per_second_to_mbps(sent_bps),
            "download_mbps": bytes_per_second_to_mbps(recv_bps),
            "total_bytes_sent": current.bytes_sent,
            "total_bytes_recv": current.bytes_recv,
        },
        current,
    )


def build_payload(
    previous_network: psutil._common.snetio | None,
    previous_disk_io: psutil._common.sdiskio | None,
    elapsed_seconds: float,
) -> tuple[dict[str, Any], psutil._common.snetio, psutil._common.sdiskio]:
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    network, current_network = read_network_usage(previous_network, elapsed_seconds)
    disk_io, current_disk_io = read_disk_io(previous_disk_io, elapsed_seconds)

    payload = {
        "computer_name": socket.gethostname(),
        "timestamp": utc_now_iso(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "cpu": {
            "usage_percent": psutil.cpu_percent(interval=CPU_PERCENT_INTERVAL_SECONDS),
            "per_cpu_percent": psutil.cpu_percent(interval=None, percpu=True),
            "logical_count": psutil.cpu_count(logical=True),
            "physical_count": psutil.cpu_count(logical=False),
            "temperature": read_cpu_temperature(),
        },
        "memory": {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "used_bytes": memory.used,
            "used_percent": memory.percent,
        },
        "swap": {
            "total_bytes": swap.total,
            "used_bytes": swap.used,
            "free_bytes": swap.free,
            "used_percent": swap.percent,
        },
        "network": network,
        "disks": read_disk_usage(),
        "disk_io": disk_io,
    }
    return payload, current_network, current_disk_io


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    if reason_code == 0:
        LOGGER.info("Connected to MQTT broker %s:%s", MQTT_HOST, MQTT_PORT)
        return

    LOGGER.error("MQTT connection failed with code %s", reason_code)


def build_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    return client


def publish_loop(client: mqtt.Client) -> None:
    previous_network = psutil.net_io_counters()
    previous_disk_io = psutil.disk_io_counters()
    previous_time = time.monotonic()

    while True:
        now = time.monotonic()
        elapsed_seconds = max(0.001, now - previous_time)
        payload, previous_network, previous_disk_io = build_payload(
            previous_network,
            previous_disk_io,
            elapsed_seconds,
        )
        previous_time = time.monotonic()

        encoded_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        result = client.publish(MQTT_TOPIC, encoded_payload, qos=MQTT_QOS, retain=MQTT_RETAIN)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            LOGGER.info(
                "Published system status to %s cpu=%s%% memory=%s%% down=%sMbps up=%sMbps",
                MQTT_TOPIC,
                payload["cpu"]["usage_percent"],
                payload["memory"]["used_percent"],
                payload["network"]["download_mbps"],
                payload["network"]["upload_mbps"],
            )
        else:
            LOGGER.warning("MQTT publish returned code %s", result.rc)

        time.sleep(PUBLISH_INTERVAL_SECONDS)


def main() -> None:
    LOGGER.info("Connecting to MQTT broker %s:%s", MQTT_HOST, MQTT_PORT)
    LOGGER.info("Publishing topic: %s", MQTT_TOPIC)

    client = build_client()
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except (ConnectionRefusedError, TimeoutError, OSError, socket.gaierror) as exc:
        LOGGER.error("Unable to connect to MQTT broker %s:%s", MQTT_HOST, MQTT_PORT)
        raise SystemExit(1) from exc

    client.loop_start()
    try:
        publish_loop(client)
    except KeyboardInterrupt:
        LOGGER.info("Stopping publisher")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
