# Crea una tarea programada de Windows que, cada hora, descarga la agenda del Concello de Redondela
# y la sube al repositorio (agenda_redondela.json). Hace falta porque redondela.gal bloquea (403)
# las peticiones desde GitHub Actions.
#
# Uso:       powershell -ExecutionPolicy Bypass -File programar_exportacion_agenda.ps1
# Eliminar:  Unregister-ScheduledTask -TaskName "Chapela Redondela - Exportar agenda Concello" -Confirm:$false

$TaskName = "Chapela Redondela - Exportar agenda Concello"
$Dir = $PSScriptRoot
$Pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source

$action = New-ScheduledTaskAction -Execute $Pythonw -Argument "monitor.py --export-redondela" -WorkingDirectory $Dir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(8) -RepetitionInterval (New-TimeSpan -Hours 1)
# StartWhenAvailable: si el PC estaba apagado a la hora prevista, se ejecuta al encenderlo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "Descarga la agenda de redondela.gal y la sube al repo (GitHub Actions recibe 403)" | Out-Null

Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
Write-Host "Tarea creada. Los resultados se registran en monitor.log."
