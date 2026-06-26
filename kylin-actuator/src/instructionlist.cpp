#include "instructionlist.h"
#include <QIcon>
#include <cstdlib>

#include <kpushbutton.h>
#include <kaboutdialog.h>
#include <qapplication.h>
#include <kmessagebox.h>
#include <filesystem>
#include <iostream>
#include <fstream>
#include <unistd.h>
#include <qprocess.h>
#include <qdir.h>
#include <regex> // For std::regex_replace
#include <QDesktopServices>
#include <unordered_map>
#include <functional>


// 定义函数指针类型，用于保存操作函数

#include "dbusclient.h"
#include "linkdialog.h"
#include "pubdef.h"
//0 sucess
//1 user cancel
//2 参数错误
//3 找不到参数执行目标
//4 执行初始出错
//5 执行过程出错
//6 执行结尾出错



namespace fs = std::filesystem;

std::string appZhName = "";

void printIndex(int index)
{
    if(index == -1)
    {
        std::cout << "<AI>好的，";
    }
    else
    {
        std::cout << "<AI>";
    }
    //    if(index > -1)
    //    {
    //        std::cout << index+1 << ". ";
    //    }
}
void checkIfEnd(int size, int index)
{
    if(index==-1 | size-1 == index)
    {
        std::cout << "<end>" << std::endl;
    }
}

