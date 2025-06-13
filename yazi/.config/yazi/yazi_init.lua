function Linemode:mtimev2() -- Custom modified time linemode that shows time in ISO format
    local time = math.floor(self._file.cha.modified or 0)
    if time > 0 then
        local time_format
        time_format = os.date("%Y-%m-%d %H:%M", time) -- With year
        return ui.Line(string.format(time_format))
    end
    return ui.Line("") -- Return empty if no time exists
end

function Linemode:ctimev2() -- Custom created time linemode that shows time in ISO format
    local time = math.floor(self._file.cha.created or 0)
    if time > 0 then
        local time_format
        time_format = os.date("%Y-%m-%d %H:%M", time) -- With year
        return ui.Line(string.format(time_format))
    end
    return ui.Line("") -- Return empty if no time exists
end
