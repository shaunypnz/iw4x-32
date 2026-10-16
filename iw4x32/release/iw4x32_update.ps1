# IW4x-32 v2.0 compatibility - NOT part of the zip. From v2.1 IW4x-32 is IW4x-32.bat + files\. A v2.0 install that
# auto-updated still starts this file ("Play IW4x-32.bat", own shortcuts): it hands over to files\iw4x32.ps1, which
# moves backup\ into files\, removes the old scripts and makes the new shortcuts.
& (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'files\iw4x32.ps1') --migrate @args
exit $LASTEXITCODE
