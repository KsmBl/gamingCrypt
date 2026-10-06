-- GamingCrypt: touch controls for mpv, like YouTube on a phone.
--
--   tap               controls on / off (over a darkened picture)
--   double tap        left / right third: 10 s back / forward - every further tap there adds 10 s
--   hold              2x speed while the finger stays down
--   time bar          tap or drag to jump (the picture follows while dragging)
--
-- gamescope's click mode lets go of the "mouse button" as soon as a finger moves, but the
-- pointer keeps following the finger: a drag on the time bar goes on until the finger rests.
--   controls          ✕ (stop), speed, subtitles, audio language, 10 s back, play / pause, 10 s forward
--   speed             the "1x" button: a menu from 0.25x to 2x
--
-- GamingCrypt switches gamescope's touch to "left click" while a movie is in front: taps
-- arrive here as MBTN_LEFT down / up at the touched position. LuaJIT: no // operator.

local mp = require "mp"

local HIDE_S = 3
local DOUBLE_TAP_S = 0.3
local SEEK_STREAK_S = 0.8 -- further taps on that side keep seeking this long
local HOLD_S = 0.5
local SEEK_STEP = 10
local SPEEDS = {0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2}
local DRAG_REST_S = 0.35 -- a drag on the time bar ends when the finger rests this long
local ACCENT = "&HFF8C4F&" -- #4f8cff (ASS colours are BGR)
local WHITE = "&HFFFFFF&"

local overlay = mp.create_osd_overlay("ass-events")
local state = {
    shown = false, hide_timer = nil, tick = nil,
    buttons = {}, bar = nil,
    down = nil, -- {x, y, time, hold_timer, held, on_bar}
    scrub = nil, -- 0..1 while dragging on the bar
    dragging = false, -- the finger moved on the bar: following the pointer (see above)
    drag_timer = nil,
    last_seek_preview = 0,
    tap_timer = nil, last_tap = nil, -- for double taps
    streak = nil, -- {side, total, until}
    ripple = nil, -- {side, text, until}
    fast = false, speed_before = 1, -- holding: 2x, then back to the chosen speed
    menu = false, -- the speed menu is open
}

local function floor(x) return math.floor(x) end

local function speed_label(speed)
    return (string.format("%.2f", speed):gsub("0+$", ""):gsub("%.$", "")) .. "x"
end
local end_drag_later -- below

local function clock(seconds)
    seconds = floor(math.max(0, seconds or 0))
    local h, m, s = floor(seconds / 3600), floor(seconds / 60) % 60, seconds % 60
    if h > 0 then return string.format("%d:%02d:%02d", h, m, s) end
    return string.format("%d:%02d", m, s)
end

-- drawing ---------------------------------------------------------------------------------
local function shape(color, alpha, path)
    return string.format("{\\an7\\pos(0,0)\\bord0\\shad0\\1c%s\\1a&H%s&\\p1}%s{\\p0}", color, alpha, path)
end

local function rect(x1, y1, x2, y2, color, alpha)
    return shape(color, alpha, string.format("m %d %d l %d %d l %d %d l %d %d",
        floor(x1), floor(y1), floor(x2), floor(y1), floor(x2), floor(y2), floor(x1), floor(y2)))
end

local function circle(cx, cy, r, color, alpha)
    local k = r * 0.5523
    local p = {cx, cy - r, cx + k, cy - r, cx + r, cy - k, cx + r, cy, cx + r, cy + k, cx + k, cy + r, cx, cy + r,
        cx - k, cy + r, cx - r, cy + k, cx - r, cy, cx - r, cy - k, cx - k, cy - r, cx, cy - r}
    for i = 1, #p do p[i] = floor(p[i]) end
    return shape(color, alpha, string.format(
        "m %d %d b %d %d %d %d %d %d b %d %d %d %d %d %d b %d %d %d %d %d %d b %d %d %d %d %d %d", unpack(p)))
end

local function text(x, y, size, s, align, color)
    return string.format("{\\an%d\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\1c%s\\3c&H000000&\\b1}%s",
        align or 5, floor(x), floor(y), floor(size), color or WHITE, s)
end

local function play_icon(cx, cy, r)
    return shape(WHITE, "00", string.format("m %d %d l %d %d l %d %d",
        floor(cx - r * 0.35), floor(cy - r * 0.5), floor(cx + r * 0.55), floor(cy), floor(cx - r * 0.35),
        floor(cy + r * 0.5)))
end

local function pause_icon(cx, cy, r)
    local w, h = r * 0.22, r * 0.5
    return rect(cx - r * 0.38, cy - h, cx - r * 0.38 + w, cy + h, WHITE, "00") .. "\n"
        .. rect(cx + r * 0.38 - w, cy - h, cx + r * 0.38, cy + h, WHITE, "00")
end

local function geometry()
    local w, h = mp.get_osd_size()
    if not w or w == 0 then return nil end
    local unit = floor(math.min(w, h) / 9)
    return w, h, unit
end

local function draw()
    local w, h, unit = geometry()
    if not w then return end
    overlay.res_x, overlay.res_y = w, h
    local now = mp.get_time()
    local out = {}
    state.buttons, state.bar = {}, nil
    local function add(s) out[#out + 1] = s end
    local function button(x1, y1, x2, y2, action)
        state.buttons[#state.buttons + 1] = {x1, y1, x2, y2, action}
    end

    if state.shown then
        add(rect(0, 0, w, h, "&H000000&", "90")) -- the picture darkened, like YouTube
        local margin = floor(unit * 0.45)
        -- top: close, title, subtitles, audio
        local top = floor(unit * 0.6)
        add(text(margin + unit * 0.3, top, unit * 0.55, "✕"))
        button(0, 0, margin + unit * 0.9, unit * 1.2, function() mp.commandv("quit") end)
        add(text(margin + unit * 1.0, top, unit * 0.4, mp.get_property("media-title", ""), 4))
        local function pill(x2, label, action)
            local pw = floor(unit * 1.7)
            add(rect(x2 - pw, top - unit * 0.38, x2, top + unit * 0.38, "&H000000&", "60"))
            add(text(x2 - pw / 2, top, unit * 0.32, label))
            button(x2 - pw - unit * 0.1, 0, x2 + unit * 0.1, unit * 1.2, action)
            return x2 - pw - floor(unit * 0.25)
        end
        local x = pill(w - margin, "Audio", function()
            mp.commandv("cycle", "audio")
            mp.osd_message("Audio: " .. (mp.get_property("current-tracks/audio/lang")
                or mp.get_property("aid", "")), 2)
        end)
        x = pill(x, "Subtitles", function()
            mp.commandv("cycle", "sub")
            mp.osd_message("Subtitles: " .. (mp.get_property("current-tracks/sub/lang")
                or mp.get_property("sid", "off")), 2)
        end)
        pill(x, speed_label(mp.get_property_number("speed", 1)), function() state.menu = not state.menu end)
        if state.menu then
            -- the speed menu instead of the middle buttons
            local current = mp.get_property_number("speed", 1)
            local bw, bh, gap = floor(unit * 1.25), floor(unit * 1.0), floor(unit * 0.2)
            local total = #SPEEDS * bw + (#SPEEDS - 1) * gap
            local x1, cy = floor((w - total) / 2), floor(h / 2)
            add(rect(x1 - gap * 2, cy - bh - unit * 0.3, x1 + total + gap * 2, cy + bh * 0.5 + gap * 2,
                "&H000000&", "50"))
            add(text(w / 2, cy - bh * 0.5 - unit * 0.25, unit * 0.36, "Playback speed"))
            for i, speed in ipairs(SPEEDS) do
                local bx = x1 + (i - 1) * (bw + gap)
                local chosen = math.abs(speed - current) < 0.001
                add(rect(bx, cy, bx + bw, cy + bh * 0.9, chosen and ACCENT or "&H382A25&", "00"))
                add(text(bx + bw / 2, cy + bh * 0.45, unit * 0.32, speed_label(speed)))
                button(bx, cy - gap, bx + bw, cy + bh, function()
                    mp.set_property_number("speed", speed)
                    state.speed_before = speed
                    state.menu = false
                    mp.osd_message("Speed " .. speed_label(speed), 1)
                end)
            end
        end
        -- middle: 10 s back, play / pause, 10 s forward
        local cx, cy, r = floor(w / 2), floor(h / 2), floor(unit * 0.8)
        local gap = floor(unit * 2.6)
        if state.menu then goto middle_done end
        add(circle(cx, cy, r, "&H000000&", "70"))
        if mp.get_property_bool("pause", false) then add(play_icon(cx, cy, r)) else add(pause_icon(cx, cy, r)) end
        button(cx - r, cy - r, cx + r, cy + r, function() mp.commandv("cycle", "pause") end)
        for _, side in ipairs({-1, 1}) do
            local sx = cx + side * gap
            add(circle(sx, cy, floor(r * 0.75), "&H000000&", "70"))
            add(text(sx, cy, unit * 0.36, side < 0 and "« 10" or "10 »"))
            button(sx - r, cy - r, sx + r, cy + r, function() mp.commandv("seek", tostring(side * SEEK_STEP)) end)
        end
        ::middle_done::
    end

    -- the time bar: shown with the controls and while dragging
    if state.shown or state.scrub then
        local pos = mp.get_property_number("time-pos", 0)
        local length = mp.get_property_number("duration", 0)
        local fraction = state.scrub or (length > 0 and pos / length or 0)
        local margin = floor(unit * 0.45)
        local x1, x2 = margin, w - margin
        local y = h - floor(unit * 0.55)
        local thick = state.scrub and floor(unit * 0.09) or floor(unit * 0.06)
        add(rect(x1, y - thick, x2, y + thick, WHITE, "B0"))
        local done = x1 + floor((x2 - x1) * math.max(0, math.min(1, fraction)))
        add(rect(x1, y - thick, done, y + thick, ACCENT, "00"))
        add(circle(done, y, floor(unit * (state.scrub and 0.22 or 0.15)), ACCENT, "00"))
        local shown_time = state.scrub and (fraction * length) or pos
        add(text(margin, y - unit * 0.55, unit * 0.34, clock(shown_time) .. " / " .. clock(length), 4))
        state.bar = {x1, y - unit * 0.6, x2, h}
    end

    -- double tap feedback: which way and how far
    if state.ripple and now < state.ripple["until"] then
        local rx = state.ripple.side < 0 and floor(w * 0.17) or floor(w * 0.83)
        add(circle(rx, floor(h / 2), floor(unit * 1.4), WHITE, "D0"))
        add(text(rx, floor(h / 2), unit * 0.42, state.ripple.text))
    end
    if state.fast then
        add(rect(w / 2 - unit * 0.9, unit * 0.3, w / 2 + unit * 0.9, unit * 0.95, "&H000000&", "60"))
        add(text(w / 2, unit * 0.62, unit * 0.36, "2x  ▶▶"))
    end
    if #out == 0 then
        overlay:remove()
    else
        overlay.data = table.concat(out, "\n")
        overlay:update()
    end
end

-- showing / hiding ---------------------------------------------------------------------------
local function ensure_tick()
    if state.tick == nil then
        state.tick = mp.add_periodic_timer(0.25, function()
            local busy = state.shown or state.scrub or state.fast
                or (state.ripple and mp.get_time() < state.ripple["until"])
            draw()
            if not busy then
                state.tick:kill()
                state.tick = nil
            end
        end)
    end
end

local function hide()
    state.shown, state.menu = false, false
    if state.hide_timer then state.hide_timer:kill() end
    draw()
end

local function keep_shown()
    if state.hide_timer then state.hide_timer:kill() end
    state.hide_timer = mp.add_timeout(HIDE_S, function()
        if mp.get_property_bool("pause", false) or state.scrub or state.menu then
            keep_shown() -- paused: the controls stay, like YouTube
        else
            hide()
        end
    end)
end

local function show()
    state.shown = true
    draw()
    ensure_tick()
    keep_shown()
end

local function toggle()
    if state.shown then hide() else show() end
end

-- touch -------------------------------------------------------------------------------------
local function mouse()
    local pos = mp.get_property_native("mouse-pos") or {}
    return pos.x or 0, pos.y or 0
end

local function inside(box, x, y)
    return box ~= nil and x >= box[1] and x <= box[3] and y >= box[2] and y <= box[4]
end

local function side_of(x)
    local w = geometry()
    if not w then return 0 end
    if x < w / 3 then return -1 end
    if x > w * 2 / 3 then return 1 end
    return 0
end

local function bar_fraction(x)
    local bar = state.bar
    return math.max(0, math.min(1, (x - bar[1]) / math.max(1, bar[3] - bar[1])))
end

local function seek_side(side)
    local now = mp.get_time()
    local streak = state.streak
    if streak and streak.side == side and now < streak["until"] then
        streak.total = streak.total + SEEK_STEP
    else
        streak = {side = side, total = SEEK_STEP}
        state.streak = streak
    end
    streak["until"] = now + SEEK_STREAK_S
    mp.commandv("seek", tostring(side * SEEK_STEP))
    state.ripple = {side = side, ["until"] = now + SEEK_STREAK_S,
        text = (side < 0 and "« " or "") .. streak.total .. " s" .. (side > 0 and " »" or "")}
    draw()
    ensure_tick()
end

local function tapped(x, y)
    -- a control (they're only there while shown)
    if state.shown then
        for _, b in ipairs(state.buttons) do
            if inside(b, x, y) then
                b[5]()
                show()
                return
            end
        end
        if state.menu then -- outside the menu: just close it
            state.menu = false
            show()
            return
        end
    end
    local side = side_of(x)
    local now = mp.get_time()
    if side ~= 0 then
        local streak = state.streak
        if streak and streak.side == side and now < streak["until"] then
            seek_side(side) -- keeps going: 20 s, 30 s, …
            return
        end
        local last = state.last_tap
        if last and last.side == side and now - last.time < DOUBLE_TAP_S then
            if state.tap_timer then state.tap_timer:kill() end
            state.last_tap = nil
            if state.shown then hide() end
            seek_side(side)
            return
        end
        -- maybe the first of two: wait a moment before showing / hiding the controls
        state.last_tap = {side = side, time = now}
        if state.tap_timer then state.tap_timer:kill() end
        state.tap_timer = mp.add_timeout(DOUBLE_TAP_S, function()
            state.last_tap = nil
            toggle()
        end)
        return
    end
    toggle()
end

local function end_scrub()
    if state.drag_timer then state.drag_timer:kill() end
    local fraction = state.scrub or 0
    state.scrub, state.dragging = nil, false
    mp.commandv("seek", tostring(fraction * 100), "absolute-percent", "exact")
    if state.shown then show() else draw() end
end

end_drag_later = function()
    if state.drag_timer then state.drag_timer:kill() end
    state.drag_timer = mp.add_timeout(DRAG_REST_S, end_scrub)
end

local function finger(event)
    if event.event == "down" then
        if state.dragging then end_scrub() end
        local x, y = mouse()
        local down = {x = x, y = y, time = mp.get_time(), held = false, on_bar = inside(state.bar, x, y)}
        state.down = down
        if down.on_bar then
            state.scrub = bar_fraction(x)
            draw()
            ensure_tick()
            return
        end
        down.hold_timer = mp.add_timeout(HOLD_S, function()
            if state.down == down then -- still pressed: fast forward like YouTube
                down.held = true
                state.fast = true
                state.speed_before = mp.get_property_number("speed", 1)
                mp.set_property_number("speed", 2)
                draw()
                ensure_tick()
            end
        end)
    elseif event.event == "up" then
        local down = state.down
        state.down = nil
        if down == nil then return end
        if down.hold_timer then down.hold_timer:kill() end
        if state.scrub then
            local x, y = mouse()
            if (x - down.x) * (x - down.x) + (y - down.y) * (y - down.y) > 100 then
                state.dragging = true -- moved: follow the finger until it rests
                end_drag_later()
            else
                end_scrub()
            end
            return
        end
        if down.held then
            state.fast = false
            mp.set_property_number("speed", state.speed_before)
            draw()
            return
        end
        tapped(mouse())
    end
end

mp.add_forced_key_binding("MBTN_LEFT", "gamingcrypt-finger", finger, {complex = true})
mp.add_forced_key_binding("MBTN_LEFT_DBL", "gamingcrypt-no-fullscreen-toggle", function() end)
mp.observe_property("mouse-pos", "native", function(_, pos)
    local down = state.down
    if pos == nil or (down == nil and not state.dragging) then return end
    if state.scrub and state.bar then
        state.scrub = bar_fraction(pos.x)
        if state.dragging then end_drag_later() end
        local now = mp.get_time()
        if now - state.last_seek_preview > 0.15 then -- the picture follows the finger
            state.last_seek_preview = now
            mp.commandv("seek", tostring(state.scrub * 100), "absolute-percent", "keyframes")
        end
        draw()
    elseif down and not down.held and down.hold_timer then
        local dx, dy = pos.x - down.x, pos.y - down.y
        if dx * dx + dy * dy > 900 then down.hold_timer:kill() end -- moved: not a hold
    end
end)
mp.observe_property("pause", "bool", function()
    if state.shown then draw() end
end)
mp.observe_property("osd-dimensions", "native", function()
    if state.shown then draw() end
end)
mp.register_script_message("gamingcrypt-show-controls", show)
