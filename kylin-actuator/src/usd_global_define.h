/* -*- Mode: C++; indent-tabs-mode: nil; tab-width: 4 -*-
 * -*- coding: utf-8 -*-
 *
 * Copyright (C) 2020 KylinSoft Co., Ltd.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef USD_GLOBAL_DEFINE_H
#define USD_GLOBAL_DEFINE_H

#define USD_BTN_PRESS   2
#define USD_BTN_RELEASE 3

/****dbus****/

/*com.kylin.statusmanager.interface*/
#define DBUS_STATUSMANAGER_NAME             "com.kylin.statusmanager.interface"
#define DBUS_STATUSMANAGER_PATH             "/"
#define DBUS_STATUSMANAGER_INTERFACE        "com.kylin.statusmanager.interface"
#define DBUS_STATUSMANAGER_GET_MODE         "get_current_tabletmode"
#define DBUS_STATUSMANAGER_GET_ROTATION     "get_current_rotation"
/*****/

/*org.ukui.SettingsDaemon.xrandr*/
#define DBUS_XRANDR_NAME                    "org.ukui.SettingsDaemon"
#define DBUS_XRANDR_PATH                    "/org/ukui/SettingsDaemon/xrandr"
#define DBUS_XRANDR_INTERFACE               "org.ukui.SettingsDaemon.xrandr"
#define DBUS_XRANDR_GET_MODE                "getScreenMode"
#define DBUS_XRANDR_SET_MODE                "setScreenMode"
#define DBUS_XRANDR_GET_SCREEN_PARAM        "getScreensParam"
/*****/

/*org.ukui.SettingsDaemon.gammaManager*/
#define DBUS_GM_NAME                    "org.ukui.SettingsDaemon"
#define DBUS_GM_PATH                    "/org/ukui/SettingsDaemon/GammaManager"
#define DBUS_GM_INTERFACE               "org.ukui.SettingsDaemon.GammaManager"
#define DBUS_GM_SCREENCHANGED           "screenBrightnessChanged"
/*****/

/*com.control.center.qt.systemdbus*/
#define DBUS_CONTROL_CENTER_NAME            "com.control.center.qt.systemdbus"
#define DBUS_CONTROL_CENTER_PATH            "/"
#define DBUS_CONTROL_CENTER_INTERFACE       "com.control.center.interface"
/*****/

/*com.settings.daemon.qt.systemdbus*/
#define SETTINGS_DAEMON_SYSTEMDBUS_NAME            "com.settings.daemon.qt.systemdbus"
#define SETTINGS_DAEMON_SYSTEMDBUS_PATH            "/"
#define SETTINGS_DAEMON_SYSTEMDBUS_INTERFACE       "com.settings.daemon.interface"
/**/

//dbus 配置
#define GNOME_SESSION_MANAGER               "org.gnome.SessionManager.Presence"
#define SESSION_MANAGER_PATH                "/org/gnome/SessionManager/Presence"



/**/
#define DBUS_GC_BRIGHTNESS_PATH                             "/GlobalBrightness"
#define DBUS_GC_BRIGHTNESS_INTERFACE                        "org.ukui.SettingsDaemon.Brightness"
#define DBUS_GC_BRIGHTNESS_SIGNAL_PRIMARYCHANGED_START      "primaryBrightnessChangedStart"
#define DBUS_GC_BRIGHTNESS_SIGNAL_PRIMARYCHANGED            "primaryBrightnessChanged"
#define DBUS_GC_BRIGHTNESS_SIGNAL_PRIMARYCHANGED_END        "primaryBrightnessChangedEnd"
#define DBUS_GC_BRIGHTNESS_SIGNAL_ENABLECHANGED             "enableChanged"


/**/
#define DBUS_GC_SIGNAL_PATH                         "/GlobaSignal"
#define DBUS_GC_SIGNAL_INTERFACE                    "org.ukui.SettingsDaemon.GlobalSignal"
#define DBUS_GC_SIGNAL_SIGNAL_Active                "Active"

