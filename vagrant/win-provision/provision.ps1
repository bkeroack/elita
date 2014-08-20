# Provision Windows Vagrant vm for Elita

if (Test-Path C:\vagrant_ip.txt) {
	$private_ip = Get-Content C:\vagrant_ip.txt
} else {
	Write-Host -ForegroundColor Red "Private IP file not found! Networking probably broken"
	exit 1
}

if (Test-Path C:\master_ip.txt) {
	$master_ip = Get-Content C:\master_ip.txt
} else {
	Write-Host -ForegroundColor Red "Master IP file not found! Salt probably broken"
	exit 1
}

if (Test-Path C:\minion_name.txt) {
	$minion_name = Get-Content C:\minion_name.txt
} else {
	Write-Host -ForegroundColor Red "Minion name file not found! Salt probably broken"
	exit 1
}

Write-Host "Disabling firewall"
netsh advfirewall set allprofiles state off |Out-Null

Write-Host "Setting private IP address"
New-NetIPAddress -InterfaceAlias "Ethernet 3" -IPAddress $private_ip -PrefixLength 24

Write-Host "Installing IIS"
Install-WindowsFeature Web-Server

Write-Host "Installing Chocolatey"
iex ((new-object net.webclient).DownloadString('https://chocolatey.org/install.ps1'))

Write-Host "Installing git"
choco install git

Write-Host "Downloading salt"
$progressPreference = 'silentlyContinue'
Invoke-WebRequest -UseBasicParsing -OutFile "C:\salt-minion.exe" "https://docs.saltstack.com/downloads/Salt-Minion-2014.1.10-AMD64-Setup.exe"

Write-Host "Installing salt"
C:\salt-minion.exe /S /master=$master_ip /minion-name=$minion_name

Write-Host "Waiting for install to finish"
Start-Sleep -Seconds 15

Write-Host "Copying keys"
Start-Process powershell -Verb runAs "Copy-Item C:\salt-keys\${minion_name}.pub C:\salt\conf\pki\minion\minion.pub"
Start-Process powershell -Verb runAs "Copy-Item C:\salt-keys\${minion_name}.pem C:\salt\conf\pki\minion\minion.pem"

Write-Host "Restarting salt service"
Restart-Service salt-minion

Write-Host "Creating SB dir tree"
New-Item -Type Directory "C:\ScoreBig" |Out-Null
New-Item -Type Directory "C:\ScoreBig\Configs" |Out-Null