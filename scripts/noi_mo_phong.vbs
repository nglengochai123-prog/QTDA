Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c """ & Replace(WScript.ScriptFullName, "noi_mo_phong.vbs", "noi_mo_phong.cmd") & """", 0, True