//gsettings

/*com.kylin.statusmanager.interface*/
/****dbus end****/
#define MIN_GAMMA_BRIGHTNESS    0.35
#define MAX_GAMMA_BRIGHTNESS    0.65
/****gsettings****/
//ukui.style
#define UKUI_STYLE_SCHEMA                   "org.ukui.style"
#define SYSTEM_FONT_SIZE                    "system-font-size"
#define SYSTEM_FONT                         "system-font"

//MATE_INTERFACE
#define MATE_INTERFACE_SCHEMA "org.mate.interface"

//auto-brightness gsettings
#define AUTO_BRIGHTNESS_SCHEMA              "org.ukui.SettingsDaemon.plugins.auto-brightness"
#define AUTO_BRIGHTNESS_KEY                 "auto-brightness"
#define DYNAMIC_BRIGHTNESS_KEY              "dynamic-brightness"
#define HAD_SENSOR_KEY                      "have-sensor"
#define DEBUG_MODE_KEY                      "debug-mode"
#define DEBUG_LUX_KEY                       "debug-lux"
#define DELAYMS_KEY                         "delayms"

#define POWER_MANAGER_SCHEMA                "org.ukui.power-manager"
#define BRIGHTNESS_AC_KEY                   "brightness-ac"
/*Xorg shutkey name*/

//xsettings
#define GSETTINGS_XSETTINGS_SCHEMA          "org.ukui.SettingsDaemon.plugins.xsettings"
#define SCALING_FACTOR_KEY                  "scaling-factor"


//mouse
#define GSETTINGS_MOUSE_SCHEMA              "org.ukui.peripherals-mouse"
#define CURSOR_THEME_KEY                    "cursor-theme"
#define CURSOR_SIZE_KEY                     "cursor-size"


//xsettings
#define GSETTINGS_GLOBALMANAGER_SCHEMA          "org.ukui.SettingsDaemon.plugins.globalManager"
#define HIDE_POWEROFF_UI                        "disable-power-operation"
#define DISABLE_POWEROFF_OPTIONS                "disable-shutdown-option"
#define UKUI_LITE_FUNCTION_KEY                  "ukui-lite-function"
#define UKUI_LITE_ANIMATION_KEY                 "ukui-lite-animation"
#define UKUI_LITE_MODE                          "ukui-lite"

#define UKUI_LITE_FUNCTION                      "function"
#define UKUI_LITE_ANIMATION                     "animation"
/*
 * 变量
*/
#define MAX_SIZE_MATCH_DIFF         0.05

//session
#define SESSION_BUSY    0
#define SESSION_IDLE    3

#define LEFT_SHIFT 0x32
#define LEFT_CTRL   0x25
#define LEFT_ALT    0x40
#define RIGHT_SHIFT 0x3E
#define RIGHT_ALT 0x6C
#define RIGHT_CTRL 0x69
#define MATE_KEY 0x85

#define xEventHandleHadRelase(action)     bool action##HadRelease = false

#define xEventHandleRelease(action)       action##HadRelease = false;

#define xEventHandle(action) \
if (false == action##HadRelease) {  \
    doAction(action);   \
    action##HadRelease = true;  \
}

#define STATE_OFF     0
#define STATE_ON      1
#define STATE_TOGGLE  2

/*Xorg shutkey nameEnd*/


#define TIME_LIMIT(time) \
    static QTime startTime = QTime::currentTime();  \
    static int elapsed = -1;    \
    elapsed = startTime.msecsTo(QTime::currentTime());  \
    if(elapsed > 0 && elapsed <= time){  \
        /*USD_LOG(LOG_ERR,"time in TIME_LIMIT");*/    \
        return; \
    }   \
    startTime = QTime::currentTime();
#endif // USD_GLOBAL_DEFINE_H
