[CmdletBinding()]
param(
    [string]$OutputPath = ".\workstation-diagnostics.txt"
)

# Read-only Tier 1 collection. Review organizational policy before running on a managed device.
$ErrorActionPreference = "Continue"
$sections = [System.Collections.Generic.List[string]]::new()

function Add-Section {
    param([string]$Name, [scriptblock]$Command)
    $sections.Add("`n=== $Name ===")
    try {
        $sections.Add(((& $Command | Out-String).Trim()))
    }
    catch {
        $sections.Add("Collection failed: $($_.Exception.Message)")
    }
}

Add-Section "Timestamp" { Get-Date -Format "yyyy-MM-dd HH:mm:ss K" }
Add-Section "Computer" { Get-ComputerInfo | Select-Object CsName, WindowsProductName, WindowsVersion, OsBuildNumber }
Add-Section "Logged-on user" { [System.Security.Principal.WindowsIdentity]::GetCurrent().Name }
Add-Section "IP configuration" { Get-NetIPConfiguration | Format-List InterfaceAlias, IPv4Address, IPv4DefaultGateway, DNSServer }
Add-Section "DNS test" { Resolve-DnsName microsoft.com -ErrorAction Stop | Select-Object Name, Type, IPAddress }
Add-Section "Disk" { Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID, Size, FreeSpace }
Add-Section "Recent system errors" { Get-WinEvent -FilterHashtable @{LogName='System'; Level=2; StartTime=(Get-Date).AddHours(-24)} -MaxEvents 20 | Select-Object TimeCreated, ProviderName, Id, Message }
Add-Section "Microsoft Defender status" { Get-MpComputerStatus | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, AntivirusSignatureLastUpdated }

$sections | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host "Diagnostic report written to $OutputPath"
