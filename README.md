# Windows System MQTT Publisher

定時讀取 Windows 電腦的系統狀態，並透過 MQTT publish JSON 到指定 topic，方便其他程式或 dashboard 呈現。

## 功能

- CPU 使用率、每核心使用率、核心數
- CPU 溫度
- 記憶體與 swap 使用狀況
- 網路上傳 / 下載速率
- 硬碟容量使用率
- 硬碟讀寫速率
- 電腦名稱與 Windows 平台資訊

## 安裝

```powershell
cd windows_system_mqtt_publisher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 執行

```powershell
$env:MQTT_HOST="broker.emqx.io"
python app.py
```

## 開機自動執行

專案提供 `start_on_boot.bat`，會啟動：

- LibreHardwareMonitor：如果 `C:\tmp\LibreHardwareMonitor-v0.9.4\LibreHardwareMonitor.exe` 存在
- MQTT publisher：`app.py`
- 手機 Dashboard HTTP server：`http://<電腦IP>:8088/mobile_dashboard.html`

手動測試：

```powershell
.\start_on_boot.bat
```

加入 Windows 開機啟動：

1. 按 `Win + R`
2. 輸入 `shell:startup`
3. 將 `start_on_boot.bat` 建立捷徑放進該資料夾

CPU 溫度若要穩定讀取，建議改用 Windows 工作排程器執行此 bat，並勾選 `以最高權限執行`。

預設會 publish 到：

```text
jj/windows/system/status
```

## 手機 Dashboard

可用手機瀏覽器開啟 `mobile_dashboard.html`，透過 MQTT WebSocket 顯示系統資訊。

預設設定：

- WebSocket：`wss://broker.emqx.io:8084/mqtt`
- Topic：`jj/windows/system/status`

如果手機和電腦不在同一台機器上，建議用簡單的本機 HTTP server 讓手機開：

```powershell
cd windows_system_mqtt_publisher
python -m http.server 8088
```

手機瀏覽器開：

```text
http://<電腦IP>:8088/mobile_dashboard.html
```

### 手機全螢幕無地址列

一般手機瀏覽器分頁不能被網頁強制隱藏地址列。若要真正無地址列顯示，請用 PWA/主畫面模式開啟：

- Android Chrome/Edge：開啟 dashboard 後，選單選 `加入主畫面` 或 `安裝應用程式`，之後從主畫面圖示開啟。
- iPhone Safari：開啟 dashboard 後，分享按鈕選 `加入主畫面`，之後從主畫面圖示開啟。

此專案已包含 `manifest.webmanifest`，以 `fullscreen` + `landscape` 模式啟動。

### 多電腦顯示

Dashboard 的第 1 頁是設定頁，可輸入要顯示的 `computer_name`，每行一台電腦。按 `Save Pages` 後，後續每一頁會各自顯示一台電腦的狀態。

- 手機上下滑動：切換上一台 / 下一台電腦
- 第 1 頁 `Detected Computers`：收到 MQTT payload 後會列出偵測到的電腦，點一下可加入顯示清單
- 設定會保存在手機瀏覽器的 `localStorage`

## 環境變數

- `MQTT_HOST`: MQTT broker host，預設 `broker.emqx.io`
- `MQTT_PORT`: MQTT broker port，預設 `1883`
- `MQTT_USERNAME`: MQTT 帳號，可空白
- `MQTT_PASSWORD`: MQTT 密碼，可空白
- `MQTT_TOPIC`: publish topic，預設 `jj/windows/system/status`
- `MQTT_CLIENT_ID`: MQTT client id，預設 `windows-system-monitor-<hostname>`
- `MQTT_QOS`: MQTT QoS，預設 `0`
- `MQTT_RETAIN`: 是否 retain message，預設 `false`
- `PUBLISH_INTERVAL_SECONDS`: publish 間隔秒數，預設 `5`
- `CPU_PERCENT_INTERVAL_SECONDS`: CPU 取樣秒數，預設 `0.2`

## Payload 範例

```json
{
  "computer_name": "DESKTOP-1234",
  "timestamp": "2026-05-07T08:30:00+00:00",
  "platform": {
    "system": "Windows",
    "release": "11",
    "version": "10.0.26100",
    "machine": "AMD64"
  },
  "cpu": {
    "usage_percent": 18.4,
    "per_cpu_percent": [12.5, 22.1, 16.0, 23.0],
    "logical_count": 16,
    "physical_count": 8,
    "temperature": {
      "celsius": 52.3,
      "source": "root/LibreHardwareMonitor",
      "sensor": "CPU Package",
      "available": true
    }
  },
  "memory": {
    "total_bytes": 34288517120,
    "available_bytes": 21000000000,
    "used_bytes": 13000000000,
    "used_percent": 38.2
  },
  "network": {
    "bytes_sent_per_second": 12345.6,
    "bytes_recv_per_second": 456789.1,
    "upload_mbps": 0.099,
    "download_mbps": 3.654
  },
  "disks": [
    {
      "device": "C:\\",
      "mountpoint": "C:\\",
      "fstype": "NTFS",
      "total_bytes": 1000202273280,
      "used_bytes": 520000000000,
      "free_bytes": 480000000000,
      "used_percent": 52.0
    }
  ],
  "disk_io": {
    "read_bytes_per_second": 1000.0,
    "write_bytes_per_second": 2000.0,
    "read_mbps": 0.008,
    "write_mbps": 0.016
  }
}
```

## CPU 溫度注意事項

Windows 沒有一致、穩定的內建 CPU 溫度 API。程式會依序嘗試：

1. LibreHardwareMonitor 的 WMI namespace：`root/LibreHardwareMonitor`
2. OpenHardwareMonitor 的 WMI namespace：`root/OpenHardwareMonitor`
3. Windows ACPI thermal zone：`root/wmi/MSAcpi_ThermalZoneTemperature`

如果抓不到，`cpu.temperature.celsius` 會是 `null`。若你需要穩定顯示 CPU 溫度，建議在 Windows 上執行 LibreHardwareMonitor，並開啟 WMI。

實測注意：

- 建議使用 LibreHardwareMonitor 的 .NET Framework 4.7.2 版本，例如 `v0.9.4` 的 `LibreHardwareMonitor-net472.zip`。
- LibreHardwareMonitor 需要保持執行中。
- 如果一般 PowerShell/Python 讀不到 `root/LibreHardwareMonitor`，請用系統管理員權限執行本 publisher。
