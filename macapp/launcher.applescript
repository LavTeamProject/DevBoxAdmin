-- Service Admin.app: peluncur ringan. Memastikan server jalan, membuka dashboard
-- http://127.0.0.1:8765 di browser default, lalu keluar (tanpa jendela sendiri).
-- Dikompilasi oleh ../install.sh dengan /usr/bin/osacompile (bagian dari macOS, TANPA Command Line Tools).
--
-- Urutan menyalakan server: LaunchAgent `local.service-admin` (dipasang install.sh),
-- lalu cadangan: menjalankan server.py langsung dengan Python bawaan panel.
-- SAProjectDir / SAPython ditulis install.sh ke Info.plist aplikasi ini.

property port : "8765"
property agentLabel : "local.service-admin"

on serverUp()
	try
		do shell script "/usr/bin/curl -fs -m 2 -o /dev/null http://127.0.0.1:" & port & "/api/jobs"
		return true
	on error
		return false
	end try
end serverUp

on plistValue(keyName)
	set infoPath to (POSIX path of (path to me)) & "Contents/Info"
	try
		return do shell script "/usr/bin/defaults read " & quoted form of infoPath & " " & keyName
	on error
		return ""
	end try
end plistValue

on startServer()
	-- 1) LaunchAgent
	try
		do shell script "/bin/launchctl kickstart gui/$(/usr/bin/id -u)/" & agentLabel
		return
	end try
	-- 2) jalankan langsung; nohup + & agar server tetap hidup setelah peluncur ini keluar
	set projectDir to plistValue("SAProjectDir")
	set pythonPath to plistValue("SAPython")
	if projectDir is "" or pythonPath is "" then return
	set logs to (POSIX path of (path to home folder)) & ".service-admin/logs"
	do shell script "/bin/mkdir -p " & quoted form of logs
	try
		do shell script "cd " & quoted form of projectDir & "; nohup " & quoted form of pythonPath & " server.py </dev/null >>" & quoted form of (logs & "/server.log") & " 2>>" & quoted form of (logs & "/server.err") & " &"
	end try
end startServer

-- /usr/bin/open tidak memerlukan izin Apple Events (open location bisa menggantung menunggu dialog izin)
on openDashboard()
	do shell script "/usr/bin/open http://127.0.0.1:" & port & "/"
end openDashboard

on waitForServer(maxTries)
	repeat maxTries times
		if serverUp() then return true
		delay 0.25
	end repeat
	return false
end waitForServer

on run
	set ready to serverUp()
	if not ready then
		startServer()
		set ready to waitForServer(48) -- ~12 detik
	end if
	if ready then
		openDashboard()
	else
		set msg to "Сервер Service Admin не отвечает." & return & return & "Если macOS показала запрос на доступ к папке «Документы» — нажмите «Разрешить» и откройте приложение снова." & return & "Журнал: ~/.service-admin/logs/server.err"
		set answer to button returned of (display dialog msg with title "Service Admin" buttons {"Закрыть", "Всё равно открыть в браузере"} default button "Закрыть" with icon caution)
		if answer is "Всё равно открыть в браузере" then openDashboard()
	end if
end run
