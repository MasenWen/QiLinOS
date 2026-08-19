"""官方 SDK 全量绑定（自动生成 v2）— declare-only，restype 从文档原型精确解析
安全设计：只 declare 不调用；调用前请核对返回类型（错误 restype 会崩溃）
用法: from src.sdk.official_bind import _lib_xxx, BOUND_LIBS
"""
from __future__ import annotations
import ctypes as _c
from .base import load_library, declare

BOUND_LIBS: dict[str, object] = {}
BOUND_FUNCS: dict[str, str] = {}   # 接口名 -> 库名

_lib_battery = load_library("libkybattery", mock=False)
if _lib_battery is not None:
    BOUND_LIBS["libkybattery"] = _lib_battery
    try:
        declare(_lib_battery, "kdk_battery_get_capacity_level", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_battery_get_capacity_level"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_get_charge_state", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_battery_get_charge_state"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_get_health_state", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_battery_get_health_state"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_get_plugged_type", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_battery_get_plugged_type"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_get_soc", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_battery_get_soc"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_get_technology", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_battery_get_technology"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_get_temperature", restype=_c.c_float)
        BOUND_FUNCS["kdk_battery_get_temperature"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_get_voltage", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_battery_get_voltage"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_battery, "kdk_battery_is_present", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_battery_is_present"] = "libkybattery"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_bluetooth = load_library("libkybluetooth", mock=False)
if _lib_bluetooth is not None:
    BOUND_LIBS["libkybluetooth"] = _lib_bluetooth
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_address", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_address"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_alcmtu", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_alcmtu"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_bus", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_bus"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_dev_version", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_dev_version"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_device_id", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_bluetooth_get_device_id"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_features", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_features"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_link_mode", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_link_mode"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_link_policy", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_link_policy"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_manufacturer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_manufacturer"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_name", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_name"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_packettype", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_packettype"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_bluetooth, "kdk_bluetooth_get_scomtu", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bluetooth_get_scomtu"] = "libkybluetooth"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_date = load_library("libkydate", mock=False)
if _lib_date is not None:
    BOUND_LIBS["libkydate"] = _lib_date
    try:
        declare(_lib_date, "kdk_date_freeall", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_date_freeall"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_dateformat", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_dateformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_eUser_login_time", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_eUser_login_time"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_longformat", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_longformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_longformat_date", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_longformat_date"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_now_dateformat", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_now_dateformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_now_timeformat", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_now_timeformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_shortformat", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_shortformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_shortformat_date", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_shortformat_date"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_shutdown_time", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_shutdown_time"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_get_startup_time", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_startup_time"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_gjx_time", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_gjx_time"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_login_lock_dateinfo", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_login_lock_dateinfo"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_logn_dateinfo", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_logn_dateinfo"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_longformat_transform", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_longformat_transform"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_longweek", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_longweek"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_nowdate", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_nowdate"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_nowtime", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_nowtime"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_second", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_second"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_set_12_timeformat", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_set_12_timeformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_set_24_timeformat", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_set_24_timeformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_set_dateformat", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_set_dateformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_set_long_dateformat", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_set_long_dateformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_set_short_dateformat", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_set_short_dateformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_shortformat_transform", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_shortformat_transform"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_shortweek", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_shortweek"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_timeformat_transform", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_timeformat_transform"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_tran_absolute_date", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_tran_absolute_date"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_tran_absolute_date_longformat", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_tran_absolute_date_longformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_date, "kdk_system_tran_dateformat", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_tran_dateformat"] = "libkydate"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_diskinfo = load_library("libkydiskinfo", mock=False)
if _lib_diskinfo is not None:
    BOUND_LIBS["libkydiskinfo"] = _lib_diskinfo
    try:
        declare(_lib_diskinfo, "kdk_disk_delete_all_partitions", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_disk_delete_all_partitions"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_delete_partition", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_disk_delete_partition"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_get_disk_geometry", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_disk_get_disk_geometry"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_get_mount_point", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_disk_get_mount_point"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_get_partition_end_sector", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_disk_get_partition_end_sector"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_get_partition_start_sector", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_disk_get_partition_start_sector"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_get_partition_table_type", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_disk_get_partition_table_type"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_get_total_tracks", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_disk_get_total_tracks"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_get_volume_label", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_disk_get_volume_label"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_is_disk_writable", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_disk_is_disk_writable"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_mount_partition", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_disk_mount_partition"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_sync", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_disk_sync"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_type", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_disk_type"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_diskinfo, "kdk_disk_unmount_partition", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_disk_unmount_partition"] = "libkydiskinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_edid = load_library("libkyedid", mock=False)
if _lib_edid is not None:
    BOUND_LIBS["libkyedid"] = _lib_edid
    try:
        declare(_lib_edid, "kdk_edid_freeall", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_freeall"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_blue_primary", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_get_blue_primary"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_character", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_character"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_current_brightness", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_get_current_brightness"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_gamma", restype=_c.c_float)
        BOUND_FUNCS["kdk_edid_get_gamma"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_green_primary", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_get_green_primary"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_interface", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_get_interface"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_manufacturer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_manufacturer"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_max_brightness", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_get_max_brightness"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_max_resolution", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_max_resolution"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_model", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_model"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_primary", restype=_c.c_int)
        BOUND_FUNCS["kdk_edid_get_primary"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_ratio", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_ratio"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_rawDpiX", restype=_c.c_float)
        BOUND_FUNCS["kdk_edid_get_rawDpiX"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_rawDpiY", restype=_c.c_float)
        BOUND_FUNCS["kdk_edid_get_rawDpiY"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_red_primary", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_get_red_primary"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_refreshRate", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_refreshRate"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_resolution", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_resolution"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_rotation", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_rotation"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_serialNumber", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_serialNumber"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_size", restype=_c.c_float)
        BOUND_FUNCS["kdk_edid_get_size"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_visible_area", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_edid_get_visible_area"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_week", restype=_c.c_int)
        BOUND_FUNCS["kdk_edid_get_week"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_white_primary", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_edid_get_white_primary"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_get_year", restype=_c.c_int)
        BOUND_FUNCS["kdk_edid_get_year"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_edid, "kdk_edid_set_resolution", restype=_c.c_int)
        BOUND_FUNCS["kdk_edid_set_resolution"] = "libkyedid"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_fan = load_library("libkyfan", mock=False)
if _lib_fan is not None:
    BOUND_LIBS["libkyfan"] = _lib_fan
    try:
        declare(_lib_fan, "kdk_fan_freeall", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_fan_freeall"] = "libkyfan"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_fan, "kdk_fan_get_information", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_fan_get_information"] = "libkyfan"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_global = load_library("libkyglobal", mock=False)
if _lib_global is not None:
    BOUND_LIBS["libkyglobal"] = _lib_global
    try:
        declare(_lib_global, "kdk_global_get_raw_offset", restype=_c.c_int)
        BOUND_FUNCS["kdk_global_get_raw_offset"] = "libkyglobal"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_global, "kdk_global_get_region_match_language", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_global_get_region_match_language"] = "libkyglobal"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_global, "kdk_global_get_rtl", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_global_get_rtl"] = "libkyglobal"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_global, "kdk_global_get_system_language", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_global_get_system_language"] = "libkyglobal"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_global, "kdk_global_get_system_support_language", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_global_get_system_support_language"] = "libkyglobal"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_hw = load_library("libkyhw", mock=False)
if _lib_hw is not None:
    BOUND_LIBS["libkyhw"] = _lib_hw
    try:
        declare(_lib_hw, "kdk_bios_free", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_bios_free"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_bios_get_date", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bios_get_date"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_bios_get_smbios_version", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bios_get_smbios_version"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_bios_get_type", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bios_get_type"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_bios_get_vendor", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bios_get_vendor"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_bios_get_version", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_bios_get_version"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_board_free", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_board_free"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_board_get_date", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_board_get_date"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_board_get_name", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_board_get_name"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_board_get_serial", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_board_get_serial"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_board_get_vendor", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_board_get_vendor"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_L1d_cache", restype=_c.c_int)
        BOUND_FUNCS["kdk_cpu_get_L1d_cache"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_L1i_cache", restype=_c.c_int)
        BOUND_FUNCS["kdk_cpu_get_L1i_cache"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_L2_cache", restype=_c.c_int)
        BOUND_FUNCS["kdk_cpu_get_L2_cache"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_L3_cache", restype=_c.c_int)
        BOUND_FUNCS["kdk_cpu_get_L3_cache"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_arch", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_cpu_get_arch"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_corenums", restype=_c.c_int)
        BOUND_FUNCS["kdk_cpu_get_corenums"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_freq_MHz", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_cpu_get_freq_MHz"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_max_freq_MHz", restype=_c.c_float)
        BOUND_FUNCS["kdk_cpu_get_max_freq_MHz"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_min_freq_MHz", restype=_c.c_float)
        BOUND_FUNCS["kdk_cpu_get_min_freq_MHz"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_model", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_cpu_get_model"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_process", restype=_c.c_int)
        BOUND_FUNCS["kdk_cpu_get_process"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_running_time", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_cpu_get_running_time"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_sockets", restype=_c.c_int)
        BOUND_FUNCS["kdk_cpu_get_sockets"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_vendor", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_cpu_get_vendor"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_hw, "kdk_cpu_get_virt", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_cpu_get_virt"] = "libkyhw"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_location = load_library("libkylocation", mock=False)
if _lib_location is not None:
    BOUND_LIBS["libkylocation"] = _lib_location
    try:
        declare(_lib_location, "kdk_location_get", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_location_get"] = "libkylocation"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_netinfo = load_library("libkynetinfo", mock=False)
if _lib_netinfo is not None:
    BOUND_LIBS["libkynetinfo"] = _lib_netinfo
    try:
        declare(_lib_netinfo, "kdk_net_free_chain", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_free_chain"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_free_route", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_free_route"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_freeall", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_freeall"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_addr_by_name", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_get_addr_by_name"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_hosts", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_hosts"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_hosts_domain", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_hosts_domain"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_iptable_rules", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_get_iptable_rules"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_ipv4_dhcp_config", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_ipv4_dhcp_config"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_ipv6_dhcp_config", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_ipv6_dhcp_config"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_link_ncNmae", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_get_link_ncNmae"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_link_status", restype=_c.c_int)
        BOUND_FUNCS["kdk_net_get_link_status"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_link_type", restype=_c.c_int)
        BOUND_FUNCS["kdk_net_get_link_type"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_multiple_port_stat", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_multiple_port_stat"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_name_by_addr", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_name_by_addr"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_netmask", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_get_netmask"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_port_stat", restype=_c.c_int)
        BOUND_FUNCS["kdk_net_get_port_stat"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_primary_conType", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_primary_conType"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_proc_port", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_proc_port"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_resolv_conf", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_get_resolv_conf"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_route", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_net_get_route"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_up_port", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_up_port"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_wifi_channel", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_wifi_channel"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_wifi_freq", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_wifi_freq"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_wifi_mode", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_wifi_mode"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_wifi_rate", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_wifi_rate"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_netinfo, "kdk_net_get_wifi_sens", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_net_get_wifi_sens"] = "libkynetinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_package = load_library("libkypackage", mock=False)
if _lib_package is not None:
    BOUND_LIBS["libkypackage"] = _lib_package
    try:
        declare(_lib_package, "kdk_package_cmd_close", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_cmd_close"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_cmd_init", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_cmd_init"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_free_app_info", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_free_app_info"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_free_cmd", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_free_cmd"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_free_packagelist", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_free_packagelist"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_free_startmenu_list", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_free_startmenu_list"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_application_list", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_get_application_list"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_code_path", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_code_path"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_audio_player", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_audio_player"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_browser", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_browser"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_excel_viewer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_excel_viewer"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_image_viewer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_image_viewer"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_pdf_viewer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_pdf_viewer"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_ppt_viewer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_ppt_viewer"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_video_player", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_video_player"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_default_word_viewer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_default_word_viewer"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_description", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_description"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_file_count", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_get_file_count"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_installation_method", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_installation_method"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_name", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_name"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_packagelist", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_get_packagelist"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_standard_path", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_standard_path"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_standard_path_lists", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_standard_path_lists"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_startmenu_list", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_get_startmenu_list"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_get_version", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_package_get_version"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_install_package", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_install_package"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_install_package_offline", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_install_package_offline"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_install_package_online", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_install_package_online"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_is_installed", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_is_installed"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_is_removable", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_is_removable"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_is_removable_by_desktop", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_is_removable_by_desktop"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_launch_cmd", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_launch_cmd"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_list", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_list"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_list_files", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_list_files"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_remove_package", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_remove_package"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_search_by_file", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_search_by_file"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_t", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_t"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_unregister_install_package_handle", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_unregister_install_package_handle"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_unregister_remove_package_handle", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_package_unregister_remove_package_handle"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_package, "kdk_package_verify_disk_space", restype=_c.c_int)
        BOUND_FUNCS["kdk_package_verify_disk_space"] = "libkypackage"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_realtime = load_library("libkyrealtime", mock=False)
if _lib_realtime is not None:
    BOUND_LIBS["libkyrealtime"] = _lib_realtime
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_branch_misses", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_cpu_branch_misses"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_bus_cycles", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_cpu_bus_cycles"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_cache_misses", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_cpu_cache_misses"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_cycles", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_cpu_cycles"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_hard_page_faults", restype=_c.c_float)
        BOUND_FUNCS["kdk_real_get_cpu_hard_page_faults"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_instructions", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_cpu_instructions"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_kernel_modes_per", restype=_c.c_float)
        BOUND_FUNCS["kdk_real_get_cpu_kernel_modes_per"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_queue_length", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_cpu_queue_length"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_soft_page_faults", restype=_c.c_float)
        BOUND_FUNCS["kdk_real_get_cpu_soft_page_faults"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_temperature", restype=_c.c_double)
        BOUND_FUNCS["kdk_real_get_cpu_temperature"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_cpu_user_modes_per", restype=_c.c_float)
        BOUND_FUNCS["kdk_real_get_cpu_user_modes_per"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_disk_queue_length", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_real_get_disk_queue_length"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_disk_rate", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_disk_rate"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_disk_read", restype=_c.c_long)
        BOUND_FUNCS["kdk_real_get_disk_read"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_disk_temperature", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_disk_temperature"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_disk_write", restype=_c.c_long)
        BOUND_FUNCS["kdk_real_get_disk_write"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_if_speed", restype=_c.c_float)
        BOUND_FUNCS["kdk_real_get_if_speed"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_memory_page", restype=_c.c_int)
        BOUND_FUNCS["kdk_real_get_memory_page"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_realtime, "kdk_real_get_net_speed", restype=_c.c_float)
        BOUND_FUNCS["kdk_real_get_net_speed"] = "libkyrealtime"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_restart = load_library("libkyrestart", mock=False)
if _lib_restart is not None:
    BOUND_LIBS["libkyrestart"] = _lib_restart
    try:
        declare(_lib_restart, "kdk_power_get_control_disk_status", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_power_get_control_disk_status"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_get_mode", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_power_get_mode"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_get_screenidle_timeout", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_power_get_screenidle_timeout"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_is_active", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_power_is_active"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_is_hibernate", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_power_is_hibernate"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_is_support_hibernate", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_power_is_support_hibernate"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_is_support_suspend", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_power_is_support_suspend"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_set_hibernate", restype=_c.c_int)
        BOUND_FUNCS["kdk_power_set_hibernate"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_power_set_suspend", restype=_c.c_int)
        BOUND_FUNCS["kdk_power_set_suspend"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_restart_cancel_reboot", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_restart_cancel_reboot"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_restart_is_schedule_reboot", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_restart_is_schedule_reboot"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_restart_reboot", restype=_c.c_int)
        BOUND_FUNCS["kdk_restart_reboot"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_restart, "kdk_restart_schedule_reboot", restype=_c.c_int)
        BOUND_FUNCS["kdk_restart_schedule_reboot"] = "libkyrestart"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_rtinfo = load_library("libkyrtinfo", mock=False)
if _lib_rtinfo is not None:
    BOUND_LIBS["libkyrtinfo"] = _lib_rtinfo
    try:
        declare(_lib_rtinfo, "kdk_rti_get_cpu_current_usage", restype=_c.c_float)
        BOUND_FUNCS["kdk_rti_get_cpu_current_usage"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_active_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_active_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_buffers_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_buffers_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_cached_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_cached_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_dirty_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_dirty_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_inactive_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_inactive_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_map_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_map_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_res_available_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_res_available_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_res_free_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_res_free_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_res_total_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_res_total_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_res_usage_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_res_usage_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_res_usage_percent", restype=_c.c_float)
        BOUND_FUNCS["kdk_rti_get_mem_res_usage_percent"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_shared_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_shared_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_slab_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_slab_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_swap_cached_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_swap_cached_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_swap_free_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_swap_free_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_swap_total_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_swap_total_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_swap_usage_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_swap_usage_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_swap_usage_percent", restype=_c.c_float)
        BOUND_FUNCS["kdk_rti_get_mem_swap_usage_percent"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_mem_virt_alloc_KiB", restype=_c.c_ulong)
        BOUND_FUNCS["kdk_rti_get_mem_virt_alloc_KiB"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_rtinfo, "kdk_rti_get_uptime", restype=_c.c_int)
        BOUND_FUNCS["kdk_rti_get_uptime"] = "libkyrtinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_shutdown = load_library("libkyshutdown", mock=False)
if _lib_shutdown is not None:
    BOUND_LIBS["libkyshutdown"] = _lib_shutdown
    try:
        declare(_lib_shutdown, "kdk_shutdown_cancel_power_off", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_shutdown_cancel_power_off"] = "libkyshutdown"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_shutdown, "kdk_shutdown_exit_window", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_shutdown_exit_window"] = "libkyshutdown"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_shutdown, "kdk_shutdown_is_schedule_power_off", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_shutdown_is_schedule_power_off"] = "libkyshutdown"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_shutdown, "kdk_shutdown_lock_work_station", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_shutdown_lock_work_station"] = "libkyshutdown"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_shutdown, "kdk_shutdown_power_off", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_shutdown_power_off"] = "libkyshutdown"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_shutdown, "kdk_shutdown_schedule_power_off", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_shutdown_schedule_power_off"] = "libkyshutdown"
    except (AttributeError, OSError):
        pass  # 符号不存在

_lib_sysinfo = load_library("libkysysinfo", mock=False)
if _lib_sysinfo is not None:
    BOUND_LIBS["libkysysinfo"] = _lib_sysinfo
    try:
        declare(_lib_sysinfo, "kdk_system_change_password", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_change_password"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_check_has_user", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_check_has_user"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_check_service_startup", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_check_service_startup"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_create_user", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_create_user"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_disable_service_startup", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_disable_service_startup"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_form", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_form"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_free_service_list", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_free_service_list"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_activationStatus", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_get_activationStatus"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_all_service_list", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_all_service_list"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_appScene", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_appScene"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_architecture", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_architecture"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_automatic_start_service_list", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_automatic_start_service_list"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_basic_form", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_basic_form"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_buildTime", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_buildTime"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_cloudPlatformType", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_cloudPlatformType"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_custom_version", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_custom_version"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_eUser", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_eUser"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_env", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_env"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_file_descriptor", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_get_file_descriptor"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_grub_menu", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_grub_menu"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_hostCloudPlatform", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_hostCloudPlatform"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_hostName", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_hostName"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_hostVirtType", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_hostVirtType"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_kernelVersion", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_kernelVersion"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_loadavg", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_loadavg"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_machine_type", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_machine_type"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_major_version", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_major_version"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_minor_version", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_minor_version"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_process_nums", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_get_process_nums"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_productFeatures", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_get_productFeatures"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_production_inner_version", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_production_inner_version"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_production_line", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_production_line"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_projectName", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_projectName"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_projectSubName", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_projectSubName"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_resolving_power", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_resolving_power"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_serialNumber", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_serialNumber"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_serial_name", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_serial_name"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_startup_takeTime", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_startup_takeTime"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_systemCategory", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_systemCategory"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_systemName", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_systemName"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_system_locale", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_system_locale"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_system_manufacturer", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_system_manufacturer"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_thread_nums", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_get_thread_nums"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_version", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_version"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_version_alias", restype=_c.c_char_p)
        BOUND_FUNCS["kdk_system_get_version_alias"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_version_detaile", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_get_version_detaile"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_get_word", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_get_word"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_is_service_active", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_is_service_active"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_is_zyj", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_is_zyj"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_register_switch_user_handle", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_register_switch_user_handle"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_set_service_reload", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_set_service_reload"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_set_service_restart", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_set_service_restart"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_set_service_shutdown", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_set_service_shutdown"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_set_service_startup", restype=_c.c_int)
        BOUND_FUNCS["kdk_system_set_service_startup"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_unregister_switch_user_handle", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_unregister_switch_user_handle"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
    try:
        declare(_lib_sysinfo, "kdk_system_user_logout_status", restype=_c.c_void_p)
        BOUND_FUNCS["kdk_system_user_logout_status"] = "libkysysinfo"
    except (AttributeError, OSError):
        pass  # 符号不存在
