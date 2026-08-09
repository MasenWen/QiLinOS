import sys, json, traceback
sys.path.insert(0, '/home/kylin/work/projects/project_dev1')

def t(name, fn, *a, **kw):
    try:
        r = fn(*a, **kw)
        s = json.dumps(r, ensure_ascii=False, default=str) if isinstance(r, (dict,list)) else str(r)
        print(f'  OK  {name}: {s[:120]}')
        return True
    except Exception as e:
        print(f'  FAIL {name}: {e}')
        return False

print('=== System SDK ===')
from src.sdk.system import get_system_info,get_display_info,get_hardware_info,get_gpu_summary,get_fan_info
t('get_system_info', get_system_info)
t('get_hardware_info', get_hardware_info)
t('get_display_info', get_display_info)
t('get_gpu_summary', get_gpu_summary)
t('get_fan_info', get_fan_info)

print('\n=== Network SDK ===')
from src.sdk.network import get_network_interfaces,get_ip_address,get_mac_address,get_network_status
t('get_network_interfaces', get_network_interfaces)
t('get_ip_address', get_ip_address)
t('get_mac_address', get_mac_address)
t('get_network_status', get_network_status)

print('\n=== Disk SDK ===')
from src.sdk.disk import get_disk_list,get_disk_usage,get_mount_points
t('get_disk_list', get_disk_list)
t('get_disk_usage', get_disk_usage)
t('get_mount_points', get_mount_points)

print('\n=== Process SDK ===')
from src.sdk.process import get_process_list,get_process_info,get_process_by_name
t('get_process_list count', lambda: len(get_process_list()))
t('get_process_info(1)', lambda: get_process_info(1))
t('get_process_by_name', lambda: get_process_by_name('python3'))

print('\n=== Battery SDK ===')
from src.sdk.battery import get_battery_info,get_battery_percentage,is_charging,get_power_plan
t('get_battery_info', get_battery_info)
t('get_battery_percentage', get_battery_percentage)
t('is_charging', is_charging)
t('get_power_plan', get_power_plan)

print('\n=== Bluetooth SDK ===')
from src.sdk.bluetooth import get_bluetooth_status
t('get_bluetooth_status', get_bluetooth_status)

print('\n=== Power SDK ===')
from src.sdk.power import is_available as pwr, summary, is_support_suspend, is_support_hibernate
t('is_available', pwr)
t('is_support_suspend', is_support_suspend)
t('is_support_hibernate', is_support_hibernate)
t('summary', summary)

print('\n=== Desktop Ctrl SDK ===')
from src.sdk.desktop_ctrl import is_available as dc, summary as dcs
t('is_available', dc)
t('summary', dcs)

print('\n=== AI SDK ===')
from src.sdk.ai_text import is_available as ait
from src.sdk.ai_image import is_available as aimg
from src.sdk.ai_speech import is_available as ais
t('ai_text.is_available', ait)
t('ai_image.is_available', aimg)
t('ai_speech.is_available', ais)

print('\n=== MCP Tool Bridge Test ===')
try:
    from src.toolkit.init_tools import init_all_tools
    reg = init_all_tools()
    tools = reg.list_all()
    print(f'  OK  Toolkit initialized: {len(tools)} tools registered')
    for tn in sorted(tools):
        tool = reg.get(tn)
        print(f'      - {tn} [{tool.risk_level.value if tool else "?"}]')
except Exception as e:
    print(f'  FAIL Toolkit init: {e}')
    traceback.print_exc()

print('\n=== All tests complete ===')