int closeBluetooth(int index)
{
    system("echo 'power off' | bluetoothctl");
    printIndex(index);
    std::cout << "关闭蓝牙" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int closeNetWork(int index)
{
    std::string input = "nmcli radio wifi off &";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经关闭网络" << std::endl;
    }
    else
    {
        std::cout << "关闭网络" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int closeBluetoothicon(int index)
{
    std::string input = "gsettings set org.ukui.bluetooth tray-show false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已关闭任务栏蓝牙图标" << std::endl;
    }
    else
    {
        std::cout << "关闭任务栏蓝牙图标" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int closeRepeatkeys(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-keyboard repeat false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已关闭键盘按键重复设置" << std::endl;
    }
    else
    {
        std::cout << "关闭键盘按键重复设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeRepeatnotification(int index)
{
    std::string input = "gsettings set org.ukui.control-center.osd show-lock-tip false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已关闭键盘按键提示设置" << std::endl;
    }
    else
    {
        std::cout << "关闭键盘按键提示设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeMouseltohand(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-mouse left-handed false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在设置鼠标左按键习惯" << std::endl;
    }
    else
    {
        std::cout << "设置鼠标左按键习惯" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeMouseacceleration(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-mouse mouse-accel false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭鼠标指针加速设置" << std::endl;
    }
    else
    {
        std::cout << "关闭鼠标指针加速设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeCtrlshowpointer(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-mouse locate-pointer false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭按Ctrl键显示鼠标指针位置设置" << std::endl;
    }
    else
    {
        std::cout << "关闭按Ctrl键显示鼠标指针位置设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeTextcursorblink(int index)
{
    std::string input = "gsettings set org.mate.interface cursor-blink false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭文本区域光标闪烁" << std::endl;
    }
    else
    {
        std::cout << "关闭文本区域光标闪烁" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closePasswordonsleep(int index)
{
    std::string input = "gsettings set org.ukui.screensaver sleep-activation-enabled false";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭睡眠/休眠密码设置" << std::endl;
    }
    else
    {
        std::cout << "关闭睡眠/休眠密码设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}



std::string getAppValueFromFile(std::ifstream& file, const std::string& name) {
    std::string line;

    // 读取文件中的每一行
    file.clear();
    file.seekg(0, std::ios::beg);
    while (std::getline(file, line))
    {
        if (line.find(name, 0) == 0)
        {
            // 找到第一个等号后的位置
            size_t pos = line.find('=');
            //            std::cout << name << std::endl;
            if (pos != std::string::npos)
            {
                // 提取GenericName的键和值
                std::string key = line.substr(0, pos);
                std::string value = line.substr(pos + 1);
                if(line.find(' ') != -1)
                {
                    value = "\"" + value + "\"";
                }
                return value; // 如果没有找到空格，返回原字符串
            }

        }
    }
    return "";
}

std::string getKeyValueFromFile(std::ifstream& file, const std::string& name) {
    std::string line;

    // 读取文件中的每一行
    while (std::getline(file, line))
    {
        if (line.rfind(name, 0) == 0)
        {
            // 找到第一个等号后的位置
            size_t pos = line.find('=');
            if (pos != std::string::npos)
            {
                // 提取GenericName的键和值
                std::string key = line.substr(0, pos);
                std::string value = line.substr(pos + 1);
                if(key.compare(name) == 0)
                {
                    size_t spacePos = value.find(' ');

                    if (spacePos != std::string::npos) {
                        return value.substr(0, spacePos);
                    } else {
                        return value; // 如果没有找到空格，返回原字符串
                    }
                }
            }
        }
    }
    return "";
}

bool isDir(const std::string path)
{
    fs::path pathToCheck(path);
    return fs::is_directory(pathToCheck);
}
bool isMail(const std::string input)
{

    std::regex mail_regex("\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b");
    auto mail_begin = std::sregex_iterator(input.begin(), input.end(), mail_regex);
    auto mail_end = std::sregex_iterator();

    // 遍历所有匹配结果并输出
    for (std::sregex_iterator i = mail_begin; i != mail_end; ++i) {
        return true;
    }
    return false;
}
bool isUrl(const std::string input)
{
    std::regex url_regex("\\b(?:(https?|ftp|file)://|www\\.)[-A-Za-z0-9+&@#/%?=~_|!:,.;]+\\b");

    auto urls_begin = std::sregex_iterator(input.begin(), input.end(), url_regex);
    auto urls_end = std::sregex_iterator();

    // 遍历所有匹配结果并输出
    for (std::sregex_iterator i = urls_begin; i != urls_end; ++i) {
        return true;
    }
    return false;
}


int nameExistInFile(std::ifstream& file, std::string app, bool vague)
{
    std::string line;

    int status = 3;
    // 读取文件中的每一行

    while (std::getline(file, line))
    {
        //line.rfind("GenericName", 0) == 0 ||
        if (line.rfind("Name", 0) == 0)
        {
            // 找到第一个等号后的位置
            size_t pos = line.find('=');
            if (pos != std::string::npos)
            {
                // 提取GenericName的键和值
                std::string key = line.substr(0, pos);
                std::string value = line.substr(pos + 1);
                transform(value.begin(), value.end(), value.begin(), ::tolower);
                if(vague && value.find(app) != std::string::npos)
                {
                    status = 0;
                    break;
                }
                else if( value.compare(app) == 0)
                {
                    status = 0;
                    break;
                }
            }
        }

    }
    return status;
}
int parseDesktopFile(std::string path, std::string app, bool vague, bool open)
{
    std::ifstream file(path); // 假设.desktop文件名为application.desktop
    int status = nameExistInFile(file, app, vague);
    if(status == 0)
    {


        std::string exec = getKeyValueFromFile(file, "Exec");
        appZhName = getAppValueFromFile(file, "Name[zh_CN]");
        //        std::cout << "Begin Exec: " << exec << std::endl;
        if(open)
        {
            if(exec != "/usr/bin/peony")
            {
                QProcess::startDetached(exec.c_str(), QStringList());
                usleep(1000000);
            }
        }
        else
        {
            size_t last_slash_pos = exec.find_last_of('/');

            // 2. 确定起始位置（如果没有 '/'，则从 0 开始）
            size_t start = (last_slash_pos != std::string::npos) ? last_slash_pos + 1 : 0;

            // 4. 提取子字符串
            std::string program_name = exec.substr(start);
            std::cout << program_name  << std::endl;
            QStringList arguments;
            arguments << QString::fromStdString(program_name);

            QProcess process;
            process.start("pkill", arguments);
            process.waitForFinished();
        }
        //        std::cout << "End Exec: " << exec << std::endl;
    }
    // 关闭文件
    file.close();

    return status;
}


int openOrCloseApplication(std::string app, bool vague, bool open)
{
    transform(app.begin(), app.end(), app.begin(), ::tolower);

    return parseApplications(app, vague, open);
}


int openNetWork(int index)
{
    std::string input = "nmcli radio wifi on &";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开网络... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开网络" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openBluetoothicon(int index)
{
    std::string input = "/usr/bin/gsettings set org.ukui.bluetooth tray-show true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开任务栏蓝牙图标... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开任务栏蓝牙图标" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openPasswordonsleep(int index)
{
    std::string input = "gsettings set org.ukui.screensaver sleep-activation-enabled true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开睡眠/休眠密码设置... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开睡眠/休眠密码设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openRepeatkeys(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-keyboard repeat true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开键盘按键重复设置... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开键盘按键重复设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openRepeatnotification(int index)
{
    std::string input = "gsettings set org.ukui.control-center.osd show-lock-tip true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开键盘按键提示设置... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开键盘按键提示设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openMouseltohand(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-mouse left-handed true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在设置鼠标右按键习惯... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "设置鼠标右按键习惯" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openMouseacceleration(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-mouse mouse-accel true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开鼠标指针加速设置... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开鼠标指针加速设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openCtrlshowpointer(int index)
{
    std::string input = "gsettings set org.ukui.peripherals-mouse locate-pointer true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开按Ctrl键显示鼠标指针位置设置... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开按Ctrl键显示鼠标指针位置设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openPrinter(int index)
{
    std::string input = "kylin-printer &";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开打印机... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开打印机" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openInputer(int index)
{
    std::string input = "fcitx5-config-qt &";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开输入法设置... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开输入法设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openTextcursorblink(int index)
{
    std::string input = "gsettings set org.mate.interface cursor-blink true";
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开文本区域光标闪烁... 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开文本区域光标闪烁" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}



int openBluetooth(int index)
{
    system("echo 'power on' | bluetoothctl");
    printIndex(index);
    std::cout << "打开蓝牙" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openMail(std::string str)
{
    QString link = QString::fromStdString(str);
    link.prepend("mailto:");
    QUrl url(link);
    QDesktopServices::openUrl(url);
    return RE_SUCCESS;
}
int openUrl(std::string str)
{

    QString link = QString::fromStdString(str);
    if (!link.startsWith("http://") && !link.startsWith("https://")) {
        link.prepend("http://"); // 添加 http:// 前缀
    }
    QUrl url(link);
    QDesktopServices::openUrl(url);
    return RE_SUCCESS;
}

int openBaidusearch(int index)
{
    system("xdg-open 'https://www.baidu.com'");
    printIndex(index);
    std::cout << "打开百度搜索引擎" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openBingsearch(int index)
{
    system("xdg-open 'https://www.bing.com'");
    printIndex(index);
    std::cout << "打开Bing搜索引擎" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openGooglesearch(int index)
{
    system("xdg-open 'https://www.google.com'");
    printIndex(index);
    std::cout << "打开谷歌搜索引擎" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openRootdir(int index)
{
    system("peony / &");
    printIndex(index);
    std::cout << "打开根目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openTempdir(int index)
{
    system("peony /tmp &");
    printIndex(index);
    std::cout << "打开临时文件目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openHomedir(int index)
{
    system("peony ${HOME} &");
    printIndex(index);
    std::cout << "打开主目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openDesktopdir(int index)
{
    system("peony ${HOME}/桌面 &");
    printIndex(index);
    std::cout << "打开桌面目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openDocumentdir(int index)
{
    system("peony ${HOME}/文档 &");
    printIndex(index);
    std::cout << "打开文档目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openImagedir(int index)
{
    system("peony ${HOME}/图片 &");
    printIndex(index);
    std::cout << "打开图片目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openDownloaddir(int index)
{
    system("peony ${HOME}/下载 &");
    printIndex(index);
    std::cout << "打开下载目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openMusicdir(int index)
{
    system("peony ${HOME}/音乐 &");
    printIndex(index);
    std::cout << "打开音乐目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openVideodir(int index)
{
    system("peony ${HOME}/视频 &");
    printIndex(index);
    std::cout << "打开视频目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openPublicdir(int index)
{
    system("peony ${HOME}/桌面 &");
    printIndex(index);
    std::cout << "打开公共目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openTemplatedir(int index)
{
    system("peony ${HOME}/模板 &");
    printIndex(index);
    std::cout << "打开模板目录" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int emptyTrash(int index)
{
    system("gio trash --empty");
    printIndex(index);
    std::cout << "清理回收站" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4inputer(int index)
{
    system("fcitx-config-gtk3 &");
    printIndex(index);
    std::cout << "打开输入法设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4touchpad(int index)
{
    system("gsettings set org.mate.peripherals-touchpad touchpad-enabled true");
    printIndex(index);
    std::cout << "打开触控板" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4connectioneditor(int index)
{
    system("nm-connection-editor");
    printIndex(index);
    std::cout << "打开网络连接" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4printersetting(int index)
{
    system("system-config-printer");
    printIndex(index);
    std::cout << "打开打印机设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4brightness(int index)
{
    system("gsettings set org.mate.power-manager brightness-ac 100");
    printIndex(index);
    std::cout << "增加屏幕亮度" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4settings(int index)
{
    system("kylin-control-center");
    printIndex(index);
    std::cout << "打开设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4wallpapersetting(int index)
{
    system("kylin-control-center -a");
    printIndex(index);
    std::cout << "打开背景设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4themesetting(int index)
{
    system("kylin-control-center -a");
    printIndex(index);
    std::cout << "打开主题设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4fontssetting(int index)
{
    system("kylin-control-center -a");
    printIndex(index);
    std::cout << "打开字体设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4screensaversetting(int index)
{
    system("kylin-control-center -a");
    printIndex(index);
    std::cout << "打开锁屏设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4datesetting(int index)
{
    system("kylin-control-center -t");
    printIndex(index);
    std::cout << "打开时间和日期设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4userinfosetting(int index)
{
    system("kylin-control-center -u");
    printIndex(index);
    std::cout << "打开账户信息设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4keyboardsetting(int index)
{
    system("kylin-control-center -k");
    printIndex(index);
    std::cout << "打开键盘设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4audiosetting(int index)
{
    system("kylin-control-center -s");
    printIndex(index);
    std::cout << "打开声音设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4netconnectsetting(int index)
{
    system("nm-connection-editor");
    printIndex(index);
    std::cout << "打开有线网络设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4displaysetting(int index)
{
    system("kylin-control-center -d");
    printIndex(index);
    std::cout << "打开显示器设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4powersetting(int index)
{
    system("kylin-control-center -p");
    printIndex(index);
    std::cout << "打开电源设置" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int emptyTempfile(int index)
{
    system("rm -rf /tmp/*");
    printIndex(index);
    std::cout << "清理临时文件" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}
int openKylinv4screensaver(int index)
{
    system("ukui-screensaver-command -l");
    printIndex(index);
    std::cout << "锁屏" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4filemanager(int index)
{
    system("caja");
    printIndex(index);
    std::cout << "打开文件管理器" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4printer(int index)
{
    system("system-config-printer");
    printIndex(index);
    std::cout << "开启打印机" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4screenshot(int index)
{
    system("mate-screenshot");
    printIndex(index);
    std::cout << "截屏" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4terminal(int index)
{
    system("mate-terminal");
    printIndex(index);
    std::cout << "打开终端" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int openKylinv4systemmonitor(int index)
{
    system("mate-system-monitor");
    printIndex(index);
    std::cout << "打开系统监视器" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}



int emptyDependencies(int index)
{
    system("echo 'openkylin' | sudo -S apt autoremove -y");
    printIndex(index);
    std::cout << "清理无用依赖包" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}


void output(std::string outStr)
{
    QString path = QDir::homePath() + "/.kylin-actuator/output";
    std::string stdPath = path.toStdString();
    // 创建一个输出文件流，并打开文件以供写入
    std::ofstream outfile(stdPath);

    // 检查文件是否成功打开
    if (!outfile.is_open()) {
        std::cerr << "Unable to open file " << stdPath << std::endl;
        return ;
    }

    // 将文本写入到文件
    outfile << outStr;

    // 关闭文件流
    outfile.close();
}

std::string replaceStr(std::string input, const std::string toSearch, const std::string replace, bool all)
{
    size_t pos = input.find(toSearch);
    while (pos != std::string::npos) { // 当还有子串时循环
        // 替换发现的第一个子串
        input.replace(pos, toSearch.length(), replace);
        if(!all)
        {
            break;
        }
        // 在当前位置之后查找下一个子串
        pos = input.find(toSearch, pos + replace.length());
    }
    return input;
}


int parseApplications(std::string app, bool vague, bool open)
{
    // 要遍历的文件夹路径，修改为实际的文件夹路径
    std::string pathToSearch = "/usr/share/applications";

    // 检查路径是否存在并且是一个目录
    if (!fs::exists(pathToSearch) || !fs::is_directory(pathToSearch)) {
        std::cerr << "Path does not exist or is not a directory.\n";
        return 3;
    }

    int status = 3;
    // 遍历给定路径下的所有项
    for (const auto& entry : fs::recursive_directory_iterator(pathToSearch)) {
        // 检查项是否是文件，以及扩展名是否为.desktop
        if (entry.is_regular_file() && entry.path().extension() == ".desktop") {
            //            std::cout << "Found .desktop file: " << entry.path() << '\n';
            status = parseDesktopFile(entry.path(), app, vague, open);
            if(status != 3)
            {
                return status;
            }
        }
    }

    return 3;
}


std::string sysExec(const char* cmd) {

    std::array<char, 128> buffer;
    std::string result;
    std::unique_ptr<FILE, decltype(&pclose)> pipe(popen(cmd, "r"), pclose);
    if (!pipe) {
        throw std::runtime_error("popen() failed!");
    }
    while (fgets(buffer.data(), buffer.size(), pipe.get()) != nullptr) {
        result += buffer.data();
    }
    return result;
}

std::string showExec(const char* cmd) {
    std::array<char, 128> buffer;
    std::string result;
    // 使用 popen 打开管道
    std::unique_ptr<FILE, decltype(&pclose)> pipe(popen(cmd, "r"), pclose);
    if (!pipe) {
        throw std::runtime_error("popen() failed!");
    }
    // 读取命令输出
    while (fgets(buffer.data(), buffer.size(), pipe.get()) != nullptr) {
        result += buffer.data();
    }
    return result;
}


int showVersioninfo(int index){
    std::string result = showExec("cat /etc/os-release | grep 'PRETTY_NAME' | awk -F = '{print $2}'");
    printIndex(index);
    std::cout << "系统版本信息如下：" << result;
    return RE_SUCCESS;
}

int showCpuinfo(int index){
    std::string result = showExec("cat /proc/cpuinfo | grep 'model name' | awk -F: '{print $2}' | head -n 1");
    printIndex(index);
    std::cout << "系统CPU信息如下：" << result;
    return RE_SUCCESS;
}

int showDiskinfo(int index){
    std::string result = showExec("lsblk");
    printIndex(index);
    std::cout << "系统硬盘信息如下：" << result;
    return RE_SUCCESS;
}

int showKernelinfo(int index){
    std::string result = showExec("uname -a");
    printIndex(index);
    std::cout << "系统内核信息如下：" << result;
    return RE_SUCCESS;
}

int showIfconfiginfo(int index){
    std::string result = showExec("ifconfig");
    printIndex(index);
    std::cout << "系统网络信息如下：" << result;
    return RE_SUCCESS;
}

int showUsernameinfo(int index){
    std::string result = showExec("whoami");
    printIndex(index);
    std::cout << "当前用户名信息如下：" << result;
    return RE_SUCCESS;
}

int showDatetime(int index){
    std::string result = showExec("date");
    printIndex(index);
    std::cout << "当前时间信息如下：" << result;
    return RE_SUCCESS;
}

int showSensorversion(int index){
    std::string result = showExec("sensors -v");
    printIndex(index);
    std::cout << "当前sensorversion版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLsusbversion(int index){
    std::string result = showExec("lsusb -V");
    printIndex(index);
    std::cout << "当前lsusb版本信息如下：" << result;
    return RE_SUCCESS;
}

int showBcversion(int index){
    std::string result = showExec("bc -v | head -n 1");
    printIndex(index);
    std::cout << "当前bc版本信息如下：" << result;
    return RE_SUCCESS;
}

int showBashversion(int index){
    std::string result = showExec("bash --version | head -n 1");
    printIndex(index);
    std::cout << "当前bash版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLddversion(int index){
    std::string result = showExec("ldd --version | head -n 1");
    printIndex(index);
    std::cout << "当前ldd版本信息如下：" << result;
    return RE_SUCCESS;
}

int showInfocmpversion(int index){
    std::string result = showExec("infocmp -V");
    printIndex(index);
    std::cout << "当前infocmp版本信息如下：" << result;
    return RE_SUCCESS;
}

int showOpensslversion(int index){
    std::string result = showExec("openssl version");
    printIndex(index);
    std::cout << "当前openssl版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLdversion(int index){
    std::string result = showExec("ld --version | head -n 1");
    printIndex(index);
    std::cout << "当前ld版本信息如下：" << result;
    return RE_SUCCESS;
}

int showFindversion(int index){
    std::string result = showExec("find --version | head -n 1");
    printIndex(index);
    std::cout << "当前find版本信息如下：" << result;
    return RE_SUCCESS;
}


int showGzipversion(int index){
    std::string result = showExec("gzip --version | head -n 1");
    printIndex(index);
    std::cout << "当前gzip版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTarversion(int index){
    std::string result = showExec("tar --version | head -n 1");
    printIndex(index);
    std::cout << "当前tar版本信息如下：" << result;
    return RE_SUCCESS;
}

int showXzversion(int index){
    std::string result = showExec("xz --version | head -n 1");
    printIndex(index);
    std::cout << "当前xz版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSedversion(int index){
    std::string result = showExec("sed --version | head -n 1");
    printIndex(index);
    std::cout << "当前sed版本信息如下：" << result;
    return RE_SUCCESS;
}

int showAwkversion(int index){
    std::string result = showExec("awk --version | head -n 1");
    printIndex(index);
    std::cout << "当前awk版本信息如下：" << result;
    return RE_SUCCESS;
}

int showGrepversion(int index){
    std::string result = showExec("grep --version | head -n 1");
    printIndex(index);
    std::cout << "当前grep版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIptablesversion(int index){
    std::string result = showExec("iptables --version | head -n 1");
    printIndex(index);
    std::cout << "当前iptables版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSystemdversion(int index){
    std::string result = showExec("systemctl --version | head -n 1");
    printIndex(index);
    std::cout << "当前systemctl版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPsversion(int index)
{
    std::string result = showExec("ps --version");
    printIndex(index);
    std::cout << "当前ps版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIfconfigversion(int index){
    std::string result = showExec("ifconfig --version");
    printIndex(index);
    std::cout << "当前ifconfig版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIpversion(int index){
    std::string result = showExec("ip -V");
    printIndex(index);
    std::cout << "当前ip版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTune2fsversion(int index){
    std::string result = showExec("tune2fs --version | head -n 1");
    printIndex(index);
    std::cout << "当前tune2fs版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMountversion(int index){
    std::string result = showExec("mount --version");
    printIndex(index);
    std::cout << "当前mount版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDmidecodeversion(int index){
    std::string result = showExec("dmidecode --version");
    printIndex(index);
    std::cout << "当前dmidecode版本信息如下：" << result;
    return RE_SUCCESS;
}

int showVimversion(int index){
    std::string result = showExec("vim --version | head -n 1");
    printIndex(index);
    std::cout << "当前vim版本信息如下：" << result;
    return RE_SUCCESS;
}


int showManversion(int index){
    std::string result = showExec("man --version");
    printIndex(index);
    std::cout << "当前man版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPingversion(int index){
    std::string result = showExec("ping -V | head -n 1");
    printIndex(index);
    std::cout << "当前ping版本信息如下：" << result;
    return RE_SUCCESS;
}

int showEthtoolversion(int index) {
    std::string result = showExec("ethtool --version");
    printIndex(index);
    std::cout << "当前ethtool版本信息如下：" << result;
    return RE_SUCCESS;
}

int showWgetversion(int index) {
    std::string result = showExec("wget --version | head -n 1");
    printIndex(index);
    std::cout << "当前wget版本信息如下：" << result;
    return RE_SUCCESS;
}

int showCurlversion(int index) {
    std::string result = showExec("curl --version | head -n 1");
    printIndex(index);
    std::cout << "当前curl版本信息如下：" << result;
    return RE_SUCCESS;
}

int showGettextversion(int index) {
    std::string result = showExec("gettext --version | head -n 1");
    printIndex(index);
    std::cout << "当前gettext版本信息如下：" << result;
    return RE_SUCCESS;
}

int showHostnamectlversion(int index) {
    std::string result = showExec("hostnamectl --version | head -n 1");
    printIndex(index);
    std::cout << "当前hostnamectl版本信息如下：" << result;
    return RE_SUCCESS;
}

int showUptimeversion(int index) {
    std::string result = showExec("uptime --version");
    printIndex(index);
    std::cout << "当前uptime版本信息如下：" << result;
    return RE_SUCCESS;
}

int showWhoversion(int index) {
    std::string result = showExec("who --version | head -n 1");
    printIndex(index);
    std::cout << "当前who版本信息如下：" << result;
    return RE_SUCCESS;
}

int showWversion(int index) {
    std::string result = showExec("w --version");
    printIndex(index);
    std::cout << "当前w版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTopversion(int index) {
    std::string result = showExec("top --version");
    printIndex(index);
    std::cout << "当前top版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDmesgversion(int index) {
    std::string result = showExec("dmesg --version");
    printIndex(index);
    std::cout << "当前dmesg版本信息如下：" << result;
    return RE_SUCCESS;
}

int showVmstatversion(int index) {
    std::string result = showExec("vmstat --version");
    printIndex(index);
    std::cout << "当前vmstat版本信息如下：" << result;
    return RE_SUCCESS;
}

int showFreeversion(int index) {
    std::string result = showExec("free --version");
    printIndex(index);
    std::cout << "当前free版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLsversion(int index) {
    std::string result = showExec("ls --version | head -n 1");
    printIndex(index);
    std::cout << "当前ls版本信息如下：" << result;
    return RE_SUCCESS;
}

int showCpversion(int index) {
    std::string result = showExec("cp --version | head -n 1");
    printIndex(index);
    std::cout << "当前cp版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMvversion(int index) {
    std::string result = showExec("mv --version | head -n 1");
    printIndex(index);
    std::cout << "当前mv版本信息如下：" << result;
    return RE_SUCCESS;
}

int showRmversion(int index) {
    std::string result = showExec("rm --version | head -n 1");
    printIndex(index);
    std::cout << "当前rm版本信息如下：" << result;
    return RE_SUCCESS;
}

int showChmodversion(int index) {
    std::string result = showExec("chmod --version | head -n 1");
    printIndex(index);
    std::cout << "当前chmod版本信息如下：" << result;
    return RE_SUCCESS;
}

int showChownversion(int index) {
    std::string result = showExec("chown --version | head -n 1");
    printIndex(index);
    std::cout << "当前chown版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLnversion(int index) {
    std::string result = showExec("ln --version | head -n 1");
    printIndex(index);
    std::cout << "当前ln版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDfversion(int index) {
    std::string result = showExec("df --version | head -n 1");
    printIndex(index);
    std::cout << "当前df版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDuversion(int index) {
    std::string result = showExec("du --version | head -n 1");
    printIndex(index);
    std::cout << "当前du版本信息如下：" << result;
    return RE_SUCCESS;
}

int showStatversion(int index) {
    std::string result = showExec("stat --version | head -n 1");
    printIndex(index);
    std::cout << "当前stat版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTeeversion(int index) {
    std::string result = showExec("tee --version | head -n 1");
    printIndex(index);
    std::cout << "当前tee版本信息如下：" << result;
    return RE_SUCCESS;
}

int showHeadversion(int index) {
    std::string result = showExec("head --version | head -n 1");
    printIndex(index);
    std::cout << "当前head版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTailversion(int index) {
    std::string result = showExec("tail --version | head -n 1");
    printIndex(index);
    std::cout << "当前tail版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSortversion(int index) {
    std::string result = showExec("sort --version | head -n 1");
    printIndex(index);
    std::cout << "当前sort版本信息如下：" << result;
    return RE_SUCCESS;
}

int showUniqversion(int index) {
    std::string result = showExec("uniq --version | head -n 1");
    printIndex(index);
    std::cout << "当前uniq版本信息如下：" << result;
    return RE_SUCCESS;
}

int showCutversion(int index) {
    std::string result = showExec("cut --version | head -n 1");
    printIndex(index);
    std::cout << "当前cut版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPasteversion(int index) {
    std::string result = showExec("paste --version | head -n 1");
    printIndex(index);
    std::cout << "当前paste版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSplitversion(int index) {
    std::string result = showExec("split --version | head -n 1");
    printIndex(index);
    std::cout << "当前split版本信息如下：" << result;
    return RE_SUCCESS;
}

int showWcversion(int index) {
    std::string result = showExec("wc --version | head -n 1");
    printIndex(index);
    std::cout << "当前wc版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTruncateversion(int index) {
    std::string result = showExec("truncate --version | head -n 1");
    printIndex(index);
    std::cout << "当前truncate版本信息如下：" << result;
    return RE_SUCCESS;
}

int showShufversion(int index) {
    std::string result = showExec("shuf --version | head -n 1");
    printIndex(index);
    std::cout << "当前shuf版本信息如下：" << result;
    return RE_SUCCESS;
}

int showYesversion(int index) {
    std::string result = showExec("yes --version | head -n 1");
    printIndex(index);
    std::cout << "当前yes版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDateversion(int index) {
    std::string result = showExec("date --version | head -n 1");
    printIndex(index);
    std::cout << "当前date版本信息如下：" << result;
    return RE_SUCCESS;
}

int showExprversion(int index) {
    std::string result = showExec("expr --version | head -n 1");
    printIndex(index);
    std::cout << "当前expr版本信息如下：" << result;
    return RE_SUCCESS;
}

int showFactorversion(int index) {
    std::string result = showExec("factor --version | head -n 1");
    printIndex(index);
    std::cout << "当前factor版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSeqversion(int index) {
    std::string result = showExec("seq --version | head -n 1");
    printIndex(index);
    std::cout << "当前seq版本信息如下：" << result;
    return RE_SUCCESS;
}

int showNlversion(int index) {
    std::string result = showExec("nl --version | head -n 1");
    printIndex(index);
    std::cout << "当前nl版本信息如下：" << result;
    return RE_SUCCESS;
}

int showBasenameversion(int index) {
    std::string result = showExec("basename --version | head -n 1");
    printIndex(index);
    std::cout << "当前basename版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDirnameversion(int index) {
    std::string result = showExec("dirname --version | head -n 1");
    printIndex(index);
    std::cout << "当前dirname版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIdversion(int index) {
    std::string result = showExec("id --version | head -n 1");
    printIndex(index);
    std::cout << "当前id版本信息如下：" << result;
    return RE_SUCCESS;
}

int showWhoamiversion(int index) {
    std::string result = showExec("whoami --version | head -n 1");
    printIndex(index);
    std::cout << "当前whoami版本信息如下：" << result;
    return RE_SUCCESS;
}

int showGroupsversion(int index) {
    std::string result = showExec("groups --version | head -n 1");
    printIndex(index);
    std::cout << "当前groups版本信息如下：" << result;
    return RE_SUCCESS;
}

int showUsersversion(int index) {
    std::string result = showExec("users --version | head -n 1");
    printIndex(index);
    std::cout << "当前users版本信息如下：" << result;
    return RE_SUCCESS;
}

int showUnameversion(int index) {
    std::string result = showExec("uname --version | head -n 1");
    printIndex(index);
    std::cout << "当前uname版本信息如下：" << result;
    return RE_SUCCESS;
}

int showArchversion(int index) {
    std::string result = showExec("arch --version | head -n 1");
    printIndex(index);
    std::cout << "当前arch版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTimeoutversion(int index) {
    std::string result = showExec("timeout --version | head -n 1");
    printIndex(index);
    std::cout << "当前timeout版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLinkversion(int index) {
    std::string result = showExec("link --version | head -n 1");
    printIndex(index);
    std::cout << "当前link版本信息如下：" << result;
    return RE_SUCCESS;
}

int showReadlinkversion(int index) {
    std::string result = showExec("readlink --version | head -n 1");
    printIndex(index);
    std::cout << "当前readlink版本信息如下：" << result;
    return RE_SUCCESS;
}

int showRealpathversion(int index) {
    std::string result = showExec("realpath --version | head -n 1");
    printIndex(index);
    std::cout << "当前realpath版本信息如下：" << result;
    return RE_SUCCESS;
}

int showFileversion(int index) {
    std::string result = showExec("file --version | head -n 1");
    printIndex(index);
    std::cout << "当前file版本信息如下：" << result;
    return RE_SUCCESS;
}

int showFoldversion(int index) {
    std::string result = showExec("fold --version | head -n 1");
    printIndex(index);
    std::cout << "当前fold版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPrversion(int index) {
    std::string result = showExec("pr --version | head -n 1");
    printIndex(index);
    std::cout << "当前pr版本信息如下：" << result;
    return RE_SUCCESS;
}

int showWatchversion(int index) {
    std::string result = showExec("watch --version");
    printIndex(index);
    std::cout << "当前watch版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLogrotateversion(int index) {
    std::string result = showExec("logrotate --version | head -n 1");
    printIndex(index);
    std::cout << "当前logrotate版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSysctlversion(int index) {
    std::string result = showExec("sysctl --version | head -n 1");
    printIndex(index);
    std::cout << "当前sysctl版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLocaleversion(int index) {
    std::string result = showExec("locale --version | head -n 1");
    printIndex(index);
    std::cout << "当前locale版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTtyversion(int index) {
    std::string result = showExec("tty --version | head -n 1");
    printIndex(index);
    std::cout << "当前tty版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSsversion(int index) {
    std::string result = showExec("ss --version | head -n 1");
    printIndex(index);
    std::cout << "当前ss版本信息如下：" << result;
    return RE_SUCCESS;
}

int showArpversion(int index) {
    std::string result = showExec("arp -V | head -n 1");
    printIndex(index);
    std::cout << "当前arp版本信息如下：" << result;
    return RE_SUCCESS;
}

int showRouteversion(int index) {
    std::string result = showExec("route -V | head -n 1");
    printIndex(index);
    std::cout << "当前route版本信息如下：" << result;
    return RE_SUCCESS;
}

int showNmcliversion(int index) {
    std::string result = showExec("nmcli --version | head -n 1");
    printIndex(index);
    std::cout << "当前nmcli版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPing6version(int index) {
    std::string result = showExec("ping6 -V | head -n 1");
    printIndex(index);
    std::cout << "当前ping6版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIp6tablesversion(int index) {
    std::string result = showExec("ip6tables --version | head -n 1");
    printIndex(index);
    std::cout << "当前ip6tables版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIptablesSaveversion(int index) {
    std::string result = showExec("iptables-save --version | head -n 1");
    printIndex(index);
    std::cout << "当前iptables-save版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIptablesRestoreversion(int index) {
    std::string result = showExec("iptables-restore --version | head -n 1");
    printIndex(index);
    std::cout << "当前iptables-restore版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMkfsversion(int index) {
    std::string result = showExec("mkfs --version | head -n 1");
    printIndex(index);
    std::cout << "当前mkfs版本信息如下：" << result;
    return RE_SUCCESS;
}

int showFsckversion(int index) {
    std::string result = showExec("fsck --version | head -n 1");
    printIndex(index);
    std::cout << "当前fsck版本信息如下：" << result;
    return RE_SUCCESS;
}

int showBlkidversion(int index) {
    std::string result = showExec("blkid --version | head -n 1");
    printIndex(index);
    std::cout << "当前blkid版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPartedversion(int index) {
    std::string result = showExec("parted --version | head -n 1");
    printIndex(index);
    std::cout << "当前parted版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLsblkversion(int index) {
    std::string result = showExec("lsblk --version | head -n 1");
    printIndex(index);
    std::cout << "当前lsblk版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMktempversion(int index) {
    std::string result = showExec("mktemp --version | head -n 1");
    printIndex(index);
    std::cout << "当前mktemp版本信息如下：" << result;
    return RE_SUCCESS;
}

int showChrootversion(int index) {
    std::string result = showExec("chroot --version | head -n 1");
    printIndex(index);
    std::cout << "当前chroot版本信息如下：" << result;
    return RE_SUCCESS;
}

int showNiceversion(int index) {
    std::string result = showExec("nice --version | head -n 1");
    printIndex(index);
    std::cout << "当前nice版本信息如下：" << result;
    return RE_SUCCESS;
}

int showReniceversion(int index) {
    std::string result = showExec("renice --version | head -n 1");
    printIndex(index);
    std::cout << "当前renice版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPkillversion(int index) {
    std::string result = showExec("pkill --version | head -n 1");
    printIndex(index);
    std::cout << "当前pkill版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPgrepversion(int index) {
    std::string result = showExec("pgrep --version | head -n 1");
    printIndex(index);
    std::cout << "当前pgrep版本信息如下：" << result;
    return RE_SUCCESS;
}

int showXargsversion(int index) {
    std::string result = showExec("xargs --version | head -n 1");
    printIndex(index);
    std::cout << "当前xargs版本信息如下：" << result;
    return RE_SUCCESS;
}

int showStringsversion(int index) {
    std::string result = showExec("strings --version | head -n 1");
    printIndex(index);
    std::cout << "当前strings版本信息如下：" << result;
    return RE_SUCCESS;
}

int showHexdumpversion(int index) {
    std::string result = showExec("hexdump --version | head -n 1");
    printIndex(index);
    std::cout << "当前hexdump版本信息如下：" << result;
    return RE_SUCCESS;
}

int showObjdumpversion(int index) {
    std::string result = showExec("objdump --version | head -n 1");
    printIndex(index);
    std::cout << "当前objdump版本信息如下：" << result;
    return RE_SUCCESS;
}

int showReadelfversion(int index) {
    std::string result = showExec("readelf --version | head -n 1");
    printIndex(index);
    std::cout << "当前readelf版本信息如下：" << result;
    return RE_SUCCESS;
}

int showNmversion(int index) {
    std::string result = showExec("nm --version | head -n 1");
    printIndex(index);
    std::cout << "当前nm版本信息如下：" << result;
    return RE_SUCCESS;
}

int showLdconfigversion(int index) {
    std::string result = showExec("ldconfig --version | head -n 1");
    printIndex(index);
    std::cout << "当前ldconfig版本信息如下：" << result;
    return RE_SUCCESS;
}

int showArversion(int index) {
    std::string result = showExec("ar --version | head -n 1");
    printIndex(index);
    std::cout << "当前ar版本信息如下：" << result;
    return RE_SUCCESS;
}

int showRanlibversion(int index) {
    std::string result = showExec("ranlib --version | head -n 1");
    printIndex(index);
    std::cout << "当前ranlib版本信息如下：" << result;
    return RE_SUCCESS;
}

int showStripversion(int index) {
    std::string result = showExec("strip --version | head -n 1");
    printIndex(index);
    std::cout << "当前strip版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSizeversion(int index) {
    std::string result = showExec("size --version | head -n 1");
    printIndex(index);
    std::cout << "当前size版本信息如下：" << result;
    return RE_SUCCESS;
}

int showAsversion(int index) {
    std::string result = showExec("as --version | head -n 1");
    printIndex(index);
    std::cout << "当前as版本信息如下：" << result;
    return RE_SUCCESS;
}

int showIconvversion(int index) {
    std::string result = showExec("iconv --version | head -n 1");
    printIndex(index);
    std::cout << "当前iconv版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMsgfmtversion(int index) {
    std::string result = showExec("msgfmt --version | head -n 1");
    printIndex(index);
    std::cout << "当前msgfmt版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMsgmergeversion(int index) {
    std::string result = showExec("msgmerge --version | head -n 1");
    printIndex(index);
    std::cout << "当前msgmerge版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMsgenversion(int index) {
    std::string result = showExec("msgen --version | head -n 1");
    printIndex(index);
    std::cout << "当前msgen版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMsgcmpversion(int index) {
    std::string result = showExec("msgcmp --version | head -n 1");
    printIndex(index);
    std::cout << "当前msgcmp版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMsgconvversion(int index) {
    std::string result = showExec("msgconv --version | head -n 1");
    printIndex(index);
    std::cout << "当前msgconv版本信息如下：" << result;
    return RE_SUCCESS;
}

int showMsgcatversion(int index) {
    std::string result = showExec("msgcat --version | head -n 1");
    printIndex(index);
    std::cout << "当前msgcat版本信息如下：" << result;
    return RE_SUCCESS;
}

int showXgettextversion(int index) {
    std::string result = showExec("xgettext --version | head -n 1");
    printIndex(index);
    std::cout << "当前xgettext版本信息如下：" << result;
    return RE_SUCCESS;
}

int showCommversion(int index) {
    std::string result = showExec("comm --version | head -n 1");
    printIndex(index);
    std::cout << "当前comm版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDiffversion(int index) {
    std::string result = showExec("diff --version | head -n 1");
    printIndex(index);
    std::cout << "当前diff版本信息如下：" << result;
    return RE_SUCCESS;
}

int showCmpversion(int index) {
    std::string result = showExec("cmp --version | head -n 1");
    printIndex(index);
    std::cout << "当前cmp版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPatchversion(int index) {
    std::string result = showExec("patch --version | head -n 1");
    printIndex(index);
    std::cout << "当前patch版本信息如下：" << result;
    return RE_SUCCESS;
}

int showDirversion(int index) {
    std::string result = showExec("dir --version | head -n 1");
    printIndex(index);
    std::cout << "当前dir版本信息如下：" << result;
    return RE_SUCCESS;
}

int showVdirversion(int index) {
    std::string result = showExec("vdir --version | head -n 1");
    printIndex(index);
    std::cout << "当前vdir版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTouchversion(int index) {
    std::string result = showExec("touch --version | head -n 1");
    printIndex(index);
    std::cout << "当前touch版本信息如下：" << result;
    return RE_SUCCESS;
}

int showEnvversion(int index) {
    std::string result = showExec("env --version | head -n 1");
    printIndex(index);
    std::cout << "当前env版本信息如下：" << result;
    return RE_SUCCESS;
}

int showPrintenvversion(int index) {
    std::string result = showExec("printenv --version | head -n 1");
    printIndex(index);
    std::cout << "当前printenv版本信息如下：" << result;
    return RE_SUCCESS;
}

int showSleepversion(int index) {
    std::string result = showExec("sleep --version | head -n 1");
    printIndex(index);
    std::cout << "当前sleep版本信息如下：" << result;
    return RE_SUCCESS;
}

int showTsortversion(int index) {
    std::string result = showExec("tsort --version | head -n 1");
    printIndex(index);
    std::cout << "当前tsort版本信息如下：" << result;
    return RE_SUCCESS;
}

int showUnlinkversion(int index) {
    std::string result = showExec("unlink --version | head -n 1");
    printIndex(index);
    std::cout << "当前unlink版本信息如下：" << result;
    return RE_SUCCESS;
}


#define CHECK_PORT(port, name) \
    int show##name(int index) { \
    std::string result = showExec("PORT=" #port "; netstat -tuln | grep -q \":$PORT \" && echo \"占用\" || echo \"没占用\""); \
    printIndex(index); \
    std::cout << #name "端口占用情况如下：" << result; \
    return RE_SUCCESS; \
    }

CHECK_PORT(3306, Mysqlport)
CHECK_PORT(80, Httpport)
CHECK_PORT(443, Httpsport)
CHECK_PORT(22, Sshport)
CHECK_PORT(21, Ftpport)
CHECK_PORT(25, Smtpport)
CHECK_PORT(53, Dnsport)
CHECK_PORT(67, Dhcpport)
CHECK_PORT(110, Pop3port)
CHECK_PORT(143, Imapport)
CHECK_PORT(23, Telnetport)
CHECK_PORT(389, Ldapport)
CHECK_PORT(445, Smbport)
CHECK_PORT(3389, Rdpport)
CHECK_PORT(5432, Pgport)
CHECK_PORT(6379, Redisport)
CHECK_PORT(27017, Mongodbport)
CHECK_PORT(11211, Memcachedport)
CHECK_PORT(9092, Kafkaport)
CHECK_PORT(9200, Elasticport)
CHECK_PORT(123, Ntpport)
CHECK_PORT(161, Snmpport)
CHECK_PORT(465, Smtpsport)
CHECK_PORT(993, Imapsport)
CHECK_PORT(995, Pop3sport)
CHECK_PORT(636, Ldapsport)
CHECK_PORT(514, Syslogport)
CHECK_PORT(179, Bgpport)
CHECK_PORT(6667, Ircport)
CHECK_PORT(1433, Mssqlport)
CHECK_PORT(1812, Radiusport)
CHECK_PORT(5900, Vncport)
CHECK_PORT(2181, Zkport)
CHECK_PORT(1194, Openvpnport)
CHECK_PORT(3128, Proxyport)
CHECK_PORT(8080, Squidport)
CHECK_PORT(8080, Tomcatport)
CHECK_PORT(7001, Weblogicport)
CHECK_PORT(5672, Rabbitmqport)
CHECK_PORT(5000, Dockerregistryport)
CHECK_PORT(9418, Gitport)
CHECK_PORT(6881, Btport)
CHECK_PORT(873, Rsyncport)
CHECK_PORT(7990, Bitbucketport)
CHECK_PORT(9000, Sonarport)
CHECK_PORT(8080, Jenkinsport)
CHECK_PORT(3000, Grafanaport)
CHECK_PORT(9090, Prometheusport)
CHECK_PORT(8500, Consulport)
CHECK_PORT(8200, Vaultport)
CHECK_PORT(6443, Kubeapiport)
CHECK_PORT(10250, Kubeletport)
CHECK_PORT(10251, Kubeschedulerport)
CHECK_PORT(10252, Kubecontrollerport)
CHECK_PORT(2379, Etcdport)
CHECK_PORT(4646, Nomadport)
CHECK_PORT(8080, Traefikport)
CHECK_PORT(80, Nginxport)
CHECK_PORT(80, Apacheport)
CHECK_PORT(8404, Haproxyport)
CHECK_PORT(6789, Cephmonport)
CHECK_PORT(6800, Cephosdport)
CHECK_PORT(6801, Cephmdsport)
CHECK_PORT(9042, Cassandraport)
CHECK_PORT(26257, Cockroachport)
CHECK_PORT(8200, Elasticapmport)
CHECK_PORT(8123, Clickhouseport)
CHECK_PORT(4222, Natsport)
CHECK_PORT(2379, Etcdclientport)
CHECK_PORT(2380, Etcdpeerport)
CHECK_PORT(8080, Keycloakport)
CHECK_PORT(443, Harborport)
CHECK_PORT(8065, Mattermostport)
CHECK_PORT(3000, Metabaseport)
CHECK_PORT(8081, Nexusport)
CHECK_PORT(3000, Giteaport)
CHECK_PORT(9000, Sentryport)
CHECK_PORT(8686, Vectorport)
CHECK_PORT(3100, Lokiport)
CHECK_PORT(9000, Minioport)
CHECK_PORT(8201, Vaultagentport)
CHECK_PORT(9200, Opensearchport)
CHECK_PORT(5984, Couchdbport)
CHECK_PORT(50070, Hadoopnamenodeport)
CHECK_PORT(50075, Hadoopdatanodeport)
CHECK_PORT(60000, Hbmasterport)
CHECK_PORT(60020, Hbregionport)
CHECK_PORT(24224, Fluentdport)
CHECK_PORT(1883, Mqttport)
CHECK_PORT(9000, Graylogport)
CHECK_PORT(6379, Keydbport)
CHECK_PORT(7474, Neo4jport)
CHECK_PORT(8529, Arangodbport)
CHECK_PORT(8200, Vaultapiport)
CHECK_PORT(10902, Thanosqueryport)
CHECK_PORT(10901, Thanosstoreport)
CHECK_PORT(10900, Thanossidecarport)



#define CHECK_VERSION(cmd, name) \
    int show##name(int index) { \
    std::string result = showExec(cmd " --version 2>&1 || " cmd " -v 2>&1 || echo \"无法获取版本信息或命令不存在\""); \
    printIndex(index); \
    std::cout << #name "版本如下：\n" << result; \
    return RE_SUCCESS; \
    }

// 版本管理工具
CHECK_VERSION("git", Gitversion)
CHECK_VERSION("docker", Dockerversion)
CHECK_VERSION("kubectl", Kubectlversion)
CHECK_VERSION("helm", Helmversion)

// 编程语言及其工具链
CHECK_VERSION("go", Goversion)
CHECK_VERSION("python3", Pythonversion) // 优先尝试python3
CHECK_VERSION("node", Nodeversion)
CHECK_VERSION("npm", Npmversion)
CHECK_VERSION("java", Javajdkversion)
CHECK_VERSION("mvn", Mavenversion)
CHECK_VERSION("gradle", Gradleversion)
CHECK_VERSION("php", Phpversion)
CHECK_VERSION("ruby", Rubyversion)
CHECK_VERSION("perl", Perlversion)
CHECK_VERSION("rustc", Rustcversion)
CHECK_VERSION("gcc", Gccversion)
CHECK_VERSION("g++", Gplusplusversion)

// 构建工具
CHECK_VERSION("make", Makeversion)
CHECK_VERSION("cmake", CMakeversion)
CHECK_VERSION("autoconf", Autoconfversion)
CHECK_VERSION("automake", Automakeversion)
CHECK_VERSION("libtool", Libtoolversion)
CHECK_VERSION("pkg-config", Pkgconfigversion)

// 包管理器
CHECK_VERSION("dnf", Dnfversion)
CHECK_VERSION("yum", Yumversion)
CHECK_VERSION("apt", Aptversion)
CHECK_VERSION("zypper", Zypperversion)
CHECK_VERSION("pacman", Pacmanversion)
CHECK_VERSION("rpm", Rpmversion)
CHECK_VERSION("dpkg", Dpkmversion)

// 系统及网络工具
CHECK_VERSION("sudo", Sudoversion)
CHECK_VERSION("su", Suversion)
CHECK_VERSION("ssh", Sshversion)
CHECK_VERSION("scp", Scpversion)
CHECK_VERSION("sftp", Sftpversion)
CHECK_VERSION("rsync", Rsyncversion)
CHECK_VERSION("pwd", Pwdversion)
CHECK_VERSION("mkdir", Mkdirversion)
CHECK_VERSION("rmdir", Rmdirversion)
CHECK_VERSION("cpio", Cpioversion)
CHECK_VERSION("dd", Ddversion)
CHECK_VERSION("od", Odversion)
CHECK_VERSION("rev", Revversion)



CHECK_VERSION("host", Hostversion)
CHECK_VERSION("nslookup", Nslookupversion)
CHECK_VERSION("dig", Digversion)
CHECK_VERSION("netstat", Netstatversion) // 尽管netstat在一些新发行版被ip取代，但仍常见
CHECK_VERSION("tcpdump", Tcpdumpversion)
CHECK_VERSION("iperf3", Iperf3version)
CHECK_VERSION("lsof", Lsofversion)

// 磁盘和文件系统工具
CHECK_VERSION("fdisk", Fdiskversion)
CHECK_VERSION("gparted", Gpartedversion) // 通常是GUI工具，但CLI可能存在
CHECK_VERSION("mdadm", Mdadmversion)
CHECK_VERSION("lvm", Lvmversion) // lvm命令本身可能没有--version，但其子命令有
CHECK_VERSION("vgdisplay", Vgdisplayversion)
CHECK_VERSION("lvdisplay", Lvdisplayversion)
CHECK_VERSION("pvdisplay", Pvdisplayversion)
CHECK_VERSION("xfs_info", Xfsinfoversion) // xfs文件系统工具
CHECK_VERSION("btrfs", Btrfsversion)
CHECK_VERSION("zfs", Zfsversion)
CHECK_VERSION("umount", Umountversion)
CHECK_VERSION("swapon", Swaponversion)
CHECK_VERSION("swapoff", Swapoffversion)
CHECK_VERSION("mkswap", Mkswapversion)

// 用户和组管理
CHECK_VERSION("useradd", Useraddversion)
CHECK_VERSION("userdel", Userdelversion)
CHECK_VERSION("usermod", Usermodversion)
CHECK_VERSION("groupadd", Groupaddversion)
CHECK_VERSION("groupdel", Groupdelversion)
CHECK_VERSION("groupmod", Groupmodversion)
CHECK_VERSION("passwd", Passwdversion)
CHECK_VERSION("chage", Chageversion)
CHECK_VERSION("pwck", Pwckversion)
CHECK_VERSION("grpck", Grpckversion)

// 计划任务
CHECK_VERSION("crontab", Crontabversion)
CHECK_VERSION("at", Atversion)

// 系统服务和日志管理
CHECK_VERSION("systemctl", Systemctlversion)
CHECK_VERSION("journalctl", Journalctlversion)
CHECK_VERSION("rsyslogd", Rsyslogdversion)
CHECK_VERSION("aureport", Aureportversion) // auditd相关

// 安全工具
CHECK_VERSION("setenforce", Setenforceversion)
CHECK_VERSION("getenforce", Getenforceversion)
CHECK_VERSION("sestatus", Sestatusversion)
CHECK_VERSION("firewall-cmd", Firewalldversion) // firewalld的CLI命令
CHECK_VERSION("ufw", Ufwversion)
CHECK_VERSION("apparmor_status", Apparmorversion) // AppArmor相关

// 虚拟化工具
CHECK_VERSION("vagrant", Vagrantversion)
CHECK_VERSION("VBoxManage", Virtualboxversion) // VirtualBox的命令行工具
CHECK_VERSION("vmware", Vmwareversion) // VMware相关命令行工具（例如vmware-installer等，取决于具体安装）

CHECK_VERSION("qemu-system-x86_64", Qemuversion) // QEMU通常以具体系统类型命令存在
CHECK_VERSION("kvm-ok", Kvmversion) // 检查KVM是否可用，通常不直接显示版本
CHECK_VERSION("virsh", Libvirtversion) // libvirt的CLI
CHECK_VERSION("virt-install", Virtinstversion)
CHECK_VERSION("virt-manager", Virtmanagerversion) // 通常是GUI，但命令可能存在

// 网络工具 (续)
CHECK_VERSION("iptables-restore", Iptablesrestoreversion)
CHECK_VERSION("iptables-save", Iptablessaveversion)
CHECK_VERSION("ip6tables-restore", Ip6tablesrestoreversion)
CHECK_VERSION("ip6tables-save", Ip6tablessaveversion)
CHECK_VERSION("traceroute", Tracerouteversion)
CHECK_VERSION("mtr", Mtrversion)
CHECK_VERSION("openssl", Ssltlsversion) // 通用SSL/TLS库，此处用openssl代替
CHECK_VERSION("nmap", Nmapversion)
CHECK_VERSION("nc", Netcatversion) // netcat
CHECK_VERSION("socat", Socatversion)
CHECK_VERSION("openvpn", Openvpnversion)
CHECK_VERSION("wg", Wireguardversion) // wireguard的CLI

// 网络模拟与分析
CHECK_VERSION("gns3", Gns3version)
CHECK_VERSION("wireshark", Wiresharkversion) // 通常是GUI，但命令行工具有版本
CHECK_VERSION("tshark", Tsharkversion)

// Systemd 衍生服务
CHECK_VERSION("systemd-resolve", Systemdresolveversion)
CHECK_VERSION("systemd-networkd", Systemdnetworkdversion)
CHECK_VERSION("systemd-timesyncd", Systemdtimesyncdversion)

// 时间同步
CHECK_VERSION("chronyc", Chronyversion)
CHECK_VERSION("ntpdate", Ntpdateversion)
CHECK_VERSION("ntpq", Ntpqversion)
CHECK_VERSION("ntpd", Ntpversion)

// 容器编排与自动化 (续)
CHECK_VERSION("docker-compose", Dockercomposeversion)
CHECK_VERSION("docker stack", Dockerstackversion) // docker子命令
CHECK_VERSION("docker info", Dockerdaemonversion) // 获取docker daemon信息，间接含版本
CHECK_VERSION("kubeadm", Kubeverseversion) // kubeadm version

// 云平台和DevOps工具
CHECK_VERSION("oc", Openshiftversion) // OpenShift CLI
CHECK_VERSION("terraform", Terraformversion)
CHECK_VERSION("ansible", Ansibleversion)
CHECK_VERSION("puppet", Puppetversion)
CHECK_VERSION("chef", Chefversion)
CHECK_VERSION("salt-call", Saltversion) // SaltStack
CHECK_VERSION("packer", Packerversion)
CHECK_VERSION("vagrant plugin", Vagrantpluginsversion) // vagrant子命令
CHECK_VERSION("cloud-init", Cloudinitversion)

// 云服务提供商CLI
CHECK_VERSION("aws", Ec2cliversion) // AWS CLI
CHECK_VERSION("az", Azcliversion) // Azure CLI
CHECK_VERSION("gcloud", Gcloudversion) // Google Cloud CLI
CHECK_VERSION("aliyun", Alishversion) // Alibaba Cloud CLI (假设别名)
CHECK_VERSION("tccli", Tencentshellversion) // Tencent Cloud CLI (假设)
CHECK_VERSION("huaweicloud", Huaweiocversion) // Huawei Cloud CLI (假设)
CHECK_VERSION("oci", Ociversion) // Oracle Cloud CLI
CHECK_VERSION("openstack", Openstackclientversion) // OpenStack CLI


// 存储系统
CHECK_VERSION("ceph", Cephversion)
CHECK_VERSION("glusterfs", Glusterversion)
CHECK_VERSION("showmount", Nfsversion) // nfs-utils通常用showmount检查
CHECK_VERSION("smbclient", Sambaversion)
CHECK_VERSION("lfs", Lustreversion) // Lustre文件系统客户端

// 大数据组件
CHECK_VERSION("hadoop", Hadoopversion)
CHECK_VERSION("spark-shell", Sparkversion)
CHECK_VERSION("hbase", Hbaseversion)
CHECK_VERSION("hive", Hiveversion)
CHECK_VERSION("flink", Flinkversion)
CHECK_VERSION("kafka-topics.sh", Kafkaversion) // Kafka工具，取其中一个代表
CHECK_VERSION("zkCli.sh", Zookeepercliversion) // Zookeeper客户端

// 分布式协调/配置
CHECK_VERSION("etcdctl", Etcdctlversion)
CHECK_VERSION("consul", Consulclientversion)
CHECK_VERSION("vault", Vaultcliversion)

// 消息队列
CHECK_VERSION("rabbitmqctl", Rabbitmqctlversion)

// Web服务器/代理/负载均衡
CHECK_VERSION("nginx", Nginxversion)
CHECK_VERSION("httpd", Apacheversion)
CHECK_VERSION("lighttpd", Lighttpdversion)
CHECK_VERSION("catalina.sh", Tomcatcatalinaversion) // Tomcat版本
CHECK_VERSION("jboss-cli.sh", Jbosscliversion) // JBoss CLI
CHECK_VERSION("wildfly-cli.sh", Wildflycliversin) // Wildfly CLI
CHECK_VERSION("squid", Squidversion)
CHECK_VERSION("haproxy", Haproxyversion)
CHECK_VERSION("keepalived", Keepalivedversion)

// FTP服务器
CHECK_VERSION("vsftpd", Vsftpdversion)
CHECK_VERSION("proftpd", Proftpdversion)
CHECK_VERSION("pure-ftpd", Pureftpdversion)

// SSH服务
CHECK_VERSION("sshd", Sshdversion) // sshd daemon，通常没有直接的版本参数

// 其他特定应用
CHECK_VERSION("nginx -V", Nginxrtmpversion) // Nginx RTMP模块版本集成在Nginx版本信息中
CHECK_VERSION("docker pull registry", Dockerregistryversion) // 拉取镜像来判断registry版本
CHECK_VERSION("promtool", Prometheusclientversion)
CHECK_VERSION("grafana-cli", Grafanatoolversion)
CHECK_VERSION("amtool", Alertmanagercliversion)

// LDAP客户端工具
CHECK_VERSION("ldapadd", Ldapaddversion)
CHECK_VERSION("ldapsearch", Ldapsearchversion)
CHECK_VERSION("ldapmodify", Ldapmodifyversion)
CHECK_VERSION("ldapdelete", Ldapdeleteversion)

// 数据库客户端
CHECK_VERSION("mysql", Mysqlclientversion)
CHECK_VERSION("psql", Pgclientversion)
CHECK_VERSION("mongo", Mongoclientversion) // MongoDB旧版客户端
CHECK_VERSION("redis-cli", Rediscliversion)

// ELK Stack (通过服务状态或客户端工具)
// 注意：以下这些通常通过API或服务状态获取版本，CLI可能不直接返回版本
// 这里尝试使用可能存在的CLI工具或通用检查方式
CHECK_VERSION("curl -s localhost:9200", Elasticsearchversion) // 尝试获取Elasticsearch服务版本
CHECK_VERSION("kibana-plugin", Kibanacliversion) // Kibana插件管理工具
CHECK_VERSION("logstash-plugin", Logstashcliversion) // Logstash插件管理工具

// 消息队列相关 (续)
CHECK_VERSION("rabbitmq-plugins", Rabbitmqpluginsversion)
CHECK_VERSION("kafka-run-class.sh kafka.tools.ConsoleProducer --version", KafkaToolversion) // 尝试用一个Kafka工具命令

// Zookeeper服务器
CHECK_VERSION("echo stat | nc localhost 2181", ZookeeperServerversion) // 尝试获取Zookeeper服务器状态，间接含版本

// Nginx Plus (通常通过API或特定命令)
CHECK_VERSION("nginx -V", NginxPlusversion) // Nginx Plus的版本信息也在 -V 中，







std::string showExec(const std::string& cmd) {
    std::string result = "";
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) return "ERROR: popen failed!";
    char buffer[128];
    while (!feof(pipe)) {
        if (fgets(buffer, 128, pipe) != nullptr)
            result += buffer;
    }
    pclose(pipe);
    return result;
}


int doEmptytrash(int index)
{
    system("gio trash --empty");
    printIndex(index);
    std::cout << "清理回收站" << "  [已完成]" << std::endl;
    return RE_SUCCESS;
}

int doCheckDiskSpace(int index) {
    std::string result = showExec("df -h . 2>&1");
    printIndex(index);
    std::cout << "Disk Space Check: " << result;
    return RE_SUCCESS;
}

int doShowCurrentWorkingDirectory(int index) {
    std::string result = showExec("pwd 2>&1");
    printIndex(index);
    std::cout << "Current Working Directory: " << result;
    return RE_SUCCESS;
}

int doListNetworkInterfaces(int index) {
    std::string result = showExec("ip -br addr show 2>&1");
    printIndex(index);
    std::cout << "Network Interfaces: " << result;
    return RE_SUCCESS;
}

int doCheckInternetConnectivity(int index) {
    std::string cmd = "ping -c 1 8.8.8.8 > /dev/null 2>&1 && echo \"Connected\" || echo \"Disconnected\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "Internet Connectivity: " << result;
    return (result.find("Connected") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doListSystemUptime(int index) {
    std::string result = showExec("uptime -p 2>&1");
    printIndex(index);
    std::cout << "System Uptime: " << result;
    return RE_SUCCESS;
}

int doGetHostname(int index) {
    std::string result = showExec("hostname 2>&1");
    printIndex(index);
    std::cout << "主机名: " << result;
    return RE_SUCCESS;
}

int doGetKernelArchitecture(int index) {
    std::string result = showExec("uname -m 2>&1");
    printIndex(index);
    std::cout << "内核架构: " << result;
    return RE_SUCCESS;
}

int doGetOsReleaseName(int index) {
    std::string result = showExec("cat /etc/os-release 2>/dev/null | grep '^NAME=' | cut -d'=' -f2 | tr -d '\"' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "操作系统名称: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "操作系统名称: " << result;
    return RE_SUCCESS;
}

int doListUserHomeDirectoryContent(int index) {
    std::string result = showExec("ls -F ~ 2>&1");
    printIndex(index);
    std::cout << "用户主目录内容: \n" << result;
    return RE_SUCCESS;
}

int doGetLoginShell(int index) {
    std::string result = showExec("echo $SHELL 2>&1");
    printIndex(index);
    std::cout << "登录Shell: " << result;
    return RE_SUCCESS;
}

int doGetDefaultGatewayIp(int index) {
    std::string result = showExec("ip r | grep default | awk '{print $3}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "默认网关IP: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "默认网关IP: " << result;
    return RE_SUCCESS;
}

int doCheckDNSServerReachability(int index) {
    std::string cmd = "ping -c 1 1.1.1.1 > /dev/null 2>&1 && echo \"已连接\" || echo \"未连接\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "DNS服务器 (1.1.1.1) 可达性: " << result;
    return (result.find("已连接") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doListAllListeningPorts(int index) {
    std::string result = showExec("ss -tuln 2>&1");
    printIndex(index);
    std::cout << "所有监听端口: \n" << result;
    return RE_SUCCESS;
}

int doShowDiskUsageInCurrentDir(int index) {
    std::string result = showExec("du -sh . 2>&1");
    printIndex(index);
    std::cout << "当前目录磁盘使用情况: " << result;
    return RE_SUCCESS;
}

int doGetCpuCoreCount(int index) {
    std::string result = showExec("nproc 2>&1");
    printIndex(index);
    std::cout << "CPU核心数: " << result;
    return RE_SUCCESS;
}

int doGetTotalSystemMemory(int index) {
    std::string result = showExec("grep MemTotal /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "系统总内存: " << result;
    return RE_SUCCESS;
}

int doGetFreeSystemMemory(int index) {
    std::string result = showExec("grep MemAvailable /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "系统可用内存: " << result;
    return RE_SUCCESS;
}

int doListCurrentlyMountedFilesystems(int index) {
    std::string result = showExec("df -hT 2>&1");
    printIndex(index);
    std::cout << "当前已挂载文件系统: \n" << result;
    return RE_SUCCESS;
}

int doShowLastLoginAttempts(int index) {
    std::string result = showExec("last -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "最近登录尝试: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "最近登录尝试 (最后5条): \n" << result;
    return RE_SUCCESS;
}

int doShowCurrentUser(int index) {
    std::string result = showExec("whoami 2>&1");
    printIndex(index);
    std::cout << "当前用户: " << result;
    return RE_SUCCESS;
}

int doListCurrentUsersGroups(int index) {
    std::string result = showExec("groups 2>&1");
    printIndex(index);
    std::cout << "当前用户所属组: " << result;
    return RE_SUCCESS;
}

int doShowSystemDateAndTime(int index) {
    std::string result = showExec("date 2>&1");
    printIndex(index);
    std::cout << "系统日期和时间: " << result;
    return RE_SUCCESS;
}

int doShowCalendarForCurrentMonth(int index) {
    std::string result = showExec("cal 2>&1");
    printIndex(index);
    std::cout << "本月日历: \n" << result;
    return RE_SUCCESS;
}

int doListRunningProcesses(int index) {
    std::string result = showExec("ps aux --sort=-%cpu | head -n 10 2>&1");
    printIndex(index);
    std::cout << "正在运行的进程 (前10条按CPU使用率): \n" << result;
    return RE_SUCCESS;
}

int doShowCpuLoadAverage(int index) {
    std::string result = showExec("uptime | awk -F'load average:' '{print $2}' 2>&1");
    printIndex(index);
    std::cout << "CPU平均负载: " << result;
    return RE_SUCCESS;
}

int doShowNetworkTrafficStatistics(int index) {
    std::string result = showExec("ip -s link show 2>&1");
    printIndex(index);
    std::cout << "网络流量统计: \n" << result;
    return RE_SUCCESS;
}

int doGetPublicIpAddress(int index) {
    std::string result = showExec("curl -s ifconfig.me 2>&1 || wget -qO- ifconfig.me 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "公网IP地址: 无法获取 (可能未安装curl/wget或无网络连接)。\n";
        return ERROR_PARA;
    }
    std::cout << "公网IP地址: " << result;
    return RE_SUCCESS;
}

int doListEnvironmentVariables(int index) {
    std::string result = showExec("env | head -n 10 2>&1");
    printIndex(index);
    std::cout << "环境变量 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowCurrentUserHistory(int index) {
    std::string result = showExec("history 5 2>&1");
    printIndex(index);
    std::cout << "当前用户命令历史 (最后5条): \n" << result;
    return RE_SUCCESS;
}

int doGetShellName(int index) {
    std::string result = showExec("basename $SHELL 2>&1");
    printIndex(index);
    std::cout << "Shell名称: " << result;
    return RE_SUCCESS;
}

int doCheckServiceStatusSshd(int index) {
    std::string result = showExec("systemctl is-active sshd 2>&1");
    printIndex(index);
    std::cout << "SSHD服务状态: " << result;
    return (result.find("active") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doCheckServiceStatusNginx(int index) {
    std::string result = showExec("systemctl is-active nginx 2>&1");
    printIndex(index);
    std::cout << "Nginx服务状态: " << result;
    return (result.find("active") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doCheckServiceStatusApache2(int index) {
    std::string result = showExec("systemctl is-active apache2 2>&1 || systemctl is-active httpd 2>&1");
    printIndex(index);
    std::cout << "Apache2/HTTPD服务状态: " << result;
    return (result.find("active") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetDefaultBrowserInfo(int index) {
    // This command is highly dependent on desktop environment and specific tools
    // Defaulting to xdg-settings, common on many desktops
    std::string result = showExec("xdg-settings get default-web-browser 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "默认浏览器信息: 无法获取 (可能未安装xdg-utils或无GUI环境)。\n";
        return ERROR_PARA;
    }
    std::cout << "默认浏览器信息: " << result;
    return RE_SUCCESS;
}

int doListAllAliases(int index) {
    std::string result = showExec("alias 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "当前Shell别名: 无。\n";
        return ERROR_PARA;
    }
    std::cout << "当前Shell别名: \n" << result;
    return RE_SUCCESS;
}

int doShowRecentKernelMessages(int index) {
    std::string result = showExec("dmesg | tail -n 10 2>&1");
    printIndex(index);
    std::cout << "最近内核消息 (最后10条): \n" << result;
    return RE_SUCCESS;
}

int doGetProcessCount(int index) {
    std::string result = showExec("ps -e | wc -l 2>&1");
    printIndex(index);
    // wc -l 会包含标题行，减去 1
    long count = 0;
    try {
        count = std::stol(result) - 1;
    } catch (const std::exception& e) {
        std::cout << "进程数量: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "当前进程数量: " << count << "\n";
    return RE_SUCCESS;
}

int doShowKernelVersion(int index) {
    std::string result = showExec("uname -r 2>&1");
    printIndex(index);
    std::cout << "内核版本: " << result;
    return RE_SUCCESS;
}

int doShowAvailableDiskSpaceRoot(int index) {
    std::string result = showExec("df -h / | awk 'NR==2 {print $4}' 2>&1");
    printIndex(index);
    std::cout << "根目录可用磁盘空间: " << result;
    return RE_SUCCESS;
}

int doListCurrentUsersOpenFiles(int index) {
    // lsof without sudo will only show files opened by the current user
    std::string result = showExec("lsof -u $(whoami) | head -n 10 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "当前用户打开的文件: 无 (或lsof未安装/无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "当前用户打开的文件 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemTimeZone(int index) {
    std::string result = showExec("timedatectl show --property=Timezone --value 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统时区: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统时区: " << result;
    return RE_SUCCESS;
}

int doShowCurrentUserDiskQuota(int index) {
    std::string result = showExec("quota -s 2>&1");
    printIndex(index);
    if (result.empty() || result.find("Disk quotas for user") == std::string::npos) {
        std::cout << "当前用户磁盘配额: 未设置或无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "当前用户磁盘配额: \n" << result;
    return RE_SUCCESS;
}

int doListAllPackagesInstalled(int index) {
    std::string cmd = "";
    // Attempt to detect package manager
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "apt list --installed 2>/dev/null | head -n 10";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf list installed 2>/dev/null | head -n 10";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum list installed 2>/dev/null | head -n 10";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Q 2>/dev/null | head -n 10";
    } else {
        printIndex(index);
        std::cout << "所有已安装软件包: 无法获取 (不支持当前包管理器)。\n";
        return ERROR_PARA;
    }
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "所有已安装软件包 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetDefaultRouteInterface(int index) {
    std::string result = showExec("ip r | grep default | awk '{print $5}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "默认路由接口: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "默认路由接口: " << result;
    return RE_SUCCESS;
}

int doGetNetworkSpeedEth0(int index) {
    // This often requires specific tools or parsing /sys/class/net/eth0/speed
    // Example using ethtool (often needs sudo, but some systems might expose info)
    // A more reliable non-sudo method might be reading from /sys if accessible
    std::string result = showExec("cat /sys/class/net/eth0/speed 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "eth0 网速: 无法获取 (需要权限或ethtool未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "eth0 网速: " << result << "Mbps\n";
    return RE_SUCCESS;
}

int doShowSystemBootMessages(int index) {
    std::string result = showExec("journalctl -b | head -n 10 2>&1");
    printIndex(index);
    std::cout << "系统启动消息 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doListUsersInSudoGroup(int index) {
    std::string result = showExec("grep '^sudo:' /etc/group | cut -d: -f4 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "sudo组中的用户: 无 (或sudo组不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "sudo组中的用户: " << result;
    return RE_SUCCESS;
}

int doShowRunningServicesCount(int index) {
    std::string result = showExec("systemctl list-units --type=service --state=running | grep -c running 2>&1");
    printIndex(index);
    std::cout << "正在运行的服务数量: " << result;
    return RE_SUCCESS;
}

int doGetFilesystemTypeRoot(int index) {
    std::string result = showExec("findmnt -n --raw --evaluate --output=FSTYPE / 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "根文件系统类型: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "根文件系统类型: " << result;
    return RE_SUCCESS;
}

int doGetLastBootTime(int index) {
    std::string result = showExec("who -b | awk '{print $3\" \"$4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "上次启动时间: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "上次启动时间: " << result;
    return RE_SUCCESS;
}

int doCheckClipboardContent(int index) {
    // This requires xclip or similar, and typically a GUI session.
    // Highly context-dependent and often requires X server interaction.
    // Providing a placeholder that might fail in non-GUI or non-xclip systems.
    std::string result = showExec("xclip -o -selection clipboard 2>/dev/null || echo \"(无法访问剪贴板或未安装xclip)\"");
    printIndex(index);
    std::cout << "剪贴板内容: " << result;
    if (result.find("(无法访问剪贴板") != std::string::npos) {
        return ERROR_PARA;
    }
    return RE_SUCCESS;
}

int doListUserCronJobs(int index) {
    std::string result = showExec("crontab -l 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户Cron任务: 无。\n";
        return ERROR_PARA;
    }
    std::cout << "用户Cron任务: \n" << result;
    return RE_SUCCESS;
}

int doShowCurrentTerminalType(int index) {
    std::string result = showExec("echo $TERM 2>&1");
    printIndex(index);
    std::cout << "当前终端类型: " << result;
    return RE_SUCCESS;
}

int doGetSystemLocale(int index) {
    std::string result = showExec("locale | grep \"LANG=\" | cut -d'=' -f2 | tr -d '\"' 2>&1");
    printIndex(index);
    std::cout << "系统区域设置 (Locale): " << result;
    return RE_SUCCESS;
}

int doListUserDownloadDirectory(int index) {
    // This typically relies on XDG user directories, common in desktop environments
    std::string result = showExec("xdg-user-dir DOWNLOAD 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户下载目录: 无法获取 (可能未设置XDG目录)。\n";
        return ERROR_PARA;
    }
    std::cout << "用户下载目录: " << result;
    return RE_SUCCESS;
}

int doCountHiddenFilesInHome(int index) {
    std::string result = showExec("find ~ -maxdepth 1 -name \".*\" -type f | wc -l 2>&1");
    printIndex(index);
    std::cout << "主目录中隐藏文件数量: " << result;
    return RE_SUCCESS;
}

int doGetLongestFileNameInCurrentDir(int index) {
    std::string result = showExec("find . -maxdepth 1 -type f -printf '%f\\n' | awk '{ print length, $0 }' | sort -n | tail -n 1 | cut -d' ' -f2- 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "当前目录中最长文件名: 无文件或无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "当前目录中最长文件名: " << result;
    return RE_SUCCESS;
}

int doCheckIfDirectoryIsEmpty(int index) {
    std::string result = showExec("find . -maxdepth 0 -empty -exec echo \"是\" \\; -o -exec echo \"否\" \\; 2>&1");
    printIndex(index);
    std::cout << "当前目录是否为空: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowDiskInodeUsage(int index) {
    std::string result = showExec("df -i . 2>&1");
    printIndex(index);
    std::cout << "磁盘Inode使用情况: \n" << result;
    return RE_SUCCESS;
}

int doGetSystemHostid(int index) {
    std::string result = showExec("hostid 2>&1");
    printIndex(index);
    std::cout << "系统主机ID: " << result;
    return RE_SUCCESS;
}

int doShowCpuModelName(int index) {
    std::string result = showExec("grep 'model name' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU型号名称: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU型号名称: " << result;
    return RE_SUCCESS;
}

int doGetBiosVersion(int index) {
    std::string result = showExec("dmidecode -s bios-version 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "BIOS版本: 无法获取 (可能需要sudo或dmidecode未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "BIOS版本: " << result;
    return RE_SUCCESS;
}

int doListAllBlockDevices(int index) {
    std::string result = showExec("lsblk -o NAME,SIZE,TYPE,MOUNTPOINT -d 2>&1");
    printIndex(index);
    std::cout << "所有块设备: \n" << result;
    return RE_SUCCESS;
}

int doShowOpenFilesCountSystemWide(int index) {
    std::string result = showExec("lsof -n | wc -l 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (const std::exception& e) {
        std::cout << "系统打开文件总数: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统打开文件总数: " << count << "\n";
    return RE_SUCCESS;
}

int doGetMaxNumberOfProcesses(int index) {
    std::string result = showExec("cat /proc/sys/kernel/pid_max 2>&1");
    printIndex(index);
    std::cout << "系统最大进程数: " << result;
    return RE_SUCCESS;
}

int doGetMaxNumberOfOpenFiles(int index) {
    std::string result = showExec("ulimit -n 2>&1");
    printIndex(index);
    std::cout << "当前用户最大打开文件数: " << result;
    return RE_SUCCESS;
}

int doShowSystemRunlevel(int index) {
    std::string result = showExec("runlevel 2>&1 | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统运行级别: 无法获取 (旧版命令或非SysVinit系统)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统运行级别: " << result;
    return RE_SUCCESS;
}

int doGetSystemBootId(int index) {
    std::string result = showExec("cat /proc/sys/kernel/random/boot_id 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统启动ID: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统启动ID: " << result;
    return RE_SUCCESS;
}

int doCheckSwapSpaceUsage(int index) {
    std::string result = showExec("free -h | grep Swap | awk '{print \"总计: \"$2\", 已用: \"$3\", 可用: \"$4}' 2>&1");
    printIndex(index);
    std::cout << "交换空间使用情况: " << result;
    return RE_SUCCESS;
}

int doShowLastSystemReboot(int index) {
    std::string result = showExec("last reboot | head -n 1 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "上次系统重启时间: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "上次系统重启时间: \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkHostname(int index) {
    std::string result = showExec("hostname -f 2>&1"); // Fully qualified domain name
    printIndex(index);
    std::cout << "网络主机名 (FQDN): " << result;
    return RE_SUCCESS;
}

int doShowRoutingTableEntries(int index) {
    std::string result = showExec("ip r 2>&1");
    printIndex(index);
    std::cout << "路由表条目: \n" << result;
    return RE_SUCCESS;
}

int doCheckNetworkInterfaceUpEth0(int index) {
    std::string cmd = "ip link show eth0 up > /dev/null 2>&1 && echo \"已启用\" || echo \"未启用/不存在\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "网卡 eth0 状态: " << result;
    return (result.find("已启用") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doListAllNetworkConnections(int index) {
    std::string result = showExec("ss -atun 2>&1 | head -n 10"); // Active TCP/UDP/UNIX connections
    printIndex(index);
    std::cout << "所有网络连接 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowMemoryCacheUsage(int index) {
    std::string result = showExec("free -h | grep -E 'Mem:|Swap:' | awk '{print \"总计: \"$2\", 已用: \"$3\", 空闲: \"$4\", 共享: \"$5\", 缓存: \"$6\", 可用: \"$7}' 2>&1");
    printIndex(index);
    std::cout << "内存缓存使用情况: \n" << result;
    return RE_SUCCESS;
}

int doGetBatteryStatus(int index) {
    std::string result = showExec("upower -i /org/freedesktop/UPower/devices/battery_BAT0 2>/dev/null | grep -E 'state|percentage' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "电池状态: 无法获取 (可能非笔记本或未安装upower)。\n";
        return ERROR_PARA;
    }
    std::cout << "电池状态: \n" << result;
    return RE_SUCCESS;
}

int doGetMonitorResolution(int index) {
    std::string result = showExec("xdpyinfo | grep dimensions | awk '{print $2}' 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "显示器分辨率: 无法获取 (可能无GUI环境或未安装xdpyinfo)。\n";
        return ERROR_PARA;
    }
    std::cout << "显示器分辨率: " << result;
    return RE_SUCCESS;
}

int doCheckKeyboardLayout(int index) {
    std::string result = showExec("setxkbmap -query | grep layout | awk '{print $2}' 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "键盘布局: 无法获取 (可能无GUI环境或未安装setxkbmap)。\n";
        return ERROR_PARA;
    }
    std::cout << "键盘布局: " << result;
    return RE_SUCCESS;
}

int doGetDesktopEnvironment(int index) {
    std::string result = showExec("echo $XDG_CURRENT_DESKTOP 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "桌面环境: 无法获取 (可能无GUI环境)。\n";
        return ERROR_PARA;
    }
    std::cout << "桌面环境: " << result;
    return RE_SUCCESS;
}

int doShowGraphicalSessionId(int index) {
    std::string result = showExec("loginctl show-session $(loginctl | grep $(whoami) | awk '{print $1}') -p Id 2>/dev/null | cut -d'=' -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "图形会话ID: 无法获取 (可能无GUI环境或非systemd)。\n";
        return ERROR_PARA;
    }
    std::cout << "图形会话ID: " << result;
    return RE_SUCCESS;
}

int doListAllUsersUIDs(int index) {
    std::string result = showExec("cut -d: -f1,3 /etc/passwd | grep -E ':[0-9]{4,}' 2>&1"); // Users with UID >= 1000
    printIndex(index);
    std::cout << "所有用户UID: \n" << result;
    return RE_SUCCESS;
}

int doGetCurrentUserGID(int index) {
    std::string result = showExec("id -g 2>&1");
    printIndex(index);
    std::cout << "当前用户GID: " << result;
    return RE_SUCCESS;
}


int doGetLoginAttemptsSinceBoot(int index) {
    std::string result = showExec("grep 'login' /var/log/auth.log 2>/dev/null | wc -l 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "自启动以来的登录尝试次数: 无法获取日志或无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "自启动以来的登录尝试次数: " << result;
    return RE_SUCCESS;
}

int doShowFailedLoginAttempts(int index) {
    std::string result = showExec("lastb | head -n 5 2>&1"); // Show last 5 bad login attempts
    printIndex(index);
    if (result.empty() || result.find("wtmp begins") != std::string::npos) {
        std::cout << "失败登录尝试: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "失败登录尝试 (最后5条): \n" << result;
    return RE_SUCCESS;
}

int doListAllSystemGroups(int index) {
    std::string result = showExec("cat /etc/group 2>&1 | cut -d: -f1 | head -n 20");
    printIndex(index);
    std::cout << "所有系统组 (前20条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemdUnitFilesCount(int index) {
    std::string result = showExec("systemctl list-unit-files --no-pager | wc -l 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result) -1; // subtract header
    } catch (const std::exception& e) {
        std::cout << "Systemd单元文件数量: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd单元文件数量: " << count << "\n";
    return RE_SUCCESS;
}

int doShowCpuTemperature(int index) {
    std::string result = showExec("sensors | grep 'Core' | head -n 1 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU温度: 无法获取 (可能未安装sensors或硬件不支持)。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU温度: " << result;
    return RE_SUCCESS;
}

int doShowGpuInformation(int index) {
    // This often requires lspci and parsing, or specific vendor tools (e.g., nvidia-smi, amdgpuinfo)
    std::string result = showExec("lspci -vnn | grep -i VGA -A 12 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "GPU信息: 无法获取 (可能无GPU或lspci权限不足)。\n";
        return ERROR_PARA;
    }
    std::cout << "GPU信息 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetSoundCardInfo(int index) {
    std::string result = showExec("aplay -l 2>/dev/null | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "声卡信息: 无法获取 (可能无声卡或aplay未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "声卡信息 (部分): \n" << result;
    return RE_SUCCESS;
}

int doListUsbDevices(int index) {
    std::string result = showExec("lsusb 2>&1");
    printIndex(index);
    std::cout << "USB设备: \n" << result;
    return RE_SUCCESS;
}

int doListPciDevices(int index) {
    std::string result = showExec("lspci 2>&1");
    printIndex(index);
    std::cout << "PCI设备: \n" << result;
    return RE_SUCCESS;
}

int doShowCpuFrequency(int index) {
    std::string result = showExec("lscpu | grep 'CPU MHz:' | awk '{print $3\" MHz\"}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU频率: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU频率: " << result;
    return RE_SUCCESS;
}

int doGetMemorySlotsInfo(int index) {
    std::string result = showExec("dmidecode --type memory 2>/dev/null | grep -E 'Size:|Speed:|Type:|Locator:|Manufacturer:' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "内存插槽信息: 无法获取 (可能需要sudo或dmidecode未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "内存插槽信息 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowSystemVoltage(int index) {
    // Typically requires lm-sensors and reading specific sensor outputs.
    // This is highly hardware dependent and often needs sudo for full access.
    std::string result = showExec("sensors | grep 'Vcc' | head -n 1 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统电压: 无法获取 (可能未安装sensors或硬件不支持)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统电压 (部分): " << result;
    return RE_SUCCESS;
}

int doGetFanSpeed(int index) {
    // Requires lm-sensors.
    std::string result = showExec("sensors | grep 'Fan' | head -n 1 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "风扇速度: 无法获取 (可能未安装sensors或硬件不支持)。\n";
        return ERROR_PARA;
    }
    std::cout << "风扇速度 (部分): " << result;
    return RE_SUCCESS;
}

int doGetDiskTemperature(int index) {
    // Requires hddtemp or smartctl, often needs sudo.
    // Providing a very basic attempt that might fail.
    std::string result = showExec("sudo hddtemp /dev/sda 2>/dev/null | head -n 1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘温度: 无法获取 (可能需要sudo或hddtemp/smartctl未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘温度: " << result;
    return RE_SUCCESS;
}

int doShowNetworkBandwidthUsage(int index) {
    // Requires iftop, nload, or similar which often needs sudo or are more complex.
    // This command is a basic snapshot. For live data, specific tools are needed.
    std::string result = showExec("cat /proc/net/dev | tail -n 1 | awk '{print \"RX: \" $2 \" bytes, TX: \" $10 \" bytes\"}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网络带宽使用: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "网络带宽使用 (概览): " << result;
    return RE_SUCCESS;
}

int doCheckPrinterStatus(int index) {
    std::string result = showExec("lpstat -p 2>&1");
    printIndex(index);
    if (result.empty() || result.find("no destinations added") != std::string::npos) {
        std::cout << "打印机状态: 未配置或无打印机。\n";
        return ERROR_PARA;
    }
    std::cout << "打印机状态: \n" << result;
    return RE_SUCCESS;
}

int doListAllInstalledFonts(int index) {
    std::string result = showExec("fc-list | head -n 10 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "所有已安装字体: 无法获取 (可能未安装fontconfig)。\n";
        return ERROR_PARA;
    }
    std::cout << "所有已安装字体 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doCheckBluetoothStatus(int index) {
    std::string result = showExec("systemctl is-active bluetooth 2>&1");
    printIndex(index);
    std::cout << "蓝牙服务状态: " << result;
    return (result.find("active") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doCheckWifiStatus(int index) {
    // Requires iwconfig or nmcli. nmcli is more modern.
    std::string result = showExec("nmcli radio wifi 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Wi-Fi状态: 无法获取 (可能未安装NetworkManager或无Wi-Fi)。\n";
        return ERROR_PARA;
    }
    std::cout << "Wi-Fi状态: " << result;
    return (result.find("enabled") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetKernelModulesLoaded(int index) {
    std::string result = showExec("lsmod | head -n 10 2>&1");
    printIndex(index);
    std::cout << "已加载内核模块 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowSystemLogSize(int index) {
    // This targets systemd-journald logs. For rsyslog logs, it would be /var/log/syslog size.
    std::string result = showExec("journalctl --disk-usage 2>&1 | tail -n 1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统日志大小: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统日志大小: " << result;
    return RE_SUCCESS;
}

int doGetDefaultEditor(int index) {
    std::string result = showExec("printenv | grep 'EDITOR\\|VISUAL' | head -n 1 | cut -d'=' -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "默认编辑器: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "默认编辑器: " << result;
    return RE_SUCCESS;
}

int doCheckUserExist(int index) {
    // Requires a user argument. For simplicity, let's assume a common user like "root"
    // In a real scenario, this function would accept a username from `args`.
    std::string testUser = "root";
    std::string cmd = "id -u " + testUser + " >/dev/null 2>&1 && echo \"存在\" || echo \"不存在\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 是否存在: " << result;
    return (result.find("存在") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetUsersDefaultShell(int index) {
    std::string testUser = "root"; // Example, would come from args
    std::string cmd = "getent passwd " + testUser + " | cut -d: -f7 2>&1";
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户 '" << testUser << "' 的默认Shell: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 的默认Shell: " << result;
    return RE_SUCCESS;
}

int doListUserProcesses(int index) {
    std::string result = showExec("ps -u $(whoami) | head -n 10 2>&1");
    printIndex(index);
    std::cout << "当前用户进程 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doCheckIfUserLoggedIn(int index) {
    std::string testUser = "root"; // Example, would come from args
    std::string cmd = "who | grep -w " + testUser + " >/dev/null 2>&1 && echo \"已登录\" || echo \"未登录\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 是否登录: " << result;
    return (result.find("已登录") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetUsersHomeDirectory(int index) {
    std::string testUser = "root"; // Example, would come from args
    std::string cmd = "getent passwd " + testUser + " | cut -d: -f6 2>&1";
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户 '" << testUser << "' 的主目录: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 的主目录: " << result;
    return RE_SUCCESS;
}

int doListAllLoginShellsAvailable(int index) {
    std::string result = showExec("cat /etc/shells 2>&1");
    printIndex(index);
    std::cout << "所有可用登录Shell: \n" << result;
    return RE_SUCCESS;
}

int doShowKernelModuleDependencies(int index) {
    std::string testModule = "ext4"; // Example, would come from args
    std::string cmd = "modinfo -d " + testModule + " 2>/dev/null";
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "内核模块 '" << testModule << "' 的依赖关系: 无法获取或模块不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "内核模块 '" << testModule << "' 的依赖关系: \n" << result;
    return RE_SUCCESS;
}

int doGetProcessorVendorId(int index) {
    std::string result = showExec("grep 'vendor_id' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "处理器供应商ID: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "处理器供应商ID: " << result;
    return RE_SUCCESS;
}

int doCheckIfVirtualMachine(int index) {
    std::string result = showExec("systemd-detect-virt 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "是否为虚拟机: 无法检测 (可能未安装systemd-detect-virt)。\n";
        return ERROR_PARA;
    }
    std::cout << "是否为虚拟机: " << result;
    return (result.find("none") != std::string::npos) ? ERROR_PARA : RE_SUCCESS; // 'none' means not a VM
}

int doShowCpuFlags(int index) {
    std::string result = showExec("grep 'flags' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU标志: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU标志 (部分): " << result;
    return RE_SUCCESS;
}

int doGetBootKernelParameters(int index) {
    std::string result = showExec("cat /proc/cmdline 2>&1");
    printIndex(index);
    std::cout << "启动内核参数: " << result;
    return RE_SUCCESS;
}

int doListAllOpenTcpConnections(int index) {
    std::string result = showExec("ss -tna 2>&1 | head -n 10");
    printIndex(index);
    std::cout << "所有打开的TCP连接 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doListAllOpenUdpConnections(int index) {
    std::string result = showExec("ss -una 2>&1 | head -n 10");
    printIndex(index);
    std::cout << "所有打开的UDP连接 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkCardMacAddress(int index) {
    // Assuming eth0. In real scenario, interface name would be an arg.
    std::string result = showExec("ip link show eth0 | grep link/ether | awk '{print $2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 eth0 MAC地址: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 eth0 MAC地址: " << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfaceStatisticsEth0(int index) {
    std::string result = showExec("ip -s link show eth0 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 eth0 统计信息: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 eth0 统计信息: \n" << result;
    return RE_SUCCESS;
}

int doGetDefaultInterfaceMTU(int index) {
    std::string result = showExec("ip route | grep default | awk '{print $5}' | xargs -I {} ip link show {} | grep mtu | awk '{print $5}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "默认接口MTU: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "默认接口MTU: " << result;
    return RE_SUCCESS;
}

int doListAllAvailableNetworkDevices(int index) {
    std::string result = showExec("ip link show | grep -E '^[0-9]:' | awk '{print $2}' | tr -d ':' 2>&1");
    printIndex(index);
    std::cout << "所有可用网络设备: \n" << result;
    return RE_SUCCESS;
}

int doGetSystemDefaultLocale(int index) {
    std::string result = showExec("locale | grep LANG= | cut -d= -f2 | tr -d '\"' 2>&1");
    printIndex(index);
    std::cout << "系统默认区域设置: " << result;
    return RE_SUCCESS;
}

int doListAvailableKeyboardLayouts(int index) {
    std::string result = showExec("localectl list-keymaps | head -n 10 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "可用键盘布局: 无法获取 (可能未安装localectl)。\n";
        return ERROR_PARA;
    }
    std::cout << "可用键盘布局 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowXorgLogErrors(int index) {
    std::string result = showExec("grep -i \"(EE)\" /var/log/Xorg.0.log 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Xorg日志错误: 未发现或无日志文件。\n";
        return ERROR_PARA;
    }
    std::cout << "Xorg日志错误: \n" << result;
    return RE_SUCCESS;
}

int doGetPackageManagerName(int index) {
    std::string pm = "";
    if (!showExec("which apt 2>/dev/null").empty()) pm = "apt";
    else if (!showExec("which dnf 2>/dev/null").empty()) pm = "dnf";
    else if (!showExec("which yum 2>/dev/null").empty()) pm = "yum";
    else if (!showExec("which pacman 2>/dev/null").empty()) pm = "pacman";

    printIndex(index);
    if (pm.empty()) {
        std::cout << "包管理器名称: 无法检测。\n";
        return ERROR_PARA;
    }
    std::cout << "包管理器名称: " << pm << "\n";
    return RE_SUCCESS;
}

int doShowDiskSectorSize(int index) {
    // Assuming /dev/sda. In real scenario, device would be an arg.
    std::string result = showExec("sudo blockdev --getss /dev/sda 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘扇区大小: 无法获取 (可能需要sudo或设备不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘扇区大小 (/dev/sda): " << result;
    return RE_SUCCESS;
}
int doCheckIfFileIsExecutable(int index) {
    std::string testFile = "/bin/ls"; // Example, would come from args
    std::string cmd = "test -x " + testFile + " && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "文件 '" << testFile << "' 是否可执行: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doCheckIfFileIsReadable(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string cmd = "test -r " + testFile + " && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "文件 '" << testFile << "' 是否可读: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doCheckIfFileIsWritable(int index) {
    std::string testFile = "/tmp/testfile.txt"; // Example, would come from args
    std::string cmd = "test -w " + testFile + " && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "文件 '" << testFile << "' 是否可写: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowFileOwnerAndGroup(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("ls -l " + testFile + " | awk '{print \"所有者: \"$3\", 组: \"$4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 的所有者和组: 无法获取或文件不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 的所有者和组: " << result;
    return RE_SUCCESS;
}

int doShowFilePermissions(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("ls -l " + testFile + " | awk '{print $1}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 的权限: 无法获取或文件不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 的权限: " << result;
    return RE_SUCCESS;
}

int doShowLastModifiedTimeOfFile(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %y " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 最后修改时间: 无法获取或文件不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 最后修改时间: " << result;
    return RE_SUCCESS;
}

int doShowCreationTimeOfFile(int index) {
    // Note: Linux ext4 does not store creation time directly (birth time), it's mtime or ctime.
    // If btime is supported (e.g., modern ext4, btrfs), stat will show it.
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %w " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty() || result.find("1970-01-01") != std::string::npos) { // Indicates btime not supported/available
        std::cout << "文件 '" << testFile << "' 创建时间: 无法获取 (文件系统可能不支持或文件不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 创建时间: " << result;
    return RE_SUCCESS;
}

int doGetFileSize(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("du -h " + testFile + " | awk '{print $1}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 大小: 无法获取或文件不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 大小: " << result;
    return RE_SUCCESS;
}

int doShowFileChecksumMd5(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("md5sum " + testFile + " | awk '{print $1}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' MD5校验和: 无法获取或文件不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' MD5校验和: " << result;
    return RE_SUCCESS;
}

int doShowFileChecksumSha256(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("sha256sum " + testFile + " | awk '{print $1}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' SHA256校验和: 无法获取或文件不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' SHA256校验和: " << result;
    return RE_SUCCESS;
}

int doCheckIfDirectoryExists(int index) {
    std::string testDir = "/tmp"; // Example, would come from args
    std::string cmd = "test -d " + testDir + " && echo \"存在\" || echo \"不存在\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "目录 '" << testDir << "' 是否存在: " << result;
    return (result.find("存在") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowDirectoryContentsRecursive(int index) {
    std::string testDir = "/tmp"; // Example, would come from args
    std::string result = showExec("ls -R " + testDir + " | head -n 10 2>&1");
    printIndex(index);
    std::cout << "目录 '" << testDir << "' 递归内容 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetDirectorySizeRecursive(int index) {
    std::string testDir = "/tmp"; // Example, would come from args
    std::string result = showExec("du -sh " + testDir + " | awk '{print $1}' 2>&1");
    printIndex(index);
    std::cout << "目录 '" << testDir << "' 递归大小: " << result;
    return RE_SUCCESS;
}

int doShowCurrentUserUid(int index) {
    std::string result = showExec("id -u 2>&1");
    printIndex(index);
    std::cout << "当前用户UID: " << result;
    return RE_SUCCESS;
}

int doShowCurrentUserGid(int index) {
    std::string result = showExec("id -g 2>&1");
    printIndex(index);
    std::cout << "当前用户GID: " << result;
    return RE_SUCCESS;
}

int doGetUsersSupplementaryGroups(int index) {
    std::string result = showExec("id -Gn 2>&1");
    printIndex(index);
    std::cout << "当前用户的附加组: " << result;
    return RE_SUCCESS;
}

int doCheckIfCommandExists(int index) {
    std::string testCmd = "ls"; // Example, would come from args
    std::string cmd = "command -v " + testCmd + " >/dev/null 2>&1 && echo \"存在\" || echo \"不存在\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "命令 '" << testCmd << "' 是否存在: " << result;
    return (result.find("存在") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowCommandFullPath(int index) {
    std::string testCmd = "ls"; // Example, would come from args
    std::string result = showExec("which " + testCmd + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "命令 '" << testCmd << "' 的完整路径: 无法找到。\n";
        return ERROR_PARA;
    }
    std::cout << "命令 '" << testCmd << "' 的完整路径: " << result;
    return RE_SUCCESS;
}

int doGetSystemArchitecture(int index) {
    std::string result = showExec("arch 2>&1");
    printIndex(index);
    std::cout << "系统架构: " << result;
    return RE_SUCCESS;
}

int doGetSystemReleaseVersion(int index) {
    std::string result = showExec("lsb_release -rs 2>/dev/null || cat /etc/os-release | grep VERSION_ID | cut -d'=' -f2 | tr -d '\"' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统发布版本: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统发布版本: " << result;
    return RE_SUCCESS;
}

int doShowAllLoadedModules(int index) {
    std::string result = showExec("lsmod 2>&1 | head -n 10");
    printIndex(index);
    std::cout << "所有已加载模块 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkDeviceDriver(int index) {
    std::string testDevice = "eth0"; // Example, would come from args
    std::string result = showExec("ethtool -i " + testDevice + " 2>/dev/null | grep driver | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网络设备 '" << testDevice << "' 驱动: 无法获取 (可能需要sudo或设备不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "网络设备 '" << testDevice << "' 驱动: " << result;
    return RE_SUCCESS;
}

int doShowDiskIoStatistics(int index) {
    std::string result = showExec("iostat -d 1 1 2>&1 | tail -n 3");
    printIndex(index);
    std::cout << "磁盘IO统计 (快照): \n" << result;
    return RE_SUCCESS;
}

int doGetRamDiskSize(int index) {
    std::string result = showExec("df -h /dev/shm | awk 'NR==2 {print $2}' 2>&1");
    printIndex(index);
    std::cout << "内存盘 (tmpfs) 大小: " << result;
    return RE_SUCCESS;
}

int doShowSyslogEntriesForToday(int index) {
    std::string result = showExec("journalctl --since \"today\" | head -n 10 2>&1");
    printIndex(index);
    std::cout << "今日系统日志条目 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetDefaultTimeZoneOffset(int index) {
    std::string result = showExec("date +%z 2>&1");
    printIndex(index);
    std::cout << "默认时区偏移: " << result;
    return RE_SUCCESS;
}

int doCheckAvailableUpdates(int index) {
    std::string result = showExec("sudo apt update 2>/dev/null >/dev/null && apt list --upgradable 2>/dev/null | wc -l");
    printIndex(index);
    // apt list --upgradable 包含一行 "Listing..."，所以要减去1
    long count = 0;
    try {
        count = std::stol(result) - 1;
    } catch (...) {
        std::cout << "可用更新: 无法获取 (可能需要sudo或apt未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "可用更新数量: " << (count > 0 ? std::to_string(count) : "0") << "\n";
    return RE_SUCCESS;
}


int doListRecentlyInstalledPackages(int index) {
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "grep \" install \" /var/log/dpkg.log 2>/dev/null | tail -n 5 | awk '{print $1, $2, $4}'";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf history list 2>/dev/null | head -n 5";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum history list 2>/dev/null | head -n 5";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "grep \"installed\" /var/log/pacman.log 2>/dev/null | tail -n 5 | awk '{print $1, $2, $3}'";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "最近安装的软件包: 无法获取 (可能无日志或不支持当前包管理器)。\n";
        return ERROR_PARA;
    }
    std::cout << "最近安装的软件包 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetPackageCountInstalled(int index) {
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "dpkg -l | grep -c '^ii'";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf list installed | wc -l"; // Includes header
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum list installed | wc -l"; // Includes header
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Q | wc -l";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
        if (cmd.find("dnf") != std::string::npos || cmd.find("yum") != std::string::npos) count--; // Adjust for header
    } catch (...) {
        std::cout << "已安装软件包总数: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "已安装软件包总数: " << count << "\n";
    return RE_SUCCESS;
}

int doShowDiskUsageByFilesystem(int index) {
    std::string result = showExec("df -hT -x tmpfs -x devtmpfs 2>&1");
    printIndex(index);
    std::cout << "按文件系统划分的磁盘使用情况: \n" << result;
    return RE_SUCCESS;
}

int doShowMountOptionsForRoot(int index) {
    std::string result = showExec("findmnt -no OPTIONS / 2>&1");
    printIndex(index);
    std::cout << "根文件系统挂载选项: " << result;
    return RE_SUCCESS;
}

int doCheckIfSwapPartitionExists(int index) {
    std::string result = showExec("grep -q swap /proc/swaps && echo \"存在\" || echo \"不存在\" 2>&1");
    printIndex(index);
    std::cout << "交换分区是否存在: " << result;
    return (result.find("存在") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowAvailableSwapDevices(int index) {
    std::string result = showExec("cat /proc/swaps 2>&1");
    printIndex(index);
    std::cout << "可用交换设备: \n" << result;
    return RE_SUCCESS;
}

int doListAllNetworkRoutes(int index) {
    std::string result = showExec("ip route show 2>&1");
    printIndex(index);
    std::cout << "所有网络路由: \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceSpeed(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ethtool " + testInterface + " 2>/dev/null | grep -i 'Speed:' | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 速度: 无法获取 (可能需要sudo或网卡不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 速度: " << result;
    return RE_SUCCESS;
}

int doCheckSpecificPortStatus(int index) {
    std::string testPort = "22"; // Example, would come from args
    std::string cmd = "ss -tuln | grep \":" + testPort + "\" >/dev/null 2>&1 && echo \"已监听\" || echo \"未监听\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "端口 '" << testPort << "' 状态: " << result;
    return (result.find("已监听") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowKernelBuildDate(int index) {
    std::string result = showExec("uname -v | awk '{print $NF}' 2>&1");
    printIndex(index);
    std::cout << "内核构建日期: " << result;
    return RE_SUCCESS;
}

int doGetSystemArchitectureEndianness(int index) {
    std::string result = showExec("lscpu | grep 'Byte Order:' | awk '{print $3}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统架构字节序: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统架构字节序: " << result;
    return RE_SUCCESS;
}

int doShowCpuVulnerabilities(int index) {
    std::string result = showExec("grep -r . /sys/devices/system/cpu/vulnerabilities/ 2>/dev/null | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU漏洞信息: 无法获取 (可能内核版本较旧或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU漏洞信息 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetCpuPhysicalCores(int index) {
    std::string result = showExec("lscpu | grep 'Core(s) per socket:' | awk '{print $4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU物理核心数: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU物理核心数: " << result;
    return RE_SUCCESS;
}

int doListAllLoadedKernelModules(int index) {
    std::string result = showExec("lsmod 2>&1");
    printIndex(index);
    std::cout << "所有已加载内核模块: \n" << result;
    return RE_SUCCESS;
}

int doShowSystemConsoleFont(int index) {
    std::string result = showExec("showconsolefont 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统控制台字体: 无法获取 (可能未安装showconsolefont)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统控制台字体: " << result;
    return RE_SUCCESS;
}

int doGetLoggedInUsersCount(int index) {
    std::string result = showExec("who | wc -l 2>&1");
    printIndex(index);
    std::cout << "已登录用户数量: " << result;
    return RE_SUCCESS;
}

int doShowUserIdleTime(int index) {
    std::string result = showExec("w | grep $(whoami) | awk '{print $5}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户空闲时间: 无法获取 (可能用户未登录或w命令不可用)。\n";
        return ERROR_PARA;
    }
    std::cout << "用户空闲时间: " << result;
    return RE_SUCCESS;
}

int doListUsersLoginSessions(int index) {
    std::string result = showExec("loginctl list-sessions 2>&1");
    printIndex(index);
    std::cout << "用户登录会话: \n" << result;
    return RE_SUCCESS;
}

int doGetLastUserLoginTime(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("last " + testUser + " | head -n 1 | awk '{print $4\" \"$5\" \"$6\" \"$7\" \"$8}' 2>&1");
    printIndex(index);
    if (result.empty() || result.find("wtmp begins") != std::string::npos) {
        std::cout << "用户上次登录时间: 无法获取或无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "用户上次登录时间: " << result;
    return RE_SUCCESS;
}

int doCheckIfUserHasPassword(int index) {
    std::string testUser = "root"; // Example, would come from args
    std::string cmd = "passwd -S " + testUser + " 2>/dev/null | awk '{print $2}'";
    std::string status = showExec(cmd);
    printIndex(index);
    if (status.empty()) {
        std::cout << "用户 '" << testUser << "' 是否有密码: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 是否有密码: " << (status == "P" ? "是 (已设置)" : "否 (无密码/锁定)") << "\n";
    return RE_SUCCESS;
}

int doListAllSystemUsers(int index) {
    std::string result = showExec("cat /etc/passwd | cut -d: -f1 | head -n 20 2>&1");
    printIndex(index);
    std::cout << "所有系统用户 (前20条): \n" << result;
    return RE_SUCCESS;
}

int doShowLastChangedPasswordDate(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("sudo chage -l " + testUser + " 2>/dev/null | grep 'Last password change' | cut -d: -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户 '" << testUser << "' 最后更改密码日期: 无法获取 (可能需要sudo或用户不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 最后更改密码日期: " << result;
    return RE_SUCCESS;
}

int doGetShellVersion(int index) {
    std::string result = showExec("bash --version | head -n 1 2>&1 || zsh --version | head -n 1 2>&1 || sh --version | head -n 1 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Shell版本: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "Shell版本: " << result;
    return RE_SUCCESS;
}

int doShowCurrentTerminalWidth(int index) {
    std::string result = showExec("tput cols 2>&1");
    printIndex(index);
    std::cout << "当前终端宽度 (列数): " << result;
    return RE_SUCCESS;
}

int doShowCurrentTerminalHeight(int index) {
    std::string result = showExec("tput lines 2>&1");
    printIndex(index);
    std::cout << "当前终端高度 (行数): " << result;
    return RE_SUCCESS;
}

int doListAllRunningServices(int index) {
    std::string result = showExec("systemctl list-units --type=service --state=running --no-pager 2>&1 | head -n 10");
    printIndex(index);
    std::cout << "所有正在运行的服务 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemdDefaultTarget(int index) {
    std::string result = showExec("systemctl get-default 2>&1");
    printIndex(index);
    std::cout << "Systemd默认目标: " << result;
    return RE_SUCCESS;
}

int doShowSystemdJournalDiskUsage(int index) {
    std::string result = showExec("journalctl --disk-usage 2>&1");
    printIndex(index);
    std::cout << "Systemd日志磁盘使用量: \n" << result;
    return RE_SUCCESS;
}

int doCheckServiceEnabledStatus(int index) {
    std::string testService = "sshd"; // Example, would come from args
    std::string result = showExec("systemctl is-enabled " + testService + " 2>&1");
    printIndex(index);
    std::cout << "服务 '" << testService << "' 是否已启用: " << result;
    return (result.find("enabled") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetSystemLocaleCharset(int index) {
    std::string result = showExec("locale | grep \"CHARSET=\" | cut -d'=' -f2 | tr -d '\"' 2>&1");
    printIndex(index);
    std::cout << "系统区域设置字符集: " << result;
    return RE_SUCCESS;
}

int doListAvailableLocales(int index) {
    std::string result = showExec("locale -a | head -n 10 2>&1");
    printIndex(index);
    std::cout << "可用区域设置 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowCurrentWorkingDirectorySize(int index) {
    std::string result = showExec("du -sh . 2>&1");
    printIndex(index);
    std::cout << "当前工作目录大小: " << result;
    return RE_SUCCESS;
}

int doCountFilesInDirectory(int index) {
    std::string testDir = "."; // Example, would come from args
    std::string result = showExec("find " + testDir + " -maxdepth 1 -type f | wc -l 2>&1");
    printIndex(index);
    std::cout << "目录 '" << testDir << "' 中的文件数量: " << result;
    return RE_SUCCESS;
}

int doCountDirectoriesInDirectory(int index) {
    std::string testDir = "."; // Example, would come from args
    std::string result = showExec("find " + testDir + " -maxdepth 1 -type d | wc -l 2>&1");
    printIndex(index);
    // wc -l 统计包含当前目录，所以需要减1
    long count = 0;
    try {
        count = std::stol(result) - 1;
    } catch (...) {
        std::cout << "目录 '" << testDir << "' 中的子目录数量: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "目录 '" << testDir << "' 中的子目录数量: " << count << "\n";
    return RE_SUCCESS;
}

int doGetTotalDiskSpace(int index) {
    std::string result = showExec("df -h --total | tail -n 1 | awk '{print $2}' 2>&1");
    printIndex(index);
    std::cout << "总磁盘空间: " << result;
    return RE_SUCCESS;
}

int doGetUsedDiskSpace(int index) {
    std::string result = showExec("df -h --total | tail -n 1 | awk '{print $3}' 2>&1");
    printIndex(index);
    std::cout << "已用磁盘空间: " << result;
    return RE_SUCCESS;
}

int doGetFreeDiskSpace(int index) {
    std::string result = showExec("df -h --total | tail -n 1 | awk '{print $4}' 2>&1");
    printIndex(index);
    std::cout << "可用磁盘空间: " << result;
    return RE_SUCCESS;
}

int doShowDiskUsageForAllMountPoints(int index) {
    std::string result = showExec("df -h 2>&1");
    printIndex(index);
    std::cout << "所有挂载点的磁盘使用情况: \n" << result;
    return RE_SUCCESS;
}

int doShowFilesystemMountTime(int index) {
    std::string testMountPoint = "/"; // Example, would come from args
    std::string result = showExec("stat -c %w " + testMountPoint + " 2>&1");
    printIndex(index);
    if (result.empty() || result.find("1970-01-01") != std::string::npos) {
        std::cout << "文件系统 '" << testMountPoint << "' 挂载时间: 无法获取 (可能文件系统不支持或未挂载)。\n";
        return ERROR_PARA;
    }
    std::cout << "文件系统 '" << testMountPoint << "' 挂载时间: " << result;
    return RE_SUCCESS;
}

int doGetKernelCommandLine(int index) {
    std::string result = showExec("cat /proc/cmdline 2>&1");
    printIndex(index);
    std::cout << "内核命令行参数: " << result;
    return RE_SUCCESS;
}

int doShowProcessTree(int index) {
    std::string result = showExec("pstree -ulp 2>&1 | head -n 10");
    printIndex(index);
    std::cout << "进程树 (前10行): \n" << result;
    return RE_SUCCESS;
}

int doGetProcessCpuUsage(int index) {
    // Requires a PID. For simplicity, pick PID 1 (init/systemd)
    std::string testPid = "1"; // Example, would come from args
    std::string result = showExec("ps -p " + testPid + " -o %cpu --no-headers 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " CPU使用率: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " CPU使用率: " << result;
    return RE_SUCCESS;
}


int doShowRecentShutdowns(int index) {
    std::string result = showExec("last -x shutdown | head -n 5 2>&1");
    printIndex(index);
    if (result.empty() || result.find("wtmp begins") != std::string::npos) {
        std::cout << "最近关机记录: 无。\n";
        return ERROR_PARA;
    }
    std::cout << "最近关机记录 (最后5条): \n" << result;
    return RE_SUCCESS;
}

int doCheckRtcTime(int index) {
    std::string result = showExec("hwclock --show 2>&1");
    printIndex(index);
    std::cout << "RTC (硬件时钟) 时间: " << result;
    return RE_SUCCESS;
}

int doGetSystemHardwareClockTime(int index) {
    std::string result = showExec("hwclock --show 2>&1");
    printIndex(index);
    std::cout << "系统硬件时钟时间: " << result;
    return RE_SUCCESS;
}

int doShowNetworkDhcpLeaseInfo(int index) {
    std::string result = showExec("cat /var/lib/dhcp/dhclient.leases 2>/dev/null | grep 'lease {' -A 5 | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网络DHCP租约信息: 无法获取 (可能未配置DHCP或无日志)。\n";
        return ERROR_PARA;
    }
    std::cout << "网络DHCP租约信息 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowNetworkDNSResolver(int index) {
    std::string result = showExec("cat /etc/resolv.conf | grep nameserver | head -n 5 2>&1");
    printIndex(index);
    std::cout << "网络DNS解析器: \n" << result;
    return RE_SUCCESS;
}

int doCheckNtpSyncStatus(int index) {
    std::string result = showExec("timedatectl | grep \"NTP synchronized:\" | awk '{print $3}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "NTP同步状态: 无法获取 (可能未安装或非systemd系统)。\n";
        return ERROR_PARA;
    }
    std::cout << "NTP同步状态: " << result;
    return RE_SUCCESS;
}

int doGetNtpServerList(int index) {
    std::string result = showExec("timedatectl timesync-status 2>/dev/null | grep 'NTP' | awk '{print $NF}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "NTP服务器列表: 无法获取 (可能未安装或非systemd系统)。\n";
        return ERROR_PARA;
    }
    std::cout << "NTP服务器列表: " << result;
    return RE_SUCCESS;
}

int doShowSystemUptime(int index) {
    std::string result = showExec("uptime -p 2>&1");
    printIndex(index);
    std::cout << "系统运行时间: " << result;
    return RE_SUCCESS;
}

int doShowLoadAverageOneMinute(int index) {
    std::string result = showExec("cat /proc/loadavg | awk '{print $1}' 2>&1");
    printIndex(index);
    std::cout << "1分钟平均负载: " << result;
    return RE_SUCCESS;
}

int doShowLoadAverageFiveMinutes(int index) {
    std::string result = showExec("cat /proc/loadavg | awk '{print $2}' 2>&1");
    printIndex(index);
    std::cout << "5分钟平均负载: " << result;
    return RE_SUCCESS;
}

int doShowLoadAverageFifteenMinutes(int index) {
    std::string result = showExec("cat /proc/loadavg | awk '{print $3}' 2>&1");
    printIndex(index);
    std::cout << "15分钟平均负载: " << result;
    return RE_SUCCESS;
}

int doGetKernelVersionFull(int index) {
    std::string result = showExec("uname -a 2>&1");
    printIndex(index);
    std::cout << "完整内核版本信息: " << result;
    return RE_SUCCESS;
}

int doShowCpuInfoSummary(int index) {
    std::string result = showExec("lscpu | grep -E 'Architecture|CPU(s):|Model name|Vendor ID|CPU MHz:' 2>&1");
    printIndex(index);
    std::cout << "CPU信息摘要: \n" << result;
    return RE_SUCCESS;
}

int doGetTotalProcessesRunning(int index) {
    std::string result = showExec("ps -e --no-headers | wc -l 2>&1");
    printIndex(index);
    std::cout << "正在运行的进程总数: " << result;
    return RE_SUCCESS;
}

int doGetProcessesPerUser(int index) {
    std::string result = showExec("ps -eo user,comm --no-headers | awk '{a[$1]++} END {for (i in a) print i, a[i]}' | head -n 5 2>&1");
    printIndex(index);
    std::cout << "每用户进程数量 (前5条): \n" << result;
    return RE_SUCCESS;
}

int doShowCpuInterruptsInfo(int index) {
    std::string result = showExec("cat /proc/interrupts | head -n 5 2>&1");
    printIndex(index);
    std::cout << "CPU中断信息 (前5行): \n" << result;
    return RE_SUCCESS;
}

int doShowCpuContextSwitches(int index) {
    std::string result = showExec("vmstat 1 1 | tail -n 1 | awk '{print $12}' 2>&1");
    printIndex(index);
    std::cout << "CPU上下文切换次数 (每秒): " << result;
    return RE_SUCCESS;
}

int doShowMemoryActiveUsage(int index) {
    std::string result = showExec("grep Active /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "内存活跃使用量: " << result;
    return RE_SUCCESS;
}

int doShowMemoryInactiveUsage(int index) {
    std::string result = showExec("grep Inactive /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "内存非活跃使用量: " << result;
    return RE_SUCCESS;
}

int doShowMemoryDirtyUsage(int index) {
    std::string result = showExec("grep Dirty /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "内存脏页使用量: " << result;
    return RE_SUCCESS;
}

int doShowMemoryWritebackUsage(int index) {
    std::string result = showExec("grep Writeback /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "内存回写使用量: " << result;
    return RE_SUCCESS;
}

int doGetFileSystemMountCount(int index) {
    std::string result = showExec("mount | wc -l 2>&1");
    printIndex(index);
    std::cout << "文件系统挂载点数量: " << result;
    return RE_SUCCESS;
}

int doShowFileSystemTypeForPath(int index) {
    std::string testPath = "/home"; // Example, would come from args
    std::string result = showExec("findmnt -no FSTYPE " + testPath + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "路径 '" << testPath << "' 的文件系统类型: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "路径 '" << testPath << "' 的文件系统类型: " << result;
    return RE_SUCCESS;
}

int doGetFreeInodesCount(int index) {
    std::string result = showExec("df -i / | awk 'NR==2 {print $4}' 2>&1");
    printIndex(index);
    std::cout << "根文件系统空闲Inode数量: " << result;
    return RE_SUCCESS;
}

int doShowDiskIoQueueSize(int index) {
    std::string testDisk = "sda"; // Example, would come from args
    std::string result = showExec("cat /sys/block/" + testDisk + "/queue/nr_requests 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘 " << testDisk << " IO队列大小: 无法获取 (可能磁盘不存在或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘 " << testDisk << " IO队列大小: " << result;
    return RE_SUCCESS;
}

int doCheckIfSsdExists(int index) {
    std::string result = showExec("grep -q 'rotational is 0' /sys/block/sda/queue/rotational 2>/dev/null && echo \"是\" || echo \"否\" 2>&1");
    printIndex(index);
    std::cout << "是否存在SSD (检查/dev/sda): " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetDiskReadSpeed(int index) {
    // Requires specialized tools like `hdparm` (often needs sudo) or `fio`.
    // This is a placeholder and may not work without elevated privileges or specific setup.
    std::string result = showExec("sudo hdparm -t /dev/sda 2>/dev/null | grep 'Timing buffered disk reads' | awk '{print $NF}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘读取速度: 无法获取 (可能需要sudo或hdparm未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘读取速度 (/dev/sda): " << result;
    return RE_SUCCESS;
}

int doGetDiskWriteSpeed(int index) {
    // Similar to read speed, requires specific tools and permissions.
    // This is a placeholder for a more complex benchmark.
    std::string result = showExec("dd if=/dev/zero of=/tmp/testfile bs=1M count=100 conv=fdatasync 2>&1 | grep copied | awk '{print $NF\" \"$(NF-1)}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘写入速度: 无法获取 (或写入测试失败)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘写入速度 (测试): " << result;
    return RE_SUCCESS;
}

int doShowNetworkPacketErrors(int index) {
    std::string result = showExec("ip -s link show | grep 'errors' 2>&1");
    printIndex(index);
    std::cout << "网络包错误: \n" << result;
    return RE_SUCCESS;
}

int doShowNetworkDroppedPackets(int index) {
    std::string result = showExec("ip -s link show | grep 'dropped' 2>&1");
    printIndex(index);
    std::cout << "网络丢弃包: \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceQueueLength(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip link show " + testInterface + " | grep qlen | awk '{print $NF}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 队列长度: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 队列长度: " << result;
    return RE_SUCCESS;
}

int doGetNetworkBroadcastAddress(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip addr show " + testInterface + " | grep 'brd' | awk '{print $4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 广播地址: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 广播地址: " << result;
    return RE_SUCCESS;
}

int doShowNetworkMulticastAddresses(int index) {
    std::string result = showExec("netstat -g 2>&1");
    printIndex(index);
    std::cout << "网络多播地址: \n" << result;
    return RE_SUCCESS;
}

int doCheckDnsResolutionForHost(int index) {
    std::string testHost = "google.com"; // Example, would come from args
    std::string result = showExec("ping -c 1 " + testHost + " >/dev/null 2>&1 && echo \"成功\" || echo \"失败\" 2>&1");
    printIndex(index);
    std::cout << "主机 '" << testHost << "' DNS解析: " << result;
    return (result.find("成功") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetDefaultShellPath(int index) {
    std::string result = showExec("getent passwd $(whoami) | cut -d: -f7 2>&1");
    printIndex(index);
    std::cout << "默认Shell路径: " << result;
    return RE_SUCCESS;
}

int doShowCurrentUserTerminalName(int index) {
    std::string result = showExec("tty 2>&1");
    printIndex(index);
    std::cout << "当前用户终端名称: " << result;
    return RE_SUCCESS;
}

int doShowLoginAttemptsToday(int index) {
    std::string result = showExec("journalctl --since \"today\" _COMM=sshd | grep 'Accepted password' | wc -l 2>&1");
    printIndex(index);
    std::cout << "今日登录尝试次数: " << result;
    return RE_SUCCESS;
}

int doCheckIfUserHasHomeDirectory(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string cmd = "getent passwd " + testUser + " | cut -d: -f6 | xargs test -d >/dev/null 2>&1 && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 是否有主目录: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doListUserDefinedAliases(int index) {
    // This only shows aliases defined in current shell session or .bashrc loaded
    std::string result = showExec("alias 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户自定义别名: 无。\n";
        return ERROR_PARA;
    }
    std::cout << "用户自定义别名: \n" << result;
    return RE_SUCCESS;
}

int doGetTotalUsersOnSystem(int index) {
    std::string result = showExec("cut -d: -f1 /etc/passwd | wc -l 2>&1");
    printIndex(index);
    std::cout << "系统总用户数量: " << result;
    return RE_SUCCESS;
}

int doShowSystemTimeZoneName(int index) {
    std::string result = showExec("timedatectl | grep 'Time zone:' | awk '{print $3}' 2>&1");
    printIndex(index);
    std::cout << "系统时区名称: " << result;
    return RE_SUCCESS;
}

int doGetSystemLocaleEncoding(int index) {
    std::string result = showExec("locale | grep 'LC_CTYPE=' | cut -d'=' -f2 | tr -d '\"' 2>&1");
    printIndex(index);
    std::cout << "系统区域设置编码: " << result;
    return RE_SUCCESS;
}

int doShowSystemHostnameShort(int index) {
    std::string result = showExec("hostname -s 2>&1");
    printIndex(index);
    std::cout << "系统短主机名: " << result;
    return RE_SUCCESS;
}

int doGetSystemDbusAddress(int index) {
    std::string result = showExec("echo $DBUS_SESSION_BUS_ADDRESS 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统D-Bus地址: 无法获取 (可能不在GUI会话中)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统D-Bus地址: " << result;
    return RE_SUCCESS;
}

int doListAllCronJobFiles(int index) {
    std::string result = showExec("find /etc/cron.* /var/spool/cron -type f 2>/dev/null | head -n 10");
    printIndex(index);
    std::cout << "所有Cron任务文件 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowCurrentlyOpenFilesCount(int index) {
    std::string result = showExec("lsof | wc -l 2>&1");
    printIndex(index);
    std::cout << "当前打开文件总数: " << result;
    return RE_SUCCESS;
}

int doGetMaxFileDescriptorsSystemWide(int index) {
    std::string result = showExec("cat /proc/sys/fs/file-max 2>&1");
    printIndex(index);
    std::cout << "系统最大文件描述符数量: " << result;
    return RE_SUCCESS;
}

int doCheckIfPowerSavingEnabled(int index) {
    std::string result = showExec("cat /sys/module/snd_hda_intel/parameters/power_save 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "电源节约模式: 无法获取 (可能不支持或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "电源节约模式 (音频): " << (result.find("0") != std::string::npos ? "禁用" : "启用") << "\n";
    return RE_SUCCESS;
}

int doGetCpuGovernor(int index) {
    std::string result = showExec("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU调速器: 无法获取 (可能不支持或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU调速器: " << result;
    return RE_SUCCESS;
}

int doShowHardwareInfoSummary(int index) {
    std::string result = showExec("lshw -short 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "硬件信息摘要: 无法获取 (可能需要sudo或lshw未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "硬件信息摘要 (部分): \n" << result;
    return RE_SUCCESS;
}

int doCheckSystemClockSynchronization(int index) {
    std::string result = showExec("timedatectl status | grep 'System clock synchronized:' | awk '{print $4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统时钟同步状态: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统时钟同步状态: " << result;
    return RE_SUCCESS;
}

int doGetBootupTimeInSeconds(int index) {
    std::string result = showExec("cat /proc/uptime | awk '{print $1}' 2>&1");
    printIndex(index);
    std::cout << "启动时间 (秒): " << result;
    return RE_SUCCESS;
}

int doShowActiveNetworkConnectionsCount(int index) {
    std::string result = showExec("ss -s | grep 'estab' | awk '{print $2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "活动网络连接数: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "活动网络连接数: " << result;
    return RE_SUCCESS;
}

int doListNetworkInterfacesOnly(int index) {
    std::string result = showExec("ip -o link show | awk -F': ' '{print $2}' 2>&1");
    printIndex(index);
    std::cout << "仅列出网络接口: \n" << result;
    return RE_SUCCESS;
}

int doShowIpV4Addresses(int index) {
    std::string result = showExec("ip -4 a | grep -oP 'inet \\K[\\d.]+' 2>&1");
    printIndex(index);
    std::cout << "IPv4 地址: \n" << result;
    return RE_SUCCESS;
}

int doShowIpV6Addresses(int index) {
    std::string result = showExec("ip -6 a | grep -oP 'inet6 \\K[0-9a-f:]+' 2>&1");
    printIndex(index);
    std::cout << "IPv6 地址: \n" << result;
    return RE_SUCCESS;
}


int doShowDnsServerIp(int index) {
    std::string result = showExec("cat /etc/resolv.conf | grep nameserver | awk '{print $2}' 2>&1");
    printIndex(index);
    std::cout << "DNS服务器IP: \n" << result;
    return RE_SUCCESS;
}

int doListAllNetworkPortsInUse(int index) {
    std::string result = showExec("netstat -tuln | head -n 10 2>&1");
    printIndex(index);
    std::cout << "所有正在使用的网络端口 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doCheckIfInterfaceIsUp(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string cmd = "ip link show " + testInterface + " up >/dev/null 2>&1 && echo \"已启用\" || echo \"未启用\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "网卡 '" << testInterface << "' 是否启用: " << result;
    return (result.find("已启用") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetNetworkLinkSpeed(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ethtool " + testInterface + " 2>/dev/null | grep 'Speed:' | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 链接速度: 无法获取 (可能需要sudo或网卡不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 链接速度: " << result;
    return RE_SUCCESS;
}

int doShowWifiSignalStrength(int index) {
    // Requires wireless-tools (iwconfig) or NetworkManager (nmcli)
    std::string result = showExec("iwconfig 2>/dev/null | grep 'Signal level' | awk '{print $4}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Wi-Fi信号强度: 无法获取 (可能无无线网卡或未连接)。\n";
        return ERROR_PARA;
    }
    std::cout << "Wi-Fi信号强度: " << result;
    return RE_SUCCESS;
}

int doShowOpenSshSessions(int index) {
    std::string result = showExec("who | grep 'ssh' | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "开放SSH会话: 无。\n";
        return ERROR_PARA;
    }
    std::cout << "开放SSH会话 (前5条): \n" << result;
    return RE_SUCCESS;
}

int doGetPackageManagerListAvailable(int index) {
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "apt list --installed 2>/dev/null | head -n 10"; // Just show some installed as "available" is too broad
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf list installed 2>/dev/null | head -n 10";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum list installed 2>/dev/null | head -n 10";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Q 2>/dev/null | head -n 10";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "包管理器可用列表: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "包管理器可用列表 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowPackageInstallSize(int index) {
    std::string testPackage = "htop"; // Example, would come from args
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "apt show " + testPackage + " 2>/dev/null | grep 'Installed-Size' | awk '{print $2}'";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf info " + testPackage + " 2>/dev/null | grep 'Installed size' | awk '{print $3}'";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum info " + testPackage + " 2>/dev/null | grep 'Installed Size' | awk '{print $4}'";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Qi " + testPackage + " 2>/dev/null | grep 'Installed Size' | awk '{print $4\" \"$5}'";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "软件包 '" << testPackage << "' 安装大小: 无法获取或软件包不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "软件包 '" << testPackage << "' 安装大小: " << result;
    return RE_SUCCESS;
}

int doGetLastBootKernelVersion(int index) {
    std::string result = showExec("uname -r 2>&1");
    printIndex(index);
    std::cout << "上次启动内核版本: " << result;
    return RE_SUCCESS;
}

int doCheckKernelModulesCompatibility(int index) {
    // This is a complex task and typically requires deep kernel knowledge.
    // A simplified approach might involve checking dmesg for module loading errors.
    std::string result = showExec("dmesg | grep -i 'module' | grep -i 'error' | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "内核模块兼容性检查: 未发现明显错误信息。\n";
        return RE_SUCCESS;
    }
    std::cout << "内核模块兼容性警告/错误 (部分): \n" << result;
    return ERROR_PARA;
}

int doGetCpuTemperatureSensorPath(int index) {
    std::string result = showExec("find /sys/class/hwmon -name 'temp*_input' | head -n 1 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU温度传感器路径: 无法找到 (可能未安装sensors或硬件不支持)。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU温度传感器路径 (示例): " << result;
    return RE_SUCCESS;
}

int doShowSystemVoltageSummary(int index) {
    std::string result = showExec("sensors | grep 'in' | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统电压摘要: 无法获取 (可能未安装sensors)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统电压摘要 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetFanSpeedSummary(int index) {
    std::string result = showExec("sensors | grep 'Fan' | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "风扇速度摘要: 无法获取 (可能未安装sensors)。\n";
        return ERROR_PARA;
    }
    std::cout << "风扇速度摘要 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowDiskSmartStatus(int index) {
    std::string testDisk = "/dev/sda"; // Example, would come from args
    std::string result = showExec("sudo smartctl -H " + testDisk + " 2>/dev/null | grep 'SMART overall-health self-assessment test result:' | awk -F': ' '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘 " << testDisk << " SMART状态: 无法获取 (可能需要sudo或smartmontools未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘 " << testDisk << " SMART状态: " << result;
    return (result.find("PASSED") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetTotalMemoryInstalled(int index) {
    std::string result = showExec("grep MemTotal /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "总安装内存: " << result;
    return RE_SUCCESS;
}

int doGetMemoryFreeAmount(int index) {
    std::string result = showExec("grep MemAvailable /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "空闲内存量: " << result;
    return RE_SUCCESS;
}

int doGetMemoryUsedAmount(int index) {
    std::string result = showExec("grep MemTotal /proc/meminfo | awk '{total=$2} END {printf \"%.2f GB\\n\", (total - (($(grep MemAvailable /proc/meminfo | awk '{print $2}') + $(grep Buffers /proc/meminfo | awk '{print $2}') + $(grep Cached /proc/meminfo | awk '{print $2}'))))/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "已用内存量: " << result;
    return RE_SUCCESS;
}

int doShowSwapMemoryUsed(int index) {
    std::string result = showExec("grep SwapUsed /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "已用交换内存: " << result;
    return RE_SUCCESS;
}

int doShowSwapMemoryFree(int index) {
    std::string result = showExec("grep SwapFree /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "空闲交换内存: " << result;
    return RE_SUCCESS;
}

int doShowTopFiveCpuProcesses(int index) {
    std::string result = showExec("ps aux --sort=-%cpu | head -n 6 2>&1"); // includes header
    printIndex(index);
    std::cout << "CPU占用前五进程: \n" << result;
    return RE_SUCCESS;
}

int doShowTopFiveMemoryProcesses(int index) {
    std::string result = showExec("ps aux --sort=-%mem | head -n 6 2>&1"); // includes header
    printIndex(index);
    std::cout << "内存占用前五进程: \n" << result;
    return RE_SUCCESS;
}

int doGetProcessNiceValue(int index) {
    std::string testPid = "1"; // Example, would come from args
    std::string result = showExec("ps -p " + testPid + " -o nice --no-headers 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 的Nice值: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 的Nice值: " << result;
    return RE_SUCCESS;
}

int doShowProcessChildrenPids(int index) {
    std::string testPid = "1"; // Example, would come from args
    std::string result = showExec("pgrep -P " + testPid + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 的子进程PID: 无。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 的子进程PID: \n" << result;
    return RE_SUCCESS;
}

int doGetProcessParentPid(int index) {
    std::string testPid = "1"; // Example, would come from args
    std::string result = showExec("ps -p " + testPid + " -o ppid --no-headers 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 的父进程PID: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 的父进程PID: " << result;
    return RE_SUCCESS;
}

int doShowCurrentUsersLoginShell(int index) {
    std::string result = showExec("echo $SHELL 2>&1");
    printIndex(index);
    std::cout << "当前用户登录Shell: " << result;
    return RE_SUCCESS;
}

int doListAllLoginRecords(int index) {
    std::string result = showExec("last -w | head -n 10 2>&1");
    printIndex(index);
    std::cout << "所有登录记录 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetLastSuccessfulLoginUser(int index) {
    std::string result = showExec("last -n 1 | grep -v 'reboot' | grep -v 'wtmp' | awk '{print $1}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "上次成功登录用户: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "上次成功登录用户: " << result;
    return RE_SUCCESS;
}

int doGetLastFailedLoginUser(int index) {
    std::string result = showExec("lastb -n 1 | awk '{print $1}' 2>&1");
    printIndex(index);
    if (result.empty() || result.find("btmp begins") != std::string::npos) {
        std::cout << "上次失败登录用户: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "上次失败登录用户: " << result;
    return RE_SUCCESS;
}

int doShowUserGroupMemberships(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("groups " + testUser + " 2>&1");
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 的组员身份: " << result;
    return RE_SUCCESS;
}

int doShowAvailableShellsForUser(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("chsh -l 2>/dev/null"); // Lists all available shells for the system
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 可用Shell: \n" << result;
    return RE_SUCCESS;
}

int doGetSystemDefaultTimezone(int index) {
    std::string result = showExec("timedatectl | grep 'Time zone:' | awk '{print $3}' 2>&1");
    printIndex(index);
    std::cout << "系统默认时区: " << result;
    return RE_SUCCESS;
}

int doShowAllSetEnvironmentVariables(int index) {
    std::string result = showExec("env | head -n 10 2>&1");
    printIndex(index);
    std::cout << "所有设置的环境变量 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetSpecificEnvironmentVariable(int index) {
    std::string testVar = "PATH"; // Example, would come from args
    std::string result = showExec("echo $" + testVar + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "环境变量 '" << testVar << "' 的值: 未设置。\n";
        return ERROR_PARA;
    }
    std::cout << "环境变量 '" << testVar << "' 的值: " << result;
    return RE_SUCCESS;
}

int doShowCurrentUsersHomeDirectory(int index) {
    std::string result = showExec("echo $HOME 2>&1");
    printIndex(index);
    std::cout << "当前用户主目录: " << result;
    return RE_SUCCESS;
}

int doShowCurrentUserPrimaryGroup(int index) {
    std::string result = showExec("id -gn 2>&1");
    printIndex(index);
    std::cout << "当前用户主要组: " << result;
    return RE_SUCCESS;
}

int doGetSystemRunlevelHistory(int index) {
    std::string result = showExec("last runlevel | head -n 5 2>&1");
    printIndex(index);
    if (result.empty() || result.find("wtmp begins") != std::string::npos) {
        std::cout << "系统运行级别历史: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "系统运行级别历史 (前5条): \n" << result;
    return RE_SUCCESS;
}

int doListAllSystemServices(int index) {
    std::string result = showExec("systemctl list-units --type=service --all --no-pager | head -n 10 2>&1");
    printIndex(index);
    std::cout << "所有系统服务 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doCheckServiceRunningStatus(int index) {
    std::string testService = "ssh"; // Example, would come from args
    std::string result = showExec("systemctl is-active " + testService + " 2>&1");
    printIndex(index);
    std::cout << "服务 '" << testService << "' 运行状态: " << result;
    return (result.find("active") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetSystemdActiveUnitCount(int index) {
    std::string result = showExec("systemctl list-units --state=active --no-pager | grep -c '.service' 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {
        std::cout << "Systemd活动单元数量: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd活动单元数量: " << count << "\n";
    return RE_SUCCESS;
}

int doShowSystemdFailedUnitCount(int index) {
    std::string result = showExec("systemctl list-units --state=failed --no-pager | grep -c '.service' 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {
        std::cout << "Systemd失败单元数量: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd失败单元数量: " << count << "\n";
    return RE_SUCCESS;
}

int doShowDiskHealthOverview(int index) {
    // This is a high-level check and ideally requires `smartctl` with elevated privileges.
    // A non-privileged command is difficult for a comprehensive "health overview".
    std::string result = showExec("df -h --total | tail -n 1 2>&1");
    printIndex(index);
    std::cout << "磁盘健康概览 (总览): \n" << result; // Reusing df for a general overview
    return RE_SUCCESS;
}

int doListAllMountedFilesystems(int index) {
    std::string result = showExec("mount | head -n 10 2>&1");
    printIndex(index);
    std::cout << "所有已挂载文件系统 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetFileSystemLabel(int index) {
    std::string testDevice = "/dev/sda1"; // Example, would come from args
    std::string result = showExec("lsblk -no LABEL " + testDevice + " 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件系统 '" << testDevice << "' 标签: 无法获取或设备不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "文件系统 '" << testDevice << "' 标签: " << result;
    return RE_SUCCESS;
}

int doShowFileSystemUsagePercent(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("df -h " + testPath + " | awk 'NR==2 {print $5}' 2>&1");
    printIndex(index);
    std::cout << "文件系统 '" << testPath << "' 使用百分比: " << result;
    return RE_SUCCESS;
}

int doCheckIfPathIsMountPoint(int index) {
    std::string testPath = "/mnt"; // Example, would come from args
    std::string cmd = "findmnt -M " + testPath + " >/dev/null 2>&1 && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "路径 '" << testPath << "' 是否为挂载点: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowSystemLogsByType(int index) {
    // Example: only errors from syslog. For full log, would be complex parsing.
    std::string result = showExec("journalctl -p err --since \"yesterday\" | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统日志错误类型 (昨日至今，前5条): 无。\n";
        return RE_SUCCESS;
    }
    std::cout << "系统日志错误类型 (昨日至今，前5条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemBootTimeHumanReadable(int index) {
    std::string result = showExec("uptime -s 2>&1");
    printIndex(index);
    std::cout << "系统启动时间 (可读): " << result;
    return RE_SUCCESS;
}

int doShowKernelRingBufferContent(int index) {
    std::string result = showExec("dmesg | head -n 10 2>&1");
    printIndex(index);
    std::cout << "内核环形缓冲区内容 (前10行): \n" << result;
    return RE_SUCCESS;
}

int doShowRecentDmesgErrors(int index) {
    std::string result = showExec("dmesg -T --level=err,warn | tail -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "最近dmesg错误/警告: 无。\n";
        return RE_SUCCESS; // No errors is a success
    }
    std::cout << "最近dmesg错误/警告 (最后5条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemLoadAverageHistory(int index) {
    std::string result = showExec("uptime | awk '{print $10, $11, $12}' 2>&1");
    printIndex(index);
    std::cout << "系统平均负载历史: " << result;
    return RE_SUCCESS;
}

int doShowCpuCoreOnlineStatus(int index) {
    std::string result = showExec("grep -H . /sys/devices/system/cpu/cpu*/online 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU核心在线状态: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU核心在线状态: \n" << result;
    return RE_SUCCESS;
}

int doGetTotalCpuThreads(int index) {
    std::string result = showExec("nproc 2>&1");
    printIndex(index);
    std::cout << "CPU总线程数: " << result;
    return RE_SUCCESS;
}


int doShowMemoryBufferUsage(int index) {
    std::string result = showExec("grep Buffers /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "内存缓冲区使用量: " << result;
    return RE_SUCCESS;
}

int doGetTopTenLargestFiles(int index) {
    std::string testPath = "/var/log"; // Example, would come from args
    std::string result = showExec("find " + testPath + " -type f -exec du -sh {} + | sort -rh | head -n 10 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "目录 '" << testPath << "' 中最大的十个文件: 未找到或无权限。\n";
        return ERROR_PARA;
    }
    std::cout << "目录 '" << testPath << "' 中最大的十个文件: \n" << result;
    return RE_SUCCESS;
}

int doShowDirectoryModificationTime(int index) {
    std::string testDir = "/tmp"; // Example, would come from args
    std::string result = showExec("stat -c %y " + testDir + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "目录 '" << testDir << "' 最后修改时间: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "目录 '" << testDir << "' 最后修改时间: " << result;
    return RE_SUCCESS;
}

int doGetFilesystemIoStatistics(int index) {
    std::string result = showExec("iostat -xk 1 1 2>/dev/null | tail -n 3");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件系统IO统计: 无法获取 (可能未安装sysstat/iostat)。\n";
        return ERROR_PARA;
    }
    std::cout << "文件系统IO统计 (快照): \n" << result;
    return RE_SUCCESS;
}

int doCheckIfPartitionIsMounted(int index) {
    std::string testPartition = "/dev/sda1"; // Example, would come from args
    std::string cmd = "mount | grep -q " + testPartition + " && echo \"已挂载\" || echo \"未挂载\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "分区 '" << testPartition << "' 是否已挂载: " << result;
    return (result.find("已挂载") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowDiskUsageForUserHome(int index) {
    std::string result = showExec("du -sh $HOME 2>&1");
    printIndex(index);
    std::cout << "用户主目录磁盘使用量: " << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceLinkStatus(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip link show " + testInterface + " | grep 'state' | awk '{print $9}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 链接状态: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 链接状态: " << result;
    return RE_SUCCESS;
}

int doCheckNetworkConnectivityToGateway(int index) {
    std::string gatewayIp = showExec("ip route | grep default | awk '{print $3}' 2>&1");
    if (gatewayIp.empty()) {
        printIndex(index);
        std::cout << "无法获取网关IP，跳过连接性检查。\n";
        return ERROR_PARA;
    }
    std::string cmd = "ping -c 1 " + gatewayIp + " >/dev/null 2>&1 && echo \"成功\" || echo \"失败\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "到网关 (" << gatewayIp.substr(0, gatewayIp.find('\n')) << ") 的网络连接性: " << result;
    return (result.find("成功") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowActiveListeningPorts(int index) {
    std::string result = showExec("ss -ltn | head -n 10 2>&1");
    printIndex(index);
    std::cout << "活动监听端口 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doListNetworkInterfacesWithIp(int index) {
    std::string result = showExec("ip -4 -o addr show | awk '{print $2\" : \"$4}' 2>&1");
    printIndex(index);
    std::cout << "带有IP的网络接口: \n" << result;
    return RE_SUCCESS;
}

int doCheckHostnameResolution(int index) {
    std::string testHost = "localhost"; // Example, would come from args
    std::string result = showExec("getent hosts " + testHost + " >/dev/null 2>&1 && echo \"成功\" || echo \"失败\"");
    printIndex(index);
    std::cout << "主机名 '" << testHost << "' 解析: " << result;
    return (result.find("成功") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowCurrentUserName(int index) {
    std::string result = showExec("whoami 2>&1");
    printIndex(index);
    std::cout << "当前用户名: " << result;
    return RE_SUCCESS;
}

int doGetUserIdNumber(int index) {
    std::string result = showExec("id -u 2>&1");
    printIndex(index);
    std::cout << "用户ID号: " << result;
    return RE_SUCCESS;
}

int doListUsersInSpecificGroup(int index) {
    std::string testGroup = "sudo"; // Example, would come from args
    std::string result = showExec("getent group " + testGroup + " | cut -d: -f4 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "组 '" << testGroup << "' 中的用户: 未找到组或无成员。\n";
        return ERROR_PARA;
    }
    std::cout << "组 '" << testGroup << "' 中的用户: " << result;
    return RE_SUCCESS;
}

int doShowUserLoginShells(int index) {
    std::string result = showExec("cat /etc/passwd | cut -d: -f1,7 | head -n 10 2>&1");
    printIndex(index);
    std::cout << "用户登录Shell (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemDefaultLanguage(int index) {
    std::string result = showExec("echo $LANG 2>&1");
    printIndex(index);
    std::cout << "系统默认语言: " << result;
    return RE_SUCCESS;
}

int doShowAllLoadedFonts(int index) {
    std::string result = showExec("fc-list | head -n 10 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "所有加载的字体: 无法获取 (可能未安装fontconfig)。\n";
        return ERROR_PARA;
    }
    std::cout << "所有加载的字体 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetGraphicalDesktopEnvironment(int index) {
    std::string result = showExec("echo $XDG_CURRENT_DESKTOP 2>&1 || echo $DESKTOP_SESSION 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "图形桌面环境: 无法检测 (可能不在图形会话中)。\n";
        return ERROR_PARA;
    }
    std::cout << "图形桌面环境: " << result;
    return RE_SUCCESS;
}

int doCheckIfXServerIsRunning(int index) {
    std::string cmd = "pgrep -x Xorg >/dev/null 2>&1 && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "X服务器是否正在运行: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowCurrentDisplayResolution(int index) {
    std::string result = showExec("xdpyinfo | grep dimensions | awk '{print $2}' 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "当前显示分辨率: 无法获取 (可能未安装xdpyinfo或不在图形会话中)。\n";
        return ERROR_PARA;
    }
    std::cout << "当前显示分辨率: " << result;
    return RE_SUCCESS;
}

int doListAllInstalledPackages(int index) {
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "dpkg -l | head -n 10";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf list installed | head -n 10";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum list installed | head -n 10";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Q | head -n 10";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "所有已安装软件包 (前10条): 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "所有已安装软件包 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetPackageDependencies(int index) {
    std::string testPackage = "apache2"; // Example, would come from args
    std::string cmd = "";
    if (!showExec("which apt-cache 2>/dev/null").empty()) {
        cmd = "apt-cache depends " + testPackage + " 2>/dev/null | head -n 5";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf repoquery --requires " + testPackage + " 2>/dev/null | head -n 5";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "repoquery --requires " + testPackage + " 2>/dev/null | head -n 5";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Qi " + testPackage + " 2>/dev/null | grep Depends | head -n 5";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "软件包 '" << testPackage << "' 依赖项: 无法获取或软件包不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "软件包 '" << testPackage << "' 依赖项 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowPackageVersion(int index) {
    std::string testPackage = "curl"; // Example, would come from args
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "apt show " + testPackage + " 2>/dev/null | grep 'Version:' | awk '{print $2}'";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf info " + testPackage + " 2>/dev/null | grep 'Version' | awk '{print $3}'";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum info " + testPackage + " 2>/dev/null | grep 'Version' | awk '{print $3}'";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Qi " + testPackage + " 2>/dev/null | grep 'Version' | awk '{print $3}'";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "软件包 '" << testPackage << "' 版本: 无法获取或软件包不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "软件包 '" << testPackage << "' 版本: " << result;
    return RE_SUCCESS;
}

int doGetPackageManagerRepositoryList(int index) {
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "grep -rhE 'deb |deb-src ' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | head -n 10";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "grep -rh '^name' /etc/yum.repos.d/ 2>/dev/null | head -n 10"; // dnf uses yum repos
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "grep -rh '^name' /etc/yum.repos.d/ 2>/dev/null | head -n 10";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "grep -A 1 '\\[.*\\]' /etc/pacman.conf 2>/dev/null | grep -E '^\\[|Server =' | head -n 10";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "包管理器仓库列表: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "包管理器仓库列表 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowCpuUtilizationPerCore(int index) {
    // This is a snapshot. Continuous monitoring needs tools like 'mpstat' or 'htop'.
    std::string result = showExec("mpstat -P ALL 1 1 2>/dev/null | tail -n +4 | head -n -1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "每核心CPU利用率: 无法获取 (可能未安装sysstat/mpstat)。\n";
        return ERROR_PARA;
    }
    std::cout << "每核心CPU利用率: \n" << result;
    return RE_SUCCESS;
}

int doGetTotalRunningProcesses(int index) {
    std::string result = showExec("ps -e --no-headers | wc -l 2>&1");
    printIndex(index);
    std::cout << "总运行进程数: " << result;
    return RE_SUCCESS;
}

int doListProcessesByUser(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("ps -u " + testUser + " --no-headers | head -n 10 2>&1");
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 的进程 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowSystemdServiceDependencies(int index) {
    std::string testService = "apache2.service"; // Example, would come from args
    std::string result = showExec("systemctl list-dependencies " + testService + " 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd服务 '" << testService << "' 依赖项: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd服务 '" << testService << "' 依赖项 (部分): \n" << result;
    return RE_SUCCESS;
}

int doCheckSystemdServiceActiveTime(int index) {
    std::string testService = "ssh.service"; // Example, would come from args
    std::string result = showExec("systemctl show -p ActiveEnterTimestamp " + testService + " 2>/dev/null | cut -d'=' -f2");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd服务 '" << testService << "' 活跃时间: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd服务 '" << testService << "' 活跃时间: " << result;
    return RE_SUCCESS;
}

int doGetSystemdServicePid(int index) {
    std::string testService = "cron.service"; // Example, would come from args
    std::string result = showExec("systemctl show -p MainPID " + testService + " 2>/dev/null | cut -d'=' -f2");
    printIndex(index);
    if (result.empty() || result.find("0") != std::string::npos) { // MainPID can be 0 if not running
        std::cout << "Systemd服务 '" << testService << "' PID: 无法获取或服务未运行。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd服务 '" << testService << "' PID: " << result;
    return RE_SUCCESS;
}

int doShowDiskPartitionTableType(int index) {
    std::string testDisk = "/dev/sda"; // Example, would come from args
    std::string result = showExec("sudo fdisk -l " + testDisk + " 2>/dev/null | grep 'Disklabel type:' | awk '{print $3}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘 '" << testDisk << "' 分区表类型: 无法获取 (可能需要sudo或fdisk未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘 '" << testDisk << "' 分区表类型: " << result;
    return RE_SUCCESS;
}

int doGetFileSystemInodeUsage(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("df -i " + testPath + " | awk 'NR==2 {print $5}' 2>&1");
    printIndex(index);
    std::cout << "文件系统 '" << testPath << "' Inode使用率: " << result;
    return RE_SUCCESS;
}

int doShowFileSystemBadBlocks(int index) {
    std::string testDevice = "/dev/sda1"; // Example, would come from args
    // Requires `badblocks` or `e2fsck -nv`. This is a non-destructive check.
    std::string result = showExec("sudo e2fsck -nv " + testDevice + " 2>&1 | grep 'bad blocks found' | awk '{print $1}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件系统 '" << testDevice << "' 坏块: 无法检查 (可能需要sudo或e2fsprogs未安装)。\n";
        return ERROR_PARA;
    }
    std::cout << "文件系统 '" << testDevice << "' 坏块数量: " << result;
    return RE_SUCCESS;
}

int doGetTotalSystemRam(int index) {
    std::string result = showExec("grep MemTotal /proc/meminfo | awk '{printf \"%s %s\\n\", $2, $3}' 2>&1");
    printIndex(index);
    std::cout << "系统总内存: " << result;
    return RE_SUCCESS;
}

int doGetFreeSystemRam(int index) {
    std::string result = showExec("grep MemFree /proc/meminfo | awk '{printf \"%s %s\\n\", $2, $3}' 2>&1");
    printIndex(index);
    std::cout << "系统空闲内存: " << result;
    return RE_SUCCESS;
}

int doGetUsedSystemRam(int index) {
    std::string result = showExec("free -h | grep Mem: | awk '{print $3}' 2>&1");
    printIndex(index);
    std::cout << "系统已用内存: " << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfacePacketCounts(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s link show " + testInterface + " | grep 'RX: bytes' -A 1 | grep -E 'packets|bytes' | awk '{print $1, $2, $3}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 包计数: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 包计数: \n" << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfaceErrorCounts(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s link show " + testInterface + " | grep 'errors' | awk '{print \"RX errors: \"$1\", TX errors: \"$2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 错误计数: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 错误计数: " << result;
    return RE_SUCCESS;
}


int doCheckIfUserIsSudoer(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string cmd = "sudo -l -U " + testUser + " >/dev/null 2>&1 && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 是否为sudoers: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowUserLastLoginTime(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("last -n 1 " + testUser + " | head -n 1 | awk '{print $NF}' 2>&1");
    printIndex(index);
    if (result.empty() || result.find("wtmp begins") != std::string::npos) {
        std::cout << "用户 '" << testUser << "' 上次登录时间: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 上次登录时间: " << result;
    return RE_SUCCESS;
}

int doGetSystemUserListFull(int index) {
    std::string result = showExec("cut -d: -f1,3,4,6,7 /etc/passwd | head -n 10 2>&1");
    printIndex(index);
    std::cout << "系统用户完整列表 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowUserDiskQuotaSummary(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("sudo repquota -s / | grep " + testUser + " 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户 '" << testUser << "' 磁盘配额摘要: 无法获取 (可能未启用配额或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 磁盘配额摘要: \n" << result;
    return RE_SUCCESS;
}

int doGetFilesystemUsedSpacePercent(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("df -h " + testPath + " | awk 'NR==2 {print $5}' 2>&1");
    printIndex(index);
    std::cout << "文件系统 '" << testPath << "' 已用空间百分比: " << result;
    return RE_SUCCESS;
}

int doShowFileSystemFreeSpaceHumanReadable(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("df -h " + testPath + " | awk 'NR==2 {print $4}' 2>&1");
    printIndex(index);
    std::cout << "文件系统 '" << testPath << "' 可用空间 (可读): " << result;
    return RE_SUCCESS;
}

int doGetFilePermissionsOctal(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %a " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 权限 (八进制): 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 权限 (八进制): " << result;
    return RE_SUCCESS;
}

int doShowFileSizeInBytes(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %s " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 大小 (字节): 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 大小 (字节): " << result;
    return RE_SUCCESS;
}

int doGetFileOwnerAndGroup(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %U:%G " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 所有者和组: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 所有者和组: " << result;
    return RE_SUCCESS;
}

int doShowCpuClockSpeedMHz(int index) {
    std::string result = showExec("grep 'cpu MHz' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    std::cout << "CPU时钟速度 (MHz): " << result;
    return RE_SUCCESS;
}

int doGetMemorySwapUsedPercentage(int index) {
    std::string result = showExec("free -h | grep Swap | awk '{print $3\"/\"$2\" (\"$3/$2*100\"%)\"}' 2>&1");
    printIndex(index);
    std::cout << "内存交换已用百分比: " << result;
    return RE_SUCCESS;
}

int doShowMemoryAvailableForApplications(int index) {
    std::string result = showExec("grep MemAvailable /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "应用程序可用内存: " << result;
    return RE_SUCCESS;
}

int doGetTotalProcessesSleeping(int index) {
    std::string result = showExec("ps -e --no-headers -o stat | grep -c S 2>&1");
    printIndex(index);
    std::cout << "总休眠进程数: " << result;
    return RE_SUCCESS;
}

int doShowProcessesInZombieState(int index) {
    std::string result = showExec("ps aux | grep -c 'Z' | grep -v 'grep' 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {
        std::cout << "僵尸状态进程: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "僵尸状态进程数: " << (count > 0 ? std::to_string(count -1) : "0") << "\n"; // Subtract 1 for grep process itself
    return RE_SUCCESS;
}

int doGetProcessCpuAffinity(int index) {
    std::string testPid = "1"; // Example, would come from args
    std::string result = showExec("taskset -cp " + testPid + " 2>/dev/null | grep 'current affinity list' | cut -d: -f2");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " CPU亲和性: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " CPU亲和性: " << result;
    return RE_SUCCESS;
}

int doShowProcessMemoryMaps(int index) {
    std::string testPid = "1"; // Example, would come from args
    std::string result = showExec("cat /proc/" + testPid + "/maps 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 内存映射 (前10条): 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 内存映射 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceMacAddress(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip link show " + testInterface + " | grep 'link/ether' | awk '{print $2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' MAC地址: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' MAC地址: " << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfaceStatistics(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s -h link show " + testInterface + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 统计信息: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 统计信息: \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkRouteTable(int index) {
    std::string result = showExec("ip route show 2>&1");
    printIndex(index);
    std::cout << "网络路由表: \n" << result;
    return RE_SUCCESS;
}

int doCheckIfPortIsOpen(int index) {
    std::string testHost = "localhost"; // Example, would come from args
    std::string testPort = "22";     // Example, would come from args
    std::string cmd = "nc -zvw1 " + testHost + " " + testPort + " 2>&1 | grep -q 'succeeded!' && echo \"开放\" || echo \"关闭\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "端口 '" << testPort << "' 在 '" << testHost << "' 上是否开放: " << result;
    return (result.find("开放") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowHostNameToIpMapping(int index) {
    std::string testHost = "google.com"; // Example, would come from args
    std::string result = showExec("dig +short " + testHost + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "主机名 '" << testHost << "' 到IP映射: 无法解析。\n";
        return ERROR_PARA;
    }
    std::cout << "主机名 '" << testHost << "' 到IP映射: \n" << result;
    return RE_SUCCESS;
}

int doGetLocalHostname(int index) {
    std::string result = showExec("hostname 2>&1");
    printIndex(index);
    std::cout << "本地主机名: " << result;
    return RE_SUCCESS;
}

int doShowDnsCacheStatistics(int index) {
    // This depends heavily on the DNS caching service used (e.g., systemd-resolved, dnsmasq, unbound)
    // For systemd-resolved:
    std::string result = showExec("sudo systemd-resolve --statistics 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "DNS缓存统计信息: 无法获取 (可能未运行systemd-resolved或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "DNS缓存统计信息 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemPackageCount(int index) {
    std::string cmd = "";
    if (!showExec("which dpkg 2>/dev/null").empty()) {
        cmd = "dpkg -l | grep -c '^ii' 2>&1";
    } else if (!showExec("which rpm 2>/dev/null").empty()) {
        cmd = "rpm -qa | wc -l 2>&1";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Q | wc -l 2>&1";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统软件包数量: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统软件包数量: " << result;
    return RE_SUCCESS;
}

int doCheckIfPackageIsInstalled(int index) {
    std::string testPackage = "nginx"; // Example, would come from args
    std::string cmd = "";
    if (!showExec("which dpkg 2>/dev/null").empty()) {
        cmd = "dpkg -s " + testPackage + " >/dev/null 2>&1 && echo \"已安装\" || echo \"未安装\"";
    } else if (!showExec("which rpm 2>/dev/null").empty()) {
        cmd = "rpm -q " + testPackage + " >/dev/null 2>&1 && echo \"已安装\" || echo \"未安装\"";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Q " + testPackage + " >/dev/null 2>&1 && echo \"已安装\" || echo \"未安装\"";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "软件包 '" << testPackage << "' 是否安装: 无法判断 (未知包管理器)。\n";
        return ERROR_PARA;
    }
    std::cout << "软件包 '" << testPackage << "' 是否安装: " << result;
    return (result.find("已安装") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowPackageUpdateStatus(int index) {
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "apt list --upgradable 2>/dev/null | wc -l 2>&1";
        std::string result = showExec(cmd);
        long count = 0;
        try {
            count = std::stol(result) - 1; // Subtract header line
        } catch (...) {}
        printIndex(index);
        std::cout << "软件包更新状态 (可升级数量): " << (count > 0 ? std::to_string(count) : "0") << "\n";
        return RE_SUCCESS;
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf check-update --quiet 2>/dev/null | wc -l 2>&1";
        std::string result = showExec(cmd);
        long count = 0;
        try {
            count = std::stol(result);
        } catch (...) {}
        printIndex(index);
        std::cout << "软件包更新状态 (可升级数量): " << count << "\n";
        return RE_SUCCESS;
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum check-update --quiet 2>/dev/null | wc -l 2>&1";
        std::string result = showExec(cmd);
        long count = 0;
        try {
            count = std::stol(result);
        } catch (...) {}
        printIndex(index);
        std::cout << "软件包更新状态 (可升级数量): " << count << "\n";
        return RE_SUCCESS;
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Qu --quiet | wc -l 2>&1";
        std::string result = showExec(cmd);
        long count = 0;
        try {
            count = std::stol(result);
        } catch (...) {}
        printIndex(index);
        std::cout << "软件包更新状态 (可升级数量): " << count << "\n";
        return RE_SUCCESS;
    }
    printIndex(index);
    std::cout << "软件包更新状态: 无法判断 (未知包管理器)。\n";
    return ERROR_PARA;
}


int doGetPackageManagerCacheSize(int index) {
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "sudo du -sh /var/cache/apt/archives/ 2>/dev/null | awk '{print $1}'";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "sudo du -sh /var/cache/dnf/ 2>/dev/null | awk '{print $1}'";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "sudo du -sh /var/cache/yum/ 2>/dev/null | awk '{print $1}'";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "sudo du -sh /var/cache/pacman/pkg/ 2>/dev/null | awk '{print $1}'";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "包管理器缓存大小: 无法获取 (可能需要sudo或无缓存)。\n";
        return ERROR_PARA;
    }
    std::cout << "包管理器缓存大小: " << result;
    return RE_SUCCESS;
}

int doShowSystemSecurityAuditLog(int index) {
    std::string result = showExec("sudo tail /var/log/auth.log 2>/dev/null | head -n 10"); // For Debian/Ubuntu
    if (result.empty()) {
        result = showExec("sudo tail /var/log/secure 2>/dev/null | head -n 10"); // For RedHat/CentOS
    }
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统安全审计日志 (前10行): 无法获取 (可能无权限或日志文件不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统安全审计日志 (前10行): \n" << result;
    return RE_SUCCESS;
}

int doCheckIfSelinuxEnforcing(int index) {
    std::string result = showExec("sestatus 2>/dev/null | grep 'Current mode:' | awk '{print $3}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "SELinux是否强制执行: 无法确定 (可能未安装selinux)。\n";
        return ERROR_PARA;
    }
    std::cout << "SELinux是否强制执行: " << result;
    return RE_SUCCESS;
}

int doShowSystemServiceUnitFileStatus(int index) {
    std::string testService = "cron.service"; // Example, would come from args
    std::string result = showExec("systemctl status " + testService + " 2>/dev/null | grep 'Loaded:' | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd服务 '" << testService << "' 单元文件状态: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd服务 '" << testService << "' 单元文件状态: " << result;
    return RE_SUCCESS;
}

int doGetSystemdTargetUnits(int index) {
    std::string result = showExec("systemctl list-units --type=target --all --no-pager | head -n 10 2>&1");
    printIndex(index);
    std::cout << "Systemd目标单元 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowSystemdServiceRuntimeStatus(int index) {
    std::string testService = "ssh.service"; // Example, would come from args
    std::string result = showExec("systemctl is-active " + testService + " 2>&1");
    printIndex(index);
    std::cout << "Systemd服务 '" << testService << "' 运行时状态: " << result;
    return RE_SUCCESS;
}

int doGetSystemdJournalSize(int index) {
    std::string result = showExec("sudo journalctl --disk-usage 2>/dev/null | head -n 1 | awk '{print $2$3}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd日志大小: 无法获取 (可能需要sudo或journalctl未运行)。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd日志大小: " << result;
    return RE_SUCCESS;
}

int doShowKernelModuleList(int index) {
    std::string result = showExec("lsmod | head -n 10 2>&1");
    printIndex(index);
    std::cout << "内核模块列表 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetLoadedKernelModulesCount(int index) {
    std::string result = showExec("lsmod | wc -l 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result) - 1; // Subtract header
    } catch (...) {}
    std::cout << "已加载内核模块数量: " << count << "\n";
    return RE_SUCCESS;
}

int doShowKernelVersionShort(int index) {
    std::string result = showExec("uname -r 2>&1");
    printIndex(index);
    std::cout << "内核版本 (短): " << result;
    return RE_SUCCESS;
}


int doCheckSystemClockHardwareTimeSync(int index) {
    std::string result = showExec("timedatectl | grep 'RTC in local TZ:' | awk '{print $4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统时钟硬件时间同步状态: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统时钟硬件时间同步状态: " << result;
    return RE_SUCCESS;
}

int doShowSystemEntropyAvailable(int index) {
    std::string result = showExec("cat /proc/sys/kernel/random/entropy_avail 2>&1");
    printIndex(index);
    std::cout << "系统可用熵值: " << result;
    return RE_SUCCESS;
}

int doGetSystemRandomPoolSize(int index) {
    std::string result = showExec("cat /proc/sys/kernel/random/poolsize 2>&1");
    printIndex(index);
    std::cout << "系统随机池大小: " << result;
    return RE_SUCCESS;
}

int doShowSystemTemperatureOverall(int index) {
    std::string result = showExec("sensors | grep 'temp' | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统整体温度: 无法获取 (可能未安装sensors)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统整体温度 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetBatteryChargeLevel(int index) {
    std::string result = showExec("upower -i /org/freedesktop/UPower/devices/battery_BAT0 2>/dev/null | grep 'percentage' | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "电池电量: 无法获取 (可能无电池或未安装upower)。\n";
        return ERROR_PARA;
    }
    std::cout << "电池电量: " << result;
    return RE_SUCCESS;
}

int doShowBatteryHealthStatus(int index) {
    // This is more complex and depends on reading specific ACPI/UPower details.
    // A simplified approach might involve checking 'state' and 'capacity'
    std::string result = showExec("upower -i /org/freedesktop/UPower/devices/battery_BAT0 2>/dev/null | grep 'state' | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "电池健康状态: 无法获取 (可能无电池或未安装upower)。\n";
        return ERROR_PARA;
    }
    std::cout << "电池健康状态 (充电状态): " << result;
    return RE_SUCCESS;
}

int doGetCpuUsagePercentageOverall(int index) {
    std::string result = showExec("grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print usage \"%\"}' 2>&1");
    printIndex(index);
    std::cout << "CPU整体使用百分比: " << result;
    return RE_SUCCESS;
}

int doShowMemoryUsagePercentageOverall(int index) {
    std::string result = showExec("free | grep Mem: | awk '{printf \"%.2f%%\\n\", $3/$2*100}' 2>&1");
    printIndex(index);
    std::cout << "内存整体使用百分比: " << result;
    return RE_SUCCESS;
}

int doGetTotalSwapSpace(int index) {
    std::string result = showExec("grep SwapTotal /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "总交换空间: " << result;
    return RE_SUCCESS;
}

int doShowInstalledFontsCount(int index) {
    std::string result = showExec("fc-list | wc -l 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "已安装字体数量: 无法获取 (可能未安装fontconfig)。\n";
        return ERROR_PARA;
    }
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {}
    std::cout << "已安装字体数量: " << count << "\n";
    return RE_SUCCESS;
}

int doGetSystemDefaultPrinter(int index) {
    std::string result = showExec("lpstat -d 2>/dev/null | awk '{print $NF}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统默认打印机: 未设置或无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统默认打印机: " << result;
    return RE_SUCCESS;
}


int doListAllCronJobsForUser(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("sudo crontab -l -u " + testUser + " 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户 '" << testUser << "' 的所有Cron作业: 无或无权限。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 的所有Cron作业 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowUserHistoryCommandCount(int index) {
    std::string result = showExec("history | wc -l 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {}
    std::cout << "用户历史命令数量: " << count << "\n";
    return RE_SUCCESS;
}

int doGetSystemUptimeInDays(int index) {
    std::string result = showExec("uptime -p | awk '{print $2}' 2>&1"); // Gets days from "up X days"
    printIndex(index);
    if (result.empty() || result.find("up") == std::string::npos) {
        std::cout << "系统运行时间 (天): 无法获取。\n";
        return ERROR_PARA;
    }
    // Extract numerical part if "days" is present
    size_t pos = result.find("天");
    if (pos != std::string::npos) {
        result = result.substr(0, pos);
    }
    std::cout << "系统运行时间 (天): " << result;
    return RE_SUCCESS;
}

int doShowLastFiveLoggedUsers(int index) {
    std::string result = showExec("last -n 5 -w | grep -v 'wtmp' | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "最后五位登录用户: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "最后五位登录用户: \n" << result;
    return RE_SUCCESS;
}

int doGetSystemHostnameFullyQualified(int index) {
    std::string result = showExec("hostname -f 2>&1");
    printIndex(index);
    std::cout << "系统完全限定主机名: " << result;
    return RE_SUCCESS;
}

int doShowNetworkTrafficPerInterface(int index) {
    std::string result = showExec("sar -n DEV 1 1 2>/dev/null | grep -E '^Average:' | tail -n +2 | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "每个接口的网络流量: 无法获取 (可能未安装sysstat/sar)。\n";
        return ERROR_PARA;
    }
    std::cout << "每个接口的网络流量 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetNetworkPacketLossPercentage(int index) {
    std::string testHost = "8.8.8.8"; // Example, would come from args
    std::string result = showExec("ping -c 4 " + testHost + " 2>&1 | grep 'packet loss' | awk '{print $6}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "到 '" << testHost << "' 的网络丢包百分比: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "到 '" << testHost << "' 的网络丢包百分比: " << result;
    return RE_SUCCESS;
}

int doShowFirewallRulesCount(int index) {
    std::string result = showExec("sudo iptables -L -n | grep -c '^Chain' 2>/dev/null");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {}
    std::cout << "防火墙规则链数量: " << count << "\n";
    return RE_SUCCESS;
}

int doGetOpenFileCountSystemWide(int index) {
    std::string result = showExec("sysctl fs.file-nr | awk '{print $1}' 2>&1");
    printIndex(index);
    std::cout << "系统范围内打开的文件句柄数: " << result;
    return RE_SUCCESS;
}

int doShowTopTenLargestDirectories(int index) {
    std::string testPath = "/var"; // Example, would come from args
    std::string result = showExec("sudo du -h " + testPath + " | sort -rh | head -n 10 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "目录 '" << testPath << "' 中最大的十个目录: 未找到或无权限。\n";
        return ERROR_PARA;
    }
    std::cout << "目录 '" << testPath << "' 中最大的十个目录: \n" << result;
    return RE_SUCCESS;
}

int doShowDiskIoReadWriteSpeed(int index) {
    std::string testDisk = "sda"; // Example, would come from args
    // Requires iostat
    std::string result = showExec("iostat -d " + testDisk + " 1 2 2>/dev/null | tail -n 2 | head -n 1 | awk '{print \"读: \"$3\"KB/s, 写: \"$4\"KB/s\"}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘 '" << testDisk << "' IO读写速度: 无法获取 (可能未安装sysstat/iostat或磁盘不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘 '" << testDisk << "' IO读写速度 (平均): " << result;
    return RE_SUCCESS;
}

int doGetTotalDiskSpaceHumanReadable(int index) {
    std::string result = showExec("df -h --total | tail -n 1 | awk '{print $2}' 2>&1");
    printIndex(index);
    std::cout << "总磁盘空间 (可读): " << result;
    return RE_SUCCESS;
}

int doShowAvailableDiskSpaceHumanReadable(int index) {
    std::string result = showExec("df -h --total | tail -n 1 | awk '{print $4}' 2>&1");
    printIndex(index);
    std::cout << "可用磁盘空间 (可读): " << result;
    return RE_SUCCESS;
}

int doCheckIfServiceIsEnabledAtBoot(int index) {
    std::string testService = "apache2.service"; // Example, would come from args
    std::string result = showExec("systemctl is-enabled " + testService + " 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "服务 '" << testService << "' 是否开机启用: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "服务 '" << testService << "' 是否开机启用: " << result;
    return (result.find("enabled") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowSystemdServiceFailureReasons(int index) {
    std::string testService = "nginx.service"; // Example, would come from args
    std::string result = showExec("systemctl status " + testService + " 2>/dev/null | grep 'Active: failed' -A 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd服务 '" << testService << "' 失败原因: 未失败或无详细信息。\n";
        return RE_SUCCESS;
    }
    std::cout << "Systemd服务 '" << testService << "' 失败原因 (部分): \n" << result;
    return ERROR_PARA;
}


int doShowKernelVersionDetails(int index) {
    std::string result = showExec("uname -a 2>&1");
    printIndex(index);
    std::cout << "内核版本详情: " << result;
    return RE_SUCCESS;
}

int doGetKernelBuildDate(int index) {
    std::string result = showExec("uname -v 2>&1 | awk '{print $NF}'");
    printIndex(index);
    std::cout << "内核构建日期: " << result;
    return RE_SUCCESS;
}

int doShowCpuInterruptStatistics(int index) {
    std::string result = showExec("cat /proc/interrupts | head -n 10 2>&1");
    printIndex(index);
    std::cout << "CPU中断统计信息 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetMemoryUsedByKernel(int index) {
    std::string result = showExec("grep VmallocUsed /proc/meminfo | awk '{printf \"%.2f MB\\n\", $2/1024}' 2>&1");
    printIndex(index);
    std::cout << "内核使用内存量: " << result;
    return RE_SUCCESS;
}

int doShowMemorySlabUsage(int index) {
    std::string result = showExec("grep Slab /proc/meminfo | awk '{printf \"%.2f MB\\n\", $2/1024}' 2>&1");
    printIndex(index);
    std::cout << "内存Slab使用量: " << result;
    return RE_SUCCESS;
}

int doShowProcessStatusForPid(int index) {
    std::string testPid = "1"; // Example, would come from args
    std::string result = showExec("cat /proc/" + testPid + "/status 2>/dev/null | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 状态 (前5条): 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 状态 (前5条): \n" << result;
    return RE_SUCCESS;
}

int doGetProcessCpuTimeUsed(int index) {
    std::string testPid = "1"; // Example, would come from args
    // ps output format for cputime: [DD-]HH:MM:SS
    std::string result = showExec("ps -p " + testPid + " -o cputime --no-headers 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 已用CPU时间: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 已用CPU时间: " << result;
    return RE_SUCCESS;
}

int doShowUserLoggedInTty(int index) {
    std::string result = showExec("tty 2>&1");
    printIndex(index);
    std::cout << "用户登录TTY: " << result;
    return RE_SUCCESS;
}

int doGetSystemDefaultUserShell(int index) {
    std::string result = showExec("grep '^SHELL=' /etc/default/useradd 2>/dev/null | cut -d'=' -f2");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统默认用户Shell: 无法获取 (可能未设置或文件不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统默认用户Shell: " << result;
    return RE_SUCCESS;
}

int doShowAllSystemGroups(int index) {
    std::string result = showExec("cut -d: -f1 /etc/group | head -n 10 2>&1");
    printIndex(index);
    std::cout << "所有系统组 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetUsersPrimaryGroup(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("id -gn " + testUser + " 2>&1");
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 的主要组: " << result;
    return RE_SUCCESS;
}

int doShowSystemCurrentDateAndTime(int index) {
    std::string result = showExec("date 2>&1");
    printIndex(index);
    std::cout << "系统当前日期和时间: " << result;
    return RE_SUCCESS;
}

int doGetSystemTimezoneOffset(int index) {
    std::string result = showExec("date +%z 2>&1");
    printIndex(index);
    std::cout << "系统时区偏移: " << result;
    return RE_SUCCESS;
}

int doShowAllSystemLocales(int index) {
    std::string result = showExec("locale -a | head -n 10 2>&1");
    printIndex(index);
    std::cout << "所有系统语言环境 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetEnvironmentVariableForProcess(int index) {
    std::string testPid = "1"; // Example, would come from args
    std::string testVar = "PATH"; // Example, would come from args
    std::string result = showExec("sudo cat /proc/" + testPid + "/environ 2>/dev/null | tr '\\0' '\\n' | grep '^" + testVar + "=' | cut -d'=' -f2");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 的环境变量 '" << testVar << "': 无法获取或未设置 (可能需要sudo)。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 的环境变量 '" << testVar << "': " << result;
    return RE_SUCCESS;
}

int doShowUserLoginShellLocation(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("getent passwd " + testUser + " | cut -d: -f7 2>&1");
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 登录Shell位置: " << result;
    return RE_SUCCESS;
}

int doCheckIfUserAccountIsLocked(int index) {
    std::string testUser = "nobody"; // Example, would come from args
    std::string result = showExec("sudo passwd -S " + testUser + " 2>/dev/null | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户账户 '" << testUser << "' 是否锁定: 无法检查 (可能需要sudo或用户不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "用户账户 '" << testUser << "' 是否锁定: " << result; // L=Locked, P=Password, NP=No Password
    return (result.find("L") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowRecentLoginAttemptsByIp(int index) {
    std::string result = showExec("journalctl _COMM=sshd -g 'Failed password' | grep -oP 'from \\K[0-9.]+' | sort | uniq -c | sort -nr | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "按IP的最近登录尝试 (失败): 无。\n";
        return RE_SUCCESS;
    }
    std::cout << "按IP的最近登录尝试 (失败, 前5条): \n" << result;
    return RE_SUCCESS;
}

int doGetPackageLatestVersionAvailable(int index) {
    std::string testPackage = "nginx"; // Example, would come from args
    std::string cmd = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        cmd = "apt-cache policy " + testPackage + " 2>/dev/null | grep 'Candidate:' | awk '{print $2}'";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        cmd = "dnf info " + testPackage + " 2>/dev/null | grep 'Latest' | awk '{print $3}'"; // May vary
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        cmd = "yum info " + testPackage + " 2>/dev/null | grep 'Latest' | awk '{print $3}'"; // May vary
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        cmd = "pacman -Si " + testPackage + " 2>/dev/null | grep 'Version' | awk '{print $3}'";
    }
    std::string result = showExec(cmd);
    printIndex(index);
    if (result.empty()) {
        std::cout << "软件包 '" << testPackage << "' 可用最新版本: 无法获取或软件包不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "软件包 '" << testPackage << "' 可用最新版本: " << result;
    return RE_SUCCESS;
}

int doShowPackageChecksum(int index) {
    std::string testPackageFile = "/var/cache/apt/archives/apache2_2.4.52-1ubuntu4.1_amd64.deb"; // Example, needs actual path
    std::string cmd = "sha256sum " + testPackageFile + " 2>/dev/null | awk '{print $1}'";
    printIndex(index);
    std::string result = showExec(cmd);
    if (result.empty()) {
        std::cout << "软件包文件 '" << testPackageFile << "' 校验和: 无法获取 (文件不存在或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "软件包文件 '" << testPackageFile << "' 校验和 (SHA256): " << result;
    return RE_SUCCESS;
}

int doGetPackageManagerLogFileLocation(int index) {
    std::string logPath = "";
    if (!showExec("which apt 2>/dev/null").empty()) {
        logPath = "/var/log/apt/term.log";
    } else if (!showExec("which dnf 2>/dev/null").empty()) {
        logPath = "/var/log/dnf.log";
    } else if (!showExec("which yum 2>/dev/null").empty()) {
        logPath = "/var/log/yum.log";
    } else if (!showExec("which pacman 2>/dev/null").empty()) {
        logPath = "/var/log/pacman.log";
    }
    printIndex(index);
    if (logPath.empty()) {
        std::cout << "包管理器日志文件位置: 无法确定 (未知包管理器)。\n";
        return ERROR_PARA;
    }
    std::cout << "包管理器日志文件位置: " << logPath << "\n";
    return RE_SUCCESS;
}

int doShowCpuFrequencyScalingGovernor(int index) {
    std::string result = showExec("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU频率缩放调控器: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU频率缩放调控器: " << result;
    return RE_SUCCESS;
}

int doGetCpuTemperatureThresholds(int index) {
    std::string result = showExec("sensors | grep 'crit' | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU温度阈值: 无法获取 (可能未安装sensors)。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU温度阈值 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowSystemPowerConsumption(int index) {
    // This is very difficult without specific hardware sensors and tools (e.g., powertop, s-tui)
    // A simplified placeholder might be battery usage for laptops.
    std::string result = showExec("upower -i /org/freedesktop/UPower/devices/battery_BAT0 2>/dev/null | grep 'power' | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统功耗: 无法获取 (可能无电池或无专用传感器)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统功耗 (电池相关信息，部分): \n" << result;
    return RE_SUCCESS;
}

int doGetBatteryCycleCount(int index) {
    std::string result = showExec("upower -i /org/freedesktop/UPower/devices/battery_BAT0 2>/dev/null | grep 'cycle-count' | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "电池循环计数: 无法获取 (可能无电池或未安装upower)。\n";
        return ERROR_PARA;
    }
    std::cout << "电池循环计数: " << result;
    return RE_SUCCESS;
}

int doShowNetworkConnectionLatency(int index) {
    std::string testHost = "8.8.8.8"; // Example, would come from args
    std::string result = showExec("ping -c 1 " + testHost + " 2>&1 | grep 'time=' | awk -F'time=' '{print $2}' | awk '{print $1\" ms\"}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "到 '" << testHost << "' 的网络连接延迟: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "到 '" << testHost << "' 的网络连接延迟: " << result;
    return RE_SUCCESS;
}

int doCheckIfSshServiceIsRunning(int index) {
    std::string result = showExec("systemctl is-active sshd.service 2>&1");
    printIndex(index);
    std::cout << "SSH服务是否正在运行: " << result;
    return (result.find("active") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetTotalPhysicalMemory(int index) {
    std::string result = showExec("grep MemTotal /proc/meminfo | awk '{printf \"%.2f GB\\n\", $2/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "总物理内存: " << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceReceiveErrors(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s link show " + testInterface + " | grep 'RX: errors' | awk '{print $2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 接收错误数: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 接收错误数: " << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfaceTransmitErrors(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s link show " + testInterface + " | grep 'TX: errors' | awk '{print $2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 发送错误数: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 发送错误数: " << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceCollisions(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s link show " + testInterface + " | grep 'collisions' | awk '{print $1}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 冲突数: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 冲突数: " << result;
    return RE_SUCCESS;
}

int doShowKernelModuleParameters(int index) {
    std::string testModule = "ext4"; // Example, would come from args
    std::string result = showExec("modinfo " + testModule + " 2>/dev/null | grep '^parm:' | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "内核模块 '" << testModule << "' 参数: 无法获取或模块不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "内核模块 '" << testModule << "' 参数 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemOpenFilesLimit(int index) {
    std::string result = showExec("ulimit -n 2>&1");
    printIndex(index);
    std::cout << "系统打开文件限制: " << result;
    return RE_SUCCESS;
}

int doShowUserLoginHistory(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("last -n 5 " + testUser + " 2>&1");
    printIndex(index);
    if (result.empty() || result.find("wtmp begins") != std::string::npos) {
        std::cout << "用户 '" << testUser << "' 登录历史: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 登录历史 (前5条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemUsersHomeDirectory(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("getent passwd " + testUser + " | cut -d: -f6 2>&1");
    printIndex(index);
    std::cout << "系统用户 '" << testUser << "' 主目录: " << result;
    return RE_SUCCESS;
}

int doShowSystemUserGroups(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("id -Gn " + testUser + " 2>&1");
    printIndex(index);
    std::cout << "系统用户 '" << testUser << "' 所属组: " << result;
    return RE_SUCCESS;
}

int doGetFileInodeNumber(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %i " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' Inode号: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' Inode号: " << result;
    return RE_SUCCESS;
}

int doShowFileLastAccessTime(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %x " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 最后访问时间: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 最后访问时间: " << result;
    return RE_SUCCESS;
}

int doGetFileLastModificationTime(int index) {
    std::string testFile = "/etc/passwd"; // Example, would come from args
    std::string result = showExec("stat -c %y " + testFile + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件 '" << testFile << "' 最后修改时间: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "文件 '" << testFile << "' 最后修改时间: " << result;
    return RE_SUCCESS;
}

int doShowDirectorySizeHumanReadable(int index) {
    std::string testDir = "/var/log"; // Example, would come from args
    std::string result = showExec("du -sh " + testDir + " 2>&1 | awk '{print $1}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "目录 '" << testDir << "' 大小 (可读): 无法获取或目录不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "目录 '" << testDir << "' 大小 (可读): " << result;
    return RE_SUCCESS;
}

int doGetFilesystemBlockSize(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("stat -f -c %s " + testPath + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "文件系统 '" << testPath << "' 块大小: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "文件系统 '" << testPath << "' 块大小 (字节): " << result;
    return RE_SUCCESS;
}

int doShowFileSystemType(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("df -T " + testPath + " | awk 'NR==2 {print $2}' 2>&1");
    printIndex(index);
    std::cout << "文件系统 '" << testPath << "' 类型: " << result;
    return RE_SUCCESS;
}

int doGetCpuIdleTime(int index) {
    // Requires some calculation from /proc/stat
    std::string stat_output = showExec("cat /proc/stat | grep '^cpu '");
    if (stat_output.empty()) {
        printIndex(index);
        std::cout << "CPU空闲时间: 无法获取。\n";
        return ERROR_PARA;
    }
    long user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice;
    sscanf(stat_output.c_str(), "cpu %ld %ld %ld %ld %ld %ld %ld %ld %ld %ld",
           &user, &nice, &system, &idle, &iowait, &irq, &softirq, &steal, &guest, &guest_nice);
    printIndex(index);
    std::cout << "CPU空闲时间 (Jiffies): " << idle << "\n";
    return RE_SUCCESS;
}

int doGetMemoryUsedByBuffersAndCache(int index) {
    std::string result = showExec("free -m | grep 'Mem:' | awk '{print $6+$7\" MB\"}' 2>&1"); // buffers + cache
    printIndex(index);
    std::cout << "缓冲区和缓存使用的内存: " << result;
    return RE_SUCCESS;
}

int doShowMemoryActiveInactive(int index) {
    std::string result = showExec("grep -E 'Active:|Inactive:' /proc/meminfo | awk '{printf \"%s %s %s\\n\", $1, $2, $3}' 2>&1");
    printIndex(index);
    std::cout << "活跃/非活跃内存 (KB): \n" << result;
    return RE_SUCCESS;
}

int doGetTotalProcessThreads(int index) {
    std::string result = showExec("ps -eLf | wc -l 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result) - 1; // Subtract header
    } catch (...) {}
    std::cout << "总进程线程数: " << count << "\n";
    return RE_SUCCESS;
}

int doShowProcessCpuUsage(int index) {
    std::string testPid = "$(pgrep -o systemd)"; // Example, would come from args
    std::string result = showExec("ps -p " + testPid + " -o %cpu --no-headers 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " CPU使用率: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " CPU使用率 (%): " << result;
    return RE_SUCCESS;
}

int doGetProcessMemoryUsage(int index) {
    std::string testPid = "$(pgrep -o systemd)"; // Example, would come from args
    std::string result = showExec("ps -p " + testPid + " -o %mem --no-headers 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 内存使用率: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 内存使用率 (%): " << result;
    return RE_SUCCESS;
}

int doShowSystemdServiceMountPoints(int index) {
    std::string testService = "systemd-networkd.service"; // Example, would come from args
    std::string result = showExec("systemctl show " + testService + " 2>/dev/null | grep 'MountFlags=' | cut -d'=' -f2");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd服务 '" << testService << "' 挂载点: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd服务 '" << testService << "' 挂载点标志: " << result;
    return RE_SUCCESS;
}

int doGetSystemdServiceExecStartCommand(int index) {
    std::string testService = "cron.service"; // Example, would come from args
    std::string result = showExec("systemctl show " + testService + " 2>/dev/null | grep 'ExecStart=' | cut -d'=' -f2");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd服务 '" << testService << "' ExecStart命令: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd服务 '" << testService << "' ExecStart命令: " << result;
    return RE_SUCCESS;
}

int doShowSystemdServicePidFile(int index) {
    std::string testService = "sshd.service"; // Example, would come from args
    std::string result = showExec("systemctl show " + testService + " 2>/dev/null | grep 'PIDFile=' | cut -d'=' -f2");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd服务 '" << testService << "' PID文件: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd服务 '" << testService << "' PID文件: " << result;
    return RE_SUCCESS;
}

int doGetSystemLogFileLocation(int index) {
    std::string result = showExec("grep -E '^\s*LOG_FILE=' /etc/syslog.conf /etc/rsyslog.conf /etc/syslog-ng.conf 2>/dev/null | head -n 1 | awk -F'=' '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        result = "/var/log/syslog (通用)"; // Common fallback
        std::cout << "系统日志文件位置: " << result << " (自动检测失败，使用通用路径)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统日志文件位置: " << result;
    return RE_SUCCESS;
}

int doShowKernelRingBufferSize(int index) {
    std::string result = showExec("dmesg -s 2>/dev/null | wc -c 2>&1"); // Approximate size
    printIndex(index);
    if (result.empty()) {
        std::cout << "内核环形缓冲区大小: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "内核环形缓冲区大小 (字节): " << result;
    return RE_SUCCESS;
}

int doGetSystemBootMessageLocation(int index) {
    std::string result = showExec("dmesg | head -n 1 2>&1"); // Just show the command that holds boot messages
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统启动消息位置: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统启动消息位置 (通常通过dmesg): \n" << result; // This command prints the messages, not a file path
    return RE_SUCCESS;
}

int doShowNetworkInterfaceIpAddress(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -4 addr show " + testInterface + " | grep 'inet ' | awk '{print $2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' IP地址: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' IP地址: " << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceSubnetMask(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string ip_cidr = showExec("ip -4 addr show " + testInterface + " | grep 'inet ' | awk '{print $2}' 2>&1");
    printIndex(index);
    if (ip_cidr.empty()) {
        std::cout << "网卡 '" << testInterface << "' 子网掩码: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    // Extract CIDR, convert to mask (simple for /24 etc., more complex for arbitrary)
    size_t slash_pos = ip_cidr.find('/');
    if (slash_pos == std::string::npos) {
        std::cout << "网卡 '" << testInterface << "' 子网掩码: 无法解析CIDR。\n";
        return ERROR_PARA;
    }
    int cidr_len = std::stoi(ip_cidr.substr(slash_pos + 1));
    std::string subnet_mask = "";
    if (cidr_len >= 0 && cidr_len <= 32) {
        unsigned int mask = ~((1U << (32 - cidr_len)) - 1);
        subnet_mask = std::to_string((mask >> 24) & 0xFF) + "." +
                      std::to_string((mask >> 16) & 0xFF) + "." +
                      std::to_string((mask >> 8) & 0xFF) + "." +
                      std::to_string(mask & 0xFF);
    } else {
        subnet_mask = "无效CIDR";
    }
    std::cout << "网卡 '" << testInterface << "' 子网掩码: " << subnet_mask << "\n";
    return RE_SUCCESS;
}

int doShowNetworkInterfaceBroadcastAddress(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -4 addr show " + testInterface + " | grep 'inet ' | awk '{print $4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 广播地址: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 广播地址: " << result;
    return RE_SUCCESS;
}

int doCheckIfDefaultGatewayIsReachable(int index) {
    std::string gatewayIp = showExec("ip route | grep default | awk '{print $3}' 2>&1");
    if (gatewayIp.empty()) {
        printIndex(index);
        std::cout << "默认网关是否可达: 无法获取网关IP。\n";
        return ERROR_PARA;
    }
    std::string cmd = "ping -c 1 " + gatewayIp.substr(0, gatewayIp.find('\n')) + " >/dev/null 2>&1 && echo \"可达\" || echo \"不可达\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "默认网关 (" << gatewayIp.substr(0, gatewayIp.find('\n')) << ") 是否可达: " << result;
    return (result.find("可达") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doGetDnsServerIpAddresses(int index) {
    std::string result = showExec("grep 'nameserver' /etc/resolv.conf | awk '{print $2}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "DNS服务器IP地址: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "DNS服务器IP地址: \n" << result;
    return RE_SUCCESS;
}

int doShowCurrentWorkingDir(int index) {
    std::string result = showExec("pwd 2>&1");
    printIndex(index);
    std::cout << "当前工作目录: " << result;
    return RE_SUCCESS;
}

int doGetUserNameFromId(int index) {
    std::string testUid = "1000"; // Example, would come from args
    std::string result = showExec("getent passwd " + testUid + " | cut -d: -f1 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "ID '" << testUid << "' 对应的用户名: 未找到。\n";
        return ERROR_PARA;
    }
    std::cout << "ID '" << testUid << "' 对应的用户名: " << result;
    return RE_SUCCESS;
}

int doShowGroupIdFromName(int index) {
    std::string testGroupName = "users"; // Example, would come from args
    std::string result = showExec("getent group " + testGroupName + " | cut -d: -f3 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "组名 '" << testGroupName << "' 对应的GID: 未找到。\n";
        return ERROR_PARA;
    }
    std::cout << "组名 '" << testGroupName << "' 对应的GID: " << result;
    return RE_SUCCESS;
}

int doGetSystemDefaultGateway(int index) {
    std::string result = showExec("ip route | grep default | awk '{print $3}' 2>&1");
    printIndex(index);
    std::cout << "系统默认网关: " << result;
    return RE_SUCCESS;
}

int doShowSystemDefaultRouteMetric(int index) {
    std::string result = showExec("ip route | grep default | awk '{print $NF}' 2>&1"); // Last field is metric
    printIndex(index);
    std::cout << "系统默认路由跃点数: " << result;
    return RE_SUCCESS;
}

int doGetAvailableShellsOnSystem(int index) {
    std::string result = showExec("cat /etc/shells 2>&1 | head -n 5");
    printIndex(index);
    std::cout << "系统可用Shell (前5个): \n" << result;
    return RE_SUCCESS;
}

int doCheckIfUserCanSudoWithoutPassword(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string cmd = "sudo -n true 2>/dev/null && echo \"是\" || echo \"否\"";
    std::string result = showExec(cmd);
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 是否可以无密码使用sudo: " << result;
    return (result.find("是") != std::string::npos) ? RE_SUCCESS : ERROR_PARA;
}

int doShowSystemHostnameAliases(int index) {
    std::string result = showExec("hostnamectl | grep 'Static hostname:' -A 1 | tail -n 1 | cut -d: -f2"); // This is a bit indirect, might be empty
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统主机名别名: 无或无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "系统主机名别名: " << result;
    return RE_SUCCESS;
}

int doGetTotalConnectedUsers(int index) {
    std::string result = showExec("who | wc -l 2>&1");
    printIndex(index);
    std::cout << "总连接用户数: " << result;
    return RE_SUCCESS;
}

int doShowUserConnectedTerminals(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("who | grep " + testUser + " | awk '{print $2}' 2>&1");
    printIndex(index);
    std::cout << "用户 '" << testUser << "' 连接的终端: \n" << result;
    return RE_SUCCESS;
}

int doShowLoadedKernelModules(int index) {
    std::string result = showExec("lsmod | head -n 5 2>&1"); // Already provided 'lsmod | head -n 10'
    printIndex(index);
    std::cout << "已加载内核模块 (前5条): \n" << result;
    return RE_SUCCESS;
}


int doShowCpuCoreCount(int index) {
    std::string result = showExec("nproc --all 2>&1");
    printIndex(index);
    std::cout << "CPU核心总数 (逻辑): " << result;
    return RE_SUCCESS;
}

int doGetMemorySwapCached(int index) {
    std::string result = showExec("grep SwapCached /proc/meminfo | awk '{printf \"%.2f MB\\n\", $2/1024}' 2>&1");
    printIndex(index);
    std::cout << "内存交换缓存: " << result;
    return RE_SUCCESS;
}

int doGetSystemInitProcessPid(int index) {
    std::string result = showExec("cat /proc/1/comm 2>&1");
    printIndex(index);
    std::cout << "系统Init进程PID (名称): " << result;
    return RE_SUCCESS;
}


int doShowSystemProcessTree(int index) {
    std::string result = showExec("pstree -p -a | head -n 10 2>&1");
    printIndex(index);
    std::cout << "系统进程树 (部分): \n" << result;
    return RE_SUCCESS;
}


int doGetNetworkSocketStatistics(int index) {
    std::string result = showExec("ss -s 2>&1");
    printIndex(index);
    std::cout << "网络套接字统计信息: \n" << result;
    return RE_SUCCESS;
}

int doShowNetworkListenPorts(int index) {
    std::string result = showExec("ss -tuln | head -n 10 2>&1");
    printIndex(index);
    std::cout << "网络监听端口 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemDhcpClientInfo(int index) {
    std::string result = showExec("cat /var/lib/dhcp/dhclient.leases 2>/dev/null | head -n 10"); // Common location for leases
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统DHCP客户端信息: 无法获取 (可能未运行DHCP客户端或日志位置不同)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统DHCP客户端信息 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowMountedFileSystemsCount(int index) {
    std::string result = showExec("mount | wc -l 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {}
    std::cout << "已挂载文件系统数量: " << count << "\n";
    return RE_SUCCESS;
}

int doGetFileSystemTotalInodes(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("df -i " + testPath + " | awk 'NR==2 {print $2}' 2>&1");
    printIndex(index);
    std::cout << "文件系统 '" << testPath << "' 总Inode数: " << result;
    return RE_SUCCESS;
}

int doShowFileSystemFreeInodes(int index) {
    std::string testPath = "/"; // Example, would come from args
    std::string result = showExec("df -i " + testPath + " | awk 'NR==2 {print $4}' 2>&1");
    printIndex(index);
    std::cout << "文件系统 '" << testPath << "' 空闲Inode数: " << result;
    return RE_SUCCESS;
}

int doGetCpuVendorId(int index) {
    std::string result = showExec("grep 'vendor_id' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    std::cout << "CPU供应商ID: " << result;
    return RE_SUCCESS;
}

int doShowCpuBugFlags(int index) {
    std::string result = showExec("grep 'bugs' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU Bug标志: 无或无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU Bug标志: " << result;
    return RE_SUCCESS;
}

int doGetMemoryFreePercentage(int index) {
    std::string result = showExec("free | grep Mem: | awk '{printf \"%.2f%%\\n\", $4/$2*100}' 2>&1");
    printIndex(index);
    std::cout << "内存空闲百分比: " << result;
    return RE_SUCCESS;
}

int doShowMemoryUsedBySharedBuffers(int index) {
    std::string result = showExec("free -m | grep 'Mem:' | awk '{print $5\" MB\"}' 2>&1"); // shared buffer
    printIndex(index);
    std::cout << "共享缓冲区使用的内存: " << result;
    return RE_SUCCESS;
}

int doGetSystemLoadAverage(int index) {
    std::string result = showExec("uptime | awk '{print $NF}' 2>&1"); // Last field is 1-min load avg
    printIndex(index);
    std::cout << "系统平均负载 (1分钟): " << result;
    return RE_SUCCESS;
}

int doShowSystemBootTime(int index) {
    std::string result = showExec("uptime -s 2>&1");
    printIndex(index);
    std::cout << "系统启动时间: " << result;
    return RE_SUCCESS;
}

int doGetSystemKernelParameters(int index) {
    std::string result = showExec("sysctl -a | head -n 10 2>&1");
    printIndex(index);
    std::cout << "系统内核参数 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfaceQueueLength(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip link show " + testInterface + " | grep 'qlen' | awk '{print $NF}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 队列长度: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 队列长度: " << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfaceMulticastAddresses(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip maddr show " + testInterface + " 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 组播地址: 无或无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 组播地址: \n" << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfaceStatus(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip link show " + testInterface + " | grep 'state' | awk '{print $NF}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 状态: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 状态: " << result;
    return RE_SUCCESS;
}

int doGetSystemPacketFilterStatus(int index) {
    std::string result = showExec("sudo iptables -L -n 2>/dev/null | head -n 5");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统包过滤器状态: 无法获取 (可能未运行iptables或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统包过滤器状态 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowLastRebootTime(int index) {
    std::string result = showExec("last reboot | head -n 1 | awk '{print $5, $6, $7, $8}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "上次重启时间: 无记录。\n";
        return ERROR_PARA;
    }
    std::cout << "上次重启时间: " << result;
    return RE_SUCCESS;
}


int doShowUserLoggedInSessions(int index) {
    std::string testUser = "$(whoami)"; // Example, would come from args
    std::string result = showExec("loginctl list-sessions --no-legend | grep " + testUser + " | head -n 5 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "用户 '" << testUser << "' 登录会话: 无或无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "用户 '" << testUser << "' 登录会话 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetSystemRunningServices(int index) {
    std::string result = showExec("systemctl list-units --type=service --state=running --no-pager | grep '.service' | head -n 10 2>&1");
    printIndex(index);
    std::cout << "系统正在运行的服务 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowSystemAvailableRamSlots(int index) {
    // This is difficult to determine purely from software, often requires dmidecode (needs root)
    // Placeholder using lshw if available and user has permissions
    std::string result = showExec("sudo lshw -short -c memory 2>/dev/null | grep 'DIMM' | wc -l 2>&1");
    printIndex(index);
    long count = 0;
    try {
        count = std::stol(result);
    } catch (...) {}
    std::cout << "系统可用内存插槽数 (估算，可能需root): " << count << "\n";
    return count > 0 ? RE_SUCCESS : ERROR_PARA;
}

int doGetCpuThreadCountPerCore(int index) {
    std::string siblings = showExec("grep 'siblings' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    std::string cpu_cores = showExec("grep 'cpu cores' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    if (siblings.empty() || cpu_cores.empty()) {
        std::cout << "CPU每核心线程数: 无法获取。\n";
        return ERROR_PARA;
    }
    try {
        int s = std::stoi(siblings);
        int c = std::stoi(cpu_cores);
        if (c > 0) {
            std::cout << "CPU每核心线程数: " << (s / c) << "\n";
        } else {
            std::cout << "CPU每核心线程数: 无法计算 (核心数为0)。\n";
            return ERROR_PARA;
        }
    } catch (...) {
        std::cout << "CPU每核心线程数: 解析错误。\n";
        return ERROR_PARA;
    }
    return RE_SUCCESS;
}

int doShowDiskSerialNumber(int index) {
    std::string testDisk = "/dev/sda"; // Example, would come from args
    std::string result = showExec("sudo hdparm -i " + testDisk + " 2>/dev/null | grep 'SerialNo' | awk -F'=' '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘 '" << testDisk << "' 序列号: 无法获取 (可能需要sudo或磁盘不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘 '" << testDisk << "' 序列号: " << result;
    return RE_SUCCESS;
}

int doGetDiskSmartStatus(int index) {
    std::string testDisk = "/dev/sda"; // Example, would come from args
    std::string result = showExec("sudo smartctl -H " + testDisk + " 2>/dev/null | grep 'SMART overall-health self-assessment test result:' | awk '{print $NF}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "磁盘 '" << testDisk << "' SMART状态: 无法获取 (可能未安装smartmontools或需要sudo)。\n";
        return ERROR_PARA;
    }
    std::cout << "磁盘 '" << testDisk << "' SMART状态: " << result;
    return RE_SUCCESS;
}

int doShowTotalNetworkBytesTransmitted(int index) {
    std::string result = showExec("grep 'Tx bytes' /proc/net/dev | awk '{sum += $9} END {printf \"%.2f GB\\n\", sum/1024/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "总网络传输字节数: " << result;
    return RE_SUCCESS;
}

int doGetTotalNetworkBytesReceived(int index) {
    std::string result = showExec("grep 'Rx bytes' /proc/net/dev | awk '{sum += $2} END {printf \"%.2f GB\\n\", sum/1024/1024/1024}' 2>&1");
    printIndex(index);
    std::cout << "总网络接收字节数: " << result;
    return RE_SUCCESS;
}

int doShowProcessOpenFileDescriptors(int index) {
    std::string testPid = "$(pgrep -o systemd)"; // Example, would come from args
    std::string result = showExec("sudo ls -l /proc/" + testPid + "/fd 2>/dev/null | wc -l 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 打开文件描述符数量: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    long count = 0;
    try {
        count = std::stol(result) - 1; // Subtract 1 for total line if present, or just count
    } catch (...) {}
    std::cout << "进程 " << testPid << " 打开文件描述符数量: " << (count > 0 ? std::to_string(count) : "0") << "\n";
    return RE_SUCCESS;
}

int doGetProcessMemoryResidentSetSize(int index) {
    std::string testPid = "$(pgrep -o systemd)"; // Example, would come from args
    std::string result = showExec("grep VmRSS /proc/" + testPid + "/status 2>/dev/null | awk '{printf \"%.2f MB\\n\", $2/1024}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 驻留集大小 (RSS): 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 驻留集大小 (RSS): " << result;
    return RE_SUCCESS;
}

int doShowProcessEffectiveUser(int index) {
    std::string testPid = "$(pgrep -o systemd)"; // Example, would come from args
    std::string result = showExec("ps -p " + testPid + " -o euser --no-headers 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "进程 " << testPid << " 有效用户: 无法获取或进程不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "进程 " << testPid << " 有效用户: " << result;
    return RE_SUCCESS;
}

int doGetSystemFirewallRules(int index) {
    std::string result = showExec("sudo iptables -L --line-numbers -n 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统防火墙规则 (前10条): 无法获取 (可能未运行iptables或无权限)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统防火墙规则 (前10条): \n" << result;
    return RE_SUCCESS;
}

int doShowSystemCronStatus(int index) {
    std::string result = showExec("systemctl status cron.service 2>/dev/null | grep 'Active:' | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统Cron服务状态: 无法获取或服务不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "系统Cron服务状态: " << result;
    return RE_SUCCESS;
}

int doGetSystemdUnitDependencies(int index) {
    std::string testUnit = "network.target"; // Example, would come from args
    std::string result = showExec("systemctl list-dependencies " + testUnit + " --plain --no-pager | head -n 10 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd单元 '" << testUnit << "' 依赖项: 无法获取或单元不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd单元 '" << testUnit << "' 依赖项 (部分): \n" << result;
    return RE_SUCCESS;
}

int doShowKernelVersionBuildOptions(int index) {
    // This is difficult, typically requires kernel source or debug info.
    // A simplified approach is to show config path.
    std::string result = showExec("grep CONFIG_ /boot/config-$(uname -r) 2>/dev/null | head -n 10");
    printIndex(index);
    if (result.empty()) {
        std::cout << "内核版本构建选项 (部分): 无法获取 (可能没有/boot/config-文件)。\n";
        return ERROR_PARA;
    }
    std::cout << "内核版本构建选项 (部分): \n" << result;
    return RE_SUCCESS;
}

int doGetKernelMaxOpenFiles(int index) {
    std::string result = showExec("sysctl fs.file-max | awk '{print $3}' 2>&1");
    printIndex(index);
    std::cout << "内核最大打开文件数: " << result;
    return RE_SUCCESS;
}

int doShowSystemdJournalLogSizeLimit(int index) {
    std::string result = showExec("journalctl --disk-usage 2>/dev/null | grep 'Persistent journal size' | awk '{print $NF}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "Systemd日志大小限制: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "Systemd日志大小限制: " << result;
    return RE_SUCCESS;
}

int doGetNetworkInterfacePacketErrors(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s link show " + testInterface + " 2>/dev/null | grep 'errors' | awk '{print $2+\" \"+$3+\" \"+$4+\" \"+$5}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 包错误数: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 包错误数 (接收/传输/冲突/CRC): " << result;
    return RE_SUCCESS;
}

int doShowNetworkInterfaceDroppedPackets(int index) {
    std::string testInterface = "eth0"; // Example, would come from args
    std::string result = showExec("ip -s link show " + testInterface + " 2>/dev/null | grep 'dropped' | awk '{print $2+\" \"+$3}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "网卡 '" << testInterface << "' 丢弃包数: 无法获取或网卡不存在。\n";
        return ERROR_PARA;
    }
    std::cout << "网卡 '" << testInterface << "' 丢弃包数 (接收/传输): " << result;
    return RE_SUCCESS;
}

int doGetSystemDefaultRouteInterface(int index) {
    std::string result = showExec("ip route | grep default | awk '{print $5}' 2>&1");
    printIndex(index);
    std::cout << "系统默认路由接口: " << result;
    return RE_SUCCESS;
}

int doShowSystemLoginGraceTime(int index) {
    // This is typically from SSHD config.
    std::string result = showExec("grep '^LoginGraceTime' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "系统登录宽限时间: 无法获取 (可能未设置或SSHD配置不存在)。\n";
        return ERROR_PARA;
    }
    std::cout << "系统登录宽限时间 (sshd): " << result;
    return RE_SUCCESS;
}

int doGetCpuMicrocodeVersion(int index) {
    std::string result = showExec("grep 'microcode' /proc/cpuinfo | head -n 1 | cut -d: -f2 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "CPU微码版本: 无法获取。\n";
        return ERROR_PARA;
    }
    std::cout << "CPU微码版本: " << result;
    return RE_SUCCESS;
}

int doShowMemoryPageFaults(int index) {
    std::string result = showExec("vmstat -s 2>/dev/null | grep 'page faults' | awk '{print $1}'");
    printIndex(index);
    if (result.empty()) {
        std::cout << "内存页错误: 无法获取 (可能未安装vmstat)。\n";
        return ERROR_PARA;
    }
    std::cout << "内存页错误: " << result;
    return RE_SUCCESS;
}

int doGetSystemCpuTopology(int index) {
    std::string result = showExec("lscpu | grep -E 'Socket|Core|Thread' 2>&1");
    printIndex(index);
    std::cout << "系统CPU拓扑: \n" << result;
    return RE_SUCCESS;
}

int doShowSystemBlockDeviceList(int index) {
    std::string result = showExec("lsblk -d -o NAME,SIZE,TYPE,MOUNTPOINT 2>&1");
    printIndex(index);
    std::cout << "系统块设备列表: \n" << result;
    return RE_SUCCESS;
}


int doShowSelinuxPolicyVersion(int index) {
    std::string result = showExec("sestatus 2>/dev/null | grep 'Loaded policy name:' | awk '{print $4}' 2>&1");
    printIndex(index);
    if (result.empty()) {
        std::cout << "SELinux策略版本: 无法获取 (可能未启用SELinux)。\n";
        return ERROR_PARA;
    }
    std::cout << "SELinux策略版本: " << result;
    return RE_SUCCESS;
}
