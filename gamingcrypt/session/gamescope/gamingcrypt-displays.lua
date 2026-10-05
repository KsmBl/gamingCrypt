-- GamingCrypt: refresh rates for handheld panels gamescope has no profile for, so the
-- screen can follow a game's frame rate (a 50 Hz PAL game on a 60 Hz screen stutters:
-- every fifth frame is shown twice). Copied to ~/.config/gamescope by install.sh.

local function rates(low, high)
    local list = {}
    for hz = low, high do
        table.insert(list, hz)
    end
    return list
end

-- same timings as the panel's own mode, only the pixel clock follows the refresh rate
local function slower_clock(base_mode, refresh)
    local mode = base_mode
    mode.clock = gamescope.modegen.calc_max_clock(mode, refresh)
    mode.vrefresh = gamescope.modegen.calc_vrefresh(mode)
    return mode
end

-- AYANEO 2021 / 2021 Pro: 800 x 1280 LCD, 60 Hz
gamescope.config.known_displays.gamingcrypt_ayaneo_2021_lcd = {
    pretty_name = "AYANEO 2021 LCD",
    dynamic_refresh_rates = rates(40, 60),
    dynamic_modegen = function(base_mode, refresh)
        debug("[gamingcrypt] "..refresh.." Hz for the AYANEO 2021 LCD")
        return slower_clock(base_mode, refresh)
    end,
    matches = function(display)
        if display.vendor == "UGD" and display.product == 0x1003 then
            debug("[gamingcrypt] matched the AYANEO 2021 LCD")
            return 4000
        end
        return -1
    end
}
