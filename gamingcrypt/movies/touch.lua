-- GamingCrypt: touch controls for mpv (instead of mpv's small on-screen controller).
--
-- Tap the picture: the controls show (again: they hide). Double tap the left / right half:
-- 10 s back / forward. Controls: the time bar (tap to jump there), back 10 s, play / pause,
-- forward 30 s, subtitles, audio language, stop. They hide after a few seconds of playing.

local mp = require "mp"

local HIDE_S = 4
local DOUBLE_TAP_S = 0.35
local BACKGROUND = "&H000000&"
local ACCENT = "&HFF8C4F&" -- #4f8cff as BGR
local TEXT = "&HF0EAE8&"

local overlay = mp.create_osd_overlay("ass-events")
local shown = false
local hide_timer = nil
local tick = nil
local buttons = {} -- {x1, y1, x2, y2, action}
local bar = nil -- {x1, y1, x2, y2}
local last_tap = {time = 0, side = nil}

local function rect(x1, y1, x2, y2, color, alpha)
    return string.format("{\\an7\\pos(0,0)\\bord0\\shad0\\1c%s\\1a&H%s&\\p1}m %d %d l %d %d l %d %d l %d %d{\\p0}",
        color, alpha, x1, y1, x2, y1, x2, y2, x1, y2)
end

local function text(x, y, size, s, align)
    return string.format("{\\an%d\\pos(%d,%d)\\fs%d\\bord2\\shad0\\1c%s\\3c&H000000&}%s",
        align or 5, x, y, size, TEXT, s)
end

local function clock(seconds)
    seconds = math.max(0, math.floor(seconds or 0))
    return string.format("%d:%02d:%02d", math.floor(seconds / 3600), math.floor(seconds / 60) % 60, seconds % 60)
end

local function draw()
    if not shown then
        overlay:remove()
        return
    end
    local w, h = mp.get_osd_size()
    if not w or w == 0 then
        return
    end
    overlay.res_x, overlay.res_y = w, h
    local unit = math.floor(math.min(w, h) / 9) -- button height: fingers, not mouse pointers
    local panel = math.floor(unit * 2.6)
    local out = {}
    buttons = {}
    -- top: the title
    out[#out + 1] = rect(0, 0, w, math.floor(unit * 0.9), BACKGROUND, "60")
    out[#out + 1] = text(math.floor(unit * 0.4), math.floor(unit * 0.45), math.floor(unit * 0.42),
        mp.get_property("media-title", ""), 4)
    -- bottom panel
    out[#out + 1] = rect(0, h - panel, w, h, BACKGROUND, "50")
    local pos = mp.get_property_number("time-pos", 0)
    local length = mp.get_property_number("duration", 0)
    local margin = math.floor(unit * 0.5)
    local bar_y = h - panel + math.floor(unit * 0.55)
    local bar_h = math.max(8, math.floor(unit * 0.14))
    local x1, x2 = margin + math.floor(unit * 1.6), w - margin - math.floor(unit * 1.6)
    out[#out + 1] = rect(x1, bar_y - math.floor(bar_h / 2), x2, bar_y + math.floor(bar_h / 2), TEXT, "A0")
    if length > 0 then
        local done = x1 + math.floor((x2 - x1) * math.min(1, pos / length))
        out[#out + 1] = rect(x1, bar_y - math.floor(bar_h / 2), done, bar_y + math.floor(bar_h / 2), ACCENT, "00")
        out[#out + 1] = rect(done - bar_h, bar_y - bar_h, done + bar_h, bar_y + bar_h, ACCENT, "00")
    end
    out[#out + 1] = text(margin, bar_y, math.floor(unit * 0.36), clock(pos), 4)
    out[#out + 1] = text(w - margin, bar_y, math.floor(unit * 0.36), clock(length), 6)
    bar = {x1, bar_y - math.floor(unit / 2), x2, bar_y + math.floor(unit / 2)} -- a finger-high touch zone
    -- the buttons
    local row_y = h - math.floor(unit * 0.95)
    local bw, bh, gap = math.floor(unit * 1.5), math.floor(unit * 1.1), math.floor(unit * 0.3)
    local function button(cx, label, action, size)
        local bx1, by1 = cx - math.floor(bw / 2), row_y - math.floor(bh / 2)
        out[#out + 1] = rect(bx1, by1, bx1 + bw, by1 + bh, "&H382A25&", "20")
        out[#out + 1] = text(cx, row_y, math.floor(unit * (size or 0.38)), label)
        buttons[#buttons + 1] = {bx1, by1, bx1 + bw, by1 + bh, action}
    end
    local cx = math.floor(w / 2)
    local paused = mp.get_property_bool("pause", false)
    button(cx - bw - gap, "« 10 s", function() mp.commandv("seek", "-10") end)
    button(cx, paused and "▶ Play" or "❚❚ Pause", function() mp.commandv("cycle", "pause") end, 0.42)
    button(cx + bw + gap, "30 s »", function() mp.commandv("seek", "30") end)
    button(margin + math.floor(bw / 2), "✕ Stop", function() mp.commandv("quit") end)
    button(w - margin - math.floor(bw / 2) - bw - gap, "Subtitles", function()
        mp.commandv("cycle", "sub")
        mp.osd_message("Subtitles: " .. (mp.get_property("current-tracks/sub/lang") or
            mp.get_property("sub", "no")), 2)
    end, 0.32)
    button(w - margin - math.floor(bw / 2), "Audio", function()
        mp.commandv("cycle", "audio")
        mp.osd_message("Audio: " .. (mp.get_property("current-tracks/audio/lang") or
            mp.get_property("aid", "")), 2)
    end, 0.32)
    overlay.data = table.concat(out, "\n")
    overlay:update()
end

local function hide()
    shown = false
    if tick then tick:kill() end
    draw()
end

local function keep_shown()
    if hide_timer then hide_timer:kill() end
    hide_timer = mp.add_timeout(HIDE_S, function()
        if mp.get_property_bool("pause", false) then
            keep_shown() -- paused: the controls stay
        else
            hide()
        end
    end)
end

local function show()
    shown = true
    draw()
    if tick then tick:kill() end
    tick = mp.add_periodic_timer(0.5, draw)
    keep_shown()
end

local function inside(box, x, y)
    return box and x >= box[1] and x <= box[3] and y >= box[2] and y <= box[4]
end

local function tap()
    local mouse = mp.get_property_native("mouse-pos") or {}
    local x, y = mouse.x or 0, mouse.y or 0
    if shown then
        for _, b in ipairs(buttons) do
            if inside(b, x, y) then
                b[5]()
                if shown then show() end
                return
            end
        end
        if inside(bar, x, y) then
            local fraction = (x - bar[1]) / math.max(1, bar[3] - bar[1])
            mp.commandv("seek", tostring(math.max(0, math.min(100, fraction * 100))), "absolute-percent")
            show()
            return
        end
    end
    local w = mp.get_osd_size()
    local side = (x < (w or 0) / 2) and "left" or "right"
    local now = mp.get_time()
    if now - last_tap.time < DOUBLE_TAP_S and last_tap.side == side then
        mp.commandv("seek", side == "left" and "-10" or "10")
        mp.osd_message(side == "left" and "« 10 s" or "10 s »", 1)
        last_tap.time = 0
        return
    end
    last_tap = {time = now, side = side}
    if shown then hide() else show() end
end

mp.add_forced_key_binding("MBTN_LEFT", "gamingcrypt-tap", tap)
mp.add_forced_key_binding("MBTN_LEFT_DBL", "gamingcrypt-tap-double", function() end)
mp.observe_property("pause", "bool", function()
    if shown then draw() end
end)
mp.observe_property("osd-dimensions", "native", function()
    if shown then draw() end
end)
mp.register_script_message("gamingcrypt-show-controls", show)
