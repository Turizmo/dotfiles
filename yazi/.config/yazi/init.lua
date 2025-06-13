-- ~/.config/yazi/init.lua
function Linemode:mtimev2()
	local time = math.floor(self._file.cha.mtime or 0)
	if time == 0 then
		time = ""
	else
		time = os.date("%Y-%m-%d %H:%M", time)
	end

	local size = self._file:size()
	return string.format("%s", time)
end
