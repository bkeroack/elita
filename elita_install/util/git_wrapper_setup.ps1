param($cmd)

#git will run this wrapper script instead of ssh directly
$gitwrapper = @"
@echo off
ssh -F "C:\Program Files (x86)\Git\.ssh\config" -o StrictHostKeyChecking=no %*
"@

#no spaces in path--screws up git
$git_script_dir = "C:\elita-git"
$git_script = "${git_script_dir}\git-ssh-wrapper.bat"

$bin_path = "C:\Program Files (x86)\Git\bin\"

if (!(Test-Path "${git_script_dir}")) {
	New-Item -Type Directory "${git_script_dir}" |Out-Null
}

#make sure git is in system PATH
$oldpath = (Get-ItemProperty -Path 'Registry::HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\Session Manager\Environment' -Name PATH).Path
if (!($oldpath.Contains($bin_path))) {
	$newpath = $oldpath + ";C:\Program Files (x86)\Git\bin\" + ";${git_script_dir}"
	Set-ItemProperty -Path 'Registry::HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\Session Manager\Environment' -Name PATH -Value $newpath
	$env:PATH = (Get-ItemProperty -Path 'Registry::HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\Session Manager\Environment' -Name PATH).Path
}

$gitwrapper |Out-File -Encoding Ascii $git_script

#set GIT_SSH environment variable system-wide
Set-ItemProperty -Path 'Registry::HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\Session Manager\Environment' -Name GIT_SSH -Value $git_script
$env:GIT_SSH = $git_script 
