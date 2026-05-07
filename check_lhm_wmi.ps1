$ErrorActionPreference = "Continue"

$outputPath = "C:\tmp\lhm_wmi_check_verbose.txt"
New-Item -ItemType Directory -Path (Split-Path $outputPath) -Force | Out-Null

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("Time: $(Get-Date -Format o)")
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$lines.Add("IsAdmin: $($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))")
$lines.Add("")
$lines.Add("LibreHardwareMonitor processes:")

try {
    $processes = Get-CimInstance Win32_Process -Filter "name='LibreHardwareMonitor.exe'"
    if ($processes) {
        $lines.Add(($processes | Select-Object ProcessId,ExecutablePath,CommandLine | Format-Table -AutoSize | Out-String))
    } else {
        $lines.Add("(none)")
    }
} catch {
    $lines.Add("ERROR reading processes: $($_.Exception.Message)")
}

$lines.Add("")
$lines.Add("Matching WMI namespaces under root:")
try {
    $namespaces = Get-CimInstance -Namespace root -ClassName __NAMESPACE |
        Where-Object { $_.Name -match "Libre|Open" } |
        Select-Object Name
    if ($namespaces) {
        $lines.Add(($namespaces | Format-Table -AutoSize | Out-String))
    } else {
        $lines.Add("(none)")
    }
} catch {
    $lines.Add("ERROR reading namespaces: $($_.Exception.Message)")
}

$lines.Add("")
$lines.Add("Temperature sensors:")
try {
    $sensors = Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor -ErrorAction Stop |
        Where-Object { $_.SensorType -eq "Temperature" } |
        Select-Object -First 20 Name,SensorType,Value,Identifier
    if ($sensors) {
        $lines.Add(($sensors | Format-Table -AutoSize | Out-String))
    } else {
        $lines.Add("(none)")
    }
} catch {
    $lines.Add("ERROR reading sensors: $($_.Exception.Message)")
}

$lines | Set-Content -Path $outputPath -Encoding UTF8
