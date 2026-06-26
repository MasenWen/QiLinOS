
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

#include "instructionset.h"
#include "instructionlist.h"

// 初始化单例实例指针
InstructionSet* InstructionSet::sInstance = nullptr;
std::mutex InstructionSet::sMutex;

using namespace kdk;
namespace fs = std::filesystem;


DBusClient *dbusClient = DBusClient::getInstance();


//查找，等待，生成图片 跳过

InstructionSet::InstructionSet() {
    //    addInstruction("cd", cd);
    //    addInstruction("close", closeAny);

    //    addInstruction("find", find);
    //    addInstruction("new", create);
    //    addInstruction("open", openAny);
    //    addInstruction("pause", pause);
    //    addInstruction("play", play);
    //    addInstruction("restart", restart);
    //    addInstruction("reboot", restart);
    //    addInstruction("save", saveFile);
    //    addInstruction("set", set);
    //    addInstruction("screenshot", screenshot);
    //    addInstruction("shutdown", shutdown);
    //    addInstruction("suspend", suspend);
    //    addInstruction("sleep", hibernate);
    //    addInstruction("wait", wait);
    //    addInstruction("write", writeContent);
    //    addInstruction("defaultExec", defaultExec);
    initializeActions();
    QString homePath = QStandardPaths::writableLocation(QStandardPaths::HomeLocation);
    pwdPath = homePath.toStdString();
    curFile = pwdPath + "/temp.txt";
}



InstructionSet* InstructionSet::getInstance() {
    std::lock_guard<std::mutex> lock(sMutex);
    if (sInstance == nullptr) {
        sInstance = new InstructionSet();
    }
    return sInstance;
}
void InstructionSet::initializeActions() {

    doActions["bye"] = &InstructionSet::bye;

    doActions["down"] = &InstructionSet::turnDown;
    doActions["up"] = &InstructionSet::turnUp;
    doActions["bottom"] = &InstructionSet::turnBottom;
    doActions["top"] = &InstructionSet::turnTop;
    doActions["cd"] = &InstructionSet::cd;
    doActions["close"] = &InstructionSet::closeAny;
    doActions["disc"] = &InstructionSet::disc;
    doActions["find"] = &InstructionSet::find;
    doActions["mailto"] = &InstructionSet::mailto;
    doActions["makepic"] = &InstructionSet::makepic;
    doActions["new"] = &InstructionSet::create;
    doActions["search"] = &InstructionSet::search;
    doActions["none"] = &InstructionSet::none;
    doActions["open"] = &InstructionSet::openAny;
    doActions["show"] = &InstructionSet::showAny;
    doActions["empty"] = &InstructionSet::emptyAny;
    doActions["do"] = &InstructionSet::doAny;
    doActions["pause"] = &InstructionSet::pause;
    doActions["play"] = &InstructionSet::play;
    doActions["rag"] = &InstructionSet::rag;
    doActions["restart"] = &InstructionSet::restart;
    doActions["reboot"] = &InstructionSet::restart;
    doActions["save"] = &InstructionSet::saveFile;
    doActions["screenshot"] = &InstructionSet::screenshot;
    doActions["shutdown"] = &InstructionSet::shutdown;
    doActions["suspend"] = &InstructionSet::suspend;
    doActions["set"] = &InstructionSet::set;
    doActions["sleep"] = &InstructionSet::hibernate;
    doActions["wait"] = &InstructionSet::wait;
    doActions["write"] = &InstructionSet::writeContent;
    doActions["defaultExec"] = &InstructionSet::defaultExec;

    doActions["down"] = &InstructionSet::turnDownSkip;
    doActions["up"] = &InstructionSet::turnUpSkip;
    doActions["bottom"] = &InstructionSet::turnBottomSkip;
    doActions["top"] = &InstructionSet::turnTopSkip;
    skipActions["cd"] = &InstructionSet::cdSkip;
    skipActions["close"] = &InstructionSet::closeAnySkip;
    skipActions["disc"] = &InstructionSet::discSkip;
    skipActions["find"] = &InstructionSet::findSkip;
    skipActions["makepic"] = &InstructionSet::makepicSkip;
    skipActions["mailto"] = &InstructionSet::mailtoSkip;
    skipActions["new"] = &InstructionSet::createSkip;
    skipActions["none"] = &InstructionSet::none;
    skipActions["open"] = &InstructionSet::openAnySkip;
    skipActions["pause"] = &InstructionSet::pauseSkip;
    skipActions["play"] = &InstructionSet::playSkip;
    skipActions["rag"] = &InstructionSet::ragSkip;
    skipActions["restart"] = &InstructionSet::restartSkip;
    skipActions["reboot"] = &InstructionSet::restartSkip;
    skipActions["save"] = &InstructionSet::saveFileSkip;
    skipActions["screenshot"] = &InstructionSet::screenshotSkip;
    skipActions["shutdown"] = &InstructionSet::shutdownSkip;
    skipActions["suspend"] = &InstructionSet::suspendSkip;
    skipActions["set"] = &InstructionSet::setSkip;
    skipActions["sleep"] = &InstructionSet::hibernateSkip;
    skipActions["wait"] = &InstructionSet::waitSkip;
    skipActions["write"] = &InstructionSet::writeContentSkip;
    skipActions["defaultExec"] = &InstructionSet::defaultExecSkip;


    setActions["language"] = &InstructionSet::setLanguage;
    setActions["background"] = &InstructionSet::setBackground;
    setActions["dark"] = &InstructionSet::setDarkMode;
    setActions["mousesize"] = &InstructionSet::setMouseSize;
    setActions["brightness"] = &InstructionSet::setBrightness;
    setActions["powerschemeonac"] = &InstructionSet::setPowerschemeonac;
    setActions["powerschemeonbattery"] = &InstructionSet::setPowerschemeonbattery;
    setActions["calendar"] = &InstructionSet::setCalendar;
    setActions["firstday"] = &InstructionSet::setFirstday;
    setActions["datetype"] = &InstructionSet::setDatetype;
    setActions["timeformat"] = &InstructionSet::setTimeformat;
    setActions["light"] = &InstructionSet::setLightMode;
    setSkipActions["language"] = &InstructionSet::setLanguageSkip;
    setSkipActions["background"] = &InstructionSet::setBackgroundSkip;
    setSkipActions["dark"] = &InstructionSet::setDarkModeSkip;
    setSkipActions["light"] = &InstructionSet::setLightModeSkip;
}

//void InstructionSet::addInstruction(const std::string& name, const InstructionFunction& function) {
//    mInstructions[name] = function;
//}

//bool InstructionSet::hasInstruction(const std::string& name) const {
//    return mInstructions.find(name) != mInstructions.end();
//}
void InstructionSet::initTaskEnv(Actuator *tAct, std::vector<std::string> *tTasks)
{
    act = tAct;
    tasks = tTasks;
}
int InstructionSet::executeInstruction(int index, const std::string& name, const std::vector<std::string>& args)
{
    auto it = doActions.find(name);
    if (it != doActions.end()) {
        // 使用std::bind来绑定this指针
        std::function<void(const std::vector<std::string>&, int)> func =
                std::bind(it->second, this, std::placeholders::_1, std::placeholders::_2);
        func(args, index);


    } else {
        defaultExec(args, index);
    }

    return 0;
}

int InstructionSet::executeSkipInstruction(int index, const std::string& name, const std::vector<std::string>& args)
{
    auto it = skipActions.find(name);
    if (it != skipActions.end()) {
        // 使用std::bind来绑定this指针
        std::function<void(const std::vector<std::string>&, int)> func =
                std::bind(it->second, this, std::placeholders::_1, std::placeholders::_2);
        func(args, index);

    } else {
        defaultExecSkip(args, index);
    }

    return 0;
}

void InstructionSet::deleteInstance() {
    delete sInstance;
    sInstance = nullptr;
}

int InstructionSet::defaultExecSkip(const std::vector<std::string>& args, int index)
{


    return 1;
}

int InstructionSet::defaultExec(const std::vector<std::string>& args, int index)
{

    std::ostringstream oss;

    if (!args.empty()) {
        // 将 vector 中的所有元素拼接成一个字符串，以空格为分隔符
        std::copy(args.begin(), args.end() - 1, std::ostream_iterator<std::string>(oss, " "));
        // 添加最后一个元素，避免在句子末尾添加多余的空格
        oss << args.back();
    }

    std::string input = "cd " + pwdPath + "; " + oss.str();

    std::string outStr = sysExec(input.c_str());
    output(outStr);
    if(outStr.empty())
    {
        std::cout << "<AI>" << oss.str() << std::endl;
    }
    else
    {
        std::cout << "<AI>" << outStr << std::endl;
    }
    return 1;
}

int InstructionSet::bye(const std::vector<std::string>& args, int index)
{
//    sleep(15);
//    system("kill -9 $(pidof chat_client)");
    return 0;
}
int InstructionSet::cdSkip(const std::vector<std::string>& args, int index)
{
    return 1;
}
int InstructionSet::cd(const std::vector<std::string>& args, int index)
{
    std::cout << "exec: cd" << std::endl;
    if(args.size() == 2)
    {
        std::string input = "/usr/bin/peony " + args[1];
        pwdPath = args[1];
        system(input.c_str());
    }
    return 1;
}



int InstructionSet::disc(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    if(index == -1)
    {
        if(args.size()>0)
        {
            std::cout << "正在刻录文件\"" << args[1] << "\"，可能需要几分钟，请您耐心等待" << std::endl;
        }
        else
        {
            std::cout << "刻录文件失败" << std::endl;
        }
    }
    else
    {
        std::cout << "刻录文件" << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    act->performSkipTasks(tasks, index+1);

    std::string tempPath = QStandardPaths::writableLocation(QStandardPaths::HomeLocation).toStdString() + "/.kylin-actuator/temp";
    std::string input = "xorriso -dev /dev/sr0 -map " + tempPath + " / -volid 刻录 -joliet on -close off -commit -eject";
    system(input.c_str());
    std::filesystem::path dirPath(tempPath);
    try {
        // 尝试删除目录及其内容
        std::error_code ec;
        std::filesystem::remove_all(dirPath, ec);
    } catch (const std::filesystem::filesystem_error& ex) {
        // 处理异常
        std::cerr << "Error occurred: " << ex.what() << std::endl;
    }
    return 1;
}

int InstructionSet::discSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    std::cout << "刻录文件" << "  [待执行]" <<std::endl;
    checkIfEnd(tasks->size(), index);
    return 1;
}
std::unordered_map<std::string, openSingleFunc> closeFuncs = {
    {"network", closeNetWork},
    {"bluetooth", closeBluetooth},
    {"bluetoothicon", closeBluetoothicon},
    {"repeatkeys", closeRepeatkeys},
    {"repeatnotification", closeRepeatnotification},
    {"mouseltohand", closeMouseltohand},
    {"mouseacceleration", closeMouseacceleration},
    {"ctrlshowpointer", closeCtrlshowpointer},
    {"textcursorblink", closeTextcursorblink},
    {"autologin", closeAutologin},
    {"passwordlesslogin", closePasswordlesslogin},
    {"passwordonsleep", closePasswordonsleep},
    {"volume", closeVolume},
    {"touchpad", closeTouchpad},
    {"brightness", closeBrightness},
};

int InstructionSet::closeAnySkip(const std::vector<std::string>& args, int index)
{
    return 1;
}
int InstructionSet::closeAny(const std::vector<std::string>& args, int index)
{
    if(args.size() < 2)
        return ERROR_PARA;
    int status = RE_SUCCESS;

    auto it = closeFuncs.find(args[1]);
    if (it != closeFuncs.end()) {
        // 调用找到的函数
        it->second(0);
    }
    else
    {
        std::cout << "close application" << std::endl;

        status = openOrCloseApplication(args[1], true, false);
        if(status==0)
        {
            printIndex(index);
            if(index == -1)
            {
                std::cout << "已经关闭" << appZhName << std::endl;
            }
            else
            {
                std::cout << "关闭" << appZhName << "  [已完成]" << std::endl;
            }
        }
        else
        {
            std::cout << "<AI>关闭失败，无法找到需要关闭的目标，或许是我不太理解需要关闭的目标";
        }
    }
    checkIfEnd(tasks->size(), index);
    if(status == ERROR_PARA)
    {

    }

    return status;
}

int InstructionSet::createSkip(const std::vector<std::string> &args, int index)
{
    return 1;
}

int InstructionSet::create(const std::vector<std::string>& args, int index)
{

    if(args.size() == 2)
    {
        curFile = pwdPath + "/" + args[1];
        std::cout << "exec: create " << curFile << std::endl;
    }
    return 0;
}

int InstructionSet::search(const std::vector<std::string>& args, int index)
{
    std::string para = args[1];
    std::string directive = "xdotool key super+s sleep 0.2 type " + para;
    system(directive.c_str());
    std::cout << "<AI>" <<"已打开全局搜索，搜索内容为：" << para <<std::endl;
    return 0;
}


std::unordered_map<std::string, std::string> findMap = {
    {"-ctime", "创建过的"},
    {"-mtime", "修改过的"}
};




int InstructionSet::find(const std::vector<std::string>& args, int index)
{
    int last = args.size()-1;
    std::string day = args[last];
    std::cout << day << std::endl;
    if (!day.empty() && day.front() == '-') {
        day.erase(0, 1);
    }
    std::string cm = args[last-1];
    std::string judge = "";
    for(int i = 0; i < last; i++){
        judge += args[i];
    }
    std::cout << judge << std::endl;
    if(judge.find("*.doc") != -1)
    {
        judge = "Word文档";
    }else if(judge.find("*.xls") != -1){
        judge = "Execl表格";
    }else if(judge.find("*.ppt") != -1){
        judge = "ppt文件";
    }else if(judge.find("*.pdf") != -1){
        judge = "pdf文件";
    }else if(judge.find("*.png") != -1 || judge.find("*.jpg") != -1 || judge.find("*.jpeg") != -1){
        judge = "图片";
    }else if(judge.find("*.txt") != -1){
        judge = "txt文件";
    }
    else
    {
        judge = "文件";
    }

    std::string homePath = QStandardPaths::writableLocation(QStandardPaths::HomeLocation).toStdString();
    if(pwdPath == homePath)
    {
        homePath = "主";
    }
    else
    {
        homePath = pwdPath;
    }
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在" << homePath << "目录查找最近" << day << "天" << findMap[cm] << judge << ", 可能需要一些时间，请耐心等待..."<< std::endl;
    }
    else
    {
        std::cout << "在" << homePath << "目录查找最近" << day << "天" << findMap[cm] << judge << "[正在执行中...]" <<std::endl;
    }
    checkIfEnd(tasks->size(), index);
    act->performSkipTasks(tasks, index+1);

    std::ostringstream oss;

    if (!args.empty()) {
        // 将 vector 中的所有元素拼接成一个字符串，以空格为分隔符
        std::copy(args.begin(), args.end() - 1, std::ostream_iterator<std::string>(oss, " "));
        // 添加最后一个元素，避免在句子末尾添加多余的空格
        oss << args.back();
    }

    //    std::string input = "cd " + pwdPath + "; " + oss.str();
    std::string replace = " " + pwdPath + " ";
    std::string input = replaceStr(oss.str(), " . ", replace, false);
    std::cout << input << std::endl;
    std::string outStr = sysExec(input.c_str());
    output(outStr);
    LinkDialog *dialog = LinkDialog::getInstance();
    std::vector<std::string> result;
    std::istringstream iss(outStr);
    std::string line;

    while (std::getline(iss, line)) {
        dialog->addLink(QString::fromStdString(line));
    }
    dialog->move((1920 -560)/ 2,100);
    dialog->show();

    std::cout << outStr << std::endl;
    return 1;
}
int InstructionSet::findSkip(const std::vector<std::string>& args, int index)
{
    int last = args.size()-1;
    std::string day = args[last];
    if (!day.empty() && day.front() == '-') {
        day.erase(0, 1);
    }
    std::string cm = args[last-1];
    std::string judge = "";
    for(int i = 0; i < last; i++){
        judge += args[i];
    }
    std::cout << judge << std::endl;
    if(judge.find("*.doc") != -1 && judge.find("*.pdf") != -1){
        judge = "文件";
    }
    else if(judge.find("*.doc") != -1)
    {
        judge = "Word文档";
    }else if(judge.find("*.xls") != -1){
        judge = "Execl表格";
    }else if(judge.find("*.ppt") != -1){
        judge = "ppt文件";
    }else if(judge.find("*.pdf") != -1){
        judge = "pdf文件";
    }else if(judge.find("*.png") != -1 || judge.find("*.jpg") != -1 || judge.find("*.jpeg") != -1){
        judge = "图片";
    }
    else
    {
        judge = "文件";
    }

    std::string homePath = QStandardPaths::writableLocation(QStandardPaths::HomeLocation).toStdString();
    if(pwdPath == homePath)
    {
        homePath = "Home";
    }
    else
    {
        homePath = pwdPath;
    }
    printIndex(index);
    std::cout << "在" << homePath << "目录查找最近" << day << "天" << findMap[cm] << judge << "  [待执行]" <<std::endl;
    checkIfEnd(tasks->size(), index);
    return 1;
}
int InstructionSet::hibernateSkip(const std::vector<std::string>& args, int index)
{
    return 1;
}
int InstructionSet::hibernate(const std::vector<std::string>& args, int index)
{
    system("ukui-session-tools --hibernate");
    return 0;
}
int InstructionSet::mailto(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经根据内容创建邮件，请确认后再发送" <<std::endl;
    }
    else
    {
        std::cout << "创建邮件给" << args[1] << "，请确认后再发送  [已完成]" <<std::endl;
    }
    return 0;
}

int InstructionSet::mailtoSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    std::cout << "创建邮件给" << args[1] << "  [待执行]" <<std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}

int InstructionSet::makepic(const std::vector<std::string>& args, int index)
{
    if(args.size()<2)
    {
        return 1;
    }
    printIndex(index);
    std::cout << "文生图" << "  [图片正在生成中...]" <<std::endl;
    checkIfEnd(tasks->size(), index);
    act->performSkipTasks(tasks, index+1);

    std::string input = "/home/ok/anaconda3/envs/gptq/bin/python /media/ok/extpub/mygit/llm-agent/make_pic.py \"" + args[1] + "\"";
    system(input.c_str());

    return 0;
}
int InstructionSet::makepicSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    std::cout << "根据文本生成图片" << "  [待执行]" <<std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::muteSkip(const std::vector<std::string>& args, int index)
{
    return 0;
}
int InstructionSet::mute(const std::vector<std::string>& args, int index)
{
    dbusClient->mediaKeyDoAction(MUTE_KEY);
    return 0;
}

int InstructionSet::none(const std::vector<std::string>& args, int index)
{
    dbusClient->mediaKeyDoAction(MUTE_KEY);
    return 0;
}



std::unordered_map<std::string, std::string> openMap = {
    {"network", "英语"},
    {"zh-CN", "简体中文"},
    {"mn", "蒙古语"}
};

std::unordered_map<std::string, openSingleFunc> openFuncs = {
    {"network", openNetWork},
    {"bluetooth", openBluetooth},
    {"bluetoothicon", openBluetoothicon},
    {"repeatkeys", openRepeatkeys},
    {"printer", openPrinter},
    {"inputer", openInputer},
    {"repeatnotification", openRepeatnotification},
    {"mouseltohand", openMouseltohand},
    {"mouseacceleration", openMouseacceleration},
    {"ctrlshowpointer", openCtrlshowpointer},
    {"textcursorblink", openTextcursorblink},
    {"autologin", openAutologin},
    {"passwordlesslogin", openPasswordlesslogin},
    {"passwordonsleep", openPasswordonsleep},
    {"networktime",openNetworktime},
    {"volume", openVolume},
    {"maxvolume", openMaxVolume},
    {"minvolume", openMinVolume},
    {"calculator", openCalculator},
    {"touchpad", openTouchpad},
    {"screensaver", openScreensaver},
    {"filemanager", openFilemanager},
    {"terminal", openTerminal},
    {"systemmonitor", openSystemmonitor},
    {"globalsearch", openGlobalsearch},
    {"ukuisidebar", openUkuisidebar},
    {"connectioneditor", openConnectioneditor},
    {"settings", openSettings},
    {"shutdownmanagement", openShutdownmanagement},
    {"projection", openProjection},
    {"userinfosetting", openUserinfosetting},
    {"biometrricssetting", openBiometrricssetting},
    {"displaysetting", openDisplaysetting},
    {"audiosetting", openAudiosetting},
    {"powersetting", openPowersetting},
    {"noticesetting", openNoticesetting},
    {"aboutsetting", openAboutsetting},
    {"bluetoothsetting", openBluetoothsetting},
    {"printersetting", openPrintersetting},
    {"mousesetting", openMousesetting},
    {"touchpadsetting", openTouchpadsetting},
    {"keyboardsetting", openKeyboardsetting},
    {"shortcutsetting", openShortcutsetting},
    {"netconnectsetting", openNetconnectsetting},
    {"wlanconnectsetting", openWlanconnectsetting},
    {"proxysetting", openProxysetting},
    {"vpnsetting", openVpnsetting},
    {"mobilehotspotsetting", openMobilehotspotsetting},
    {"wallpapersetting", openWallpapersetting},
    {"themesetting", openThemesetting},
    {"screenlocksetting", openScreenlocksetting},
    {"screensaversetting", openScreensaversetting},
    {"fontssetting", openFontssetting},
    {"panelsetting", openPanelsetting},
    {"datesetting", openDatesetting},
    {"areasetting", openAreasetting},
    {"upgradesetting", openUpgradesetting},
    {"backupsetting", openBackupsetting},
    {"defaultappsetting", openDefaultappsetting},
    {"autostartsetting", openAutostartsetting},
    {"searchsetting", openSearchsetting},
    {"brightness", openBrightness},
    {"maxbrightness",openMaxBrightness},
    {"minbrightness",openMinBrightness},
    {"volumeup", openVolumeup},
    {"volumedown", openVolumedown},
    {"windowscreenshot", openWindowscreenshot},
    {"areascreenshot", openAreascreenshot},
    {"windowswitch", openWindowswitch},
    {"baidusearch", openBaidusearch},
    {"bingsearch", openBingsearch},
    {"googlesearch", openGooglesearch},
    {"rootdir", openRootdir},
    {"tempdir", openTempdir},
    {"homedir", openHomedir},
    {"desktopdir", openDesktopdir},
    {"documentdir", openDocumentdir},
    {"imagedir", openImagedir},
    {"downloaddir", openDownloaddir},
    {"musicdir", openMusicdir},
    {"videodir", openVideodir},
    {"publicdir", openPublicdir},
    {"templatedir", openTemplatedir},
    {"kylinv4_inputer", openKylinv4inputer},
    {"kylinv4_touchpad", openKylinv4touchpad},
    {"kylinv4_screensaver", openKylinv4screensaver},
    {"kylinv4_filemanager", openKylinv4filemanager},
    {"kylinv4_printer", openKylinv4printer},
    {"kylinv4_screenshot", openKylinv4screenshot},
    {"kylinv4_terminal", openKylinv4terminal},
    {"kylinv4_systemmonitor", openKylinv4systemmonitor},
    {"kylinv4_connectioneditor", openKylinv4connectioneditor},
    {"kylinv4_printersetting", openKylinv4printersetting},
    {"kylinv4_brightness", openKylinv4brightness},
    {"kylinv4_settings", openKylinv4settings},
    {"kylinv4_wallpapersetting", openKylinv4wallpapersetting},
    {"kylinv4_themesetting", openKylinv4themesetting},
    {"kylinv4_fontssetting", openKylinv4fontssetting},
    {"kylinv4_screensaversetting", openKylinv4screensaversetting},
    {"kylinv4_datesetting", openKylinv4datesetting},
    {"kylinv4_userinfosetting", openKylinv4userinfosetting},
    {"kylinv4_keyboardsetting", openKylinv4keyboardsetting},
    {"kylinv4_audiosetting", openKylinv4audiosetting},
    {"kylinv4_netconnectsetting", openKylinv4netconnectsetting},
    {"kylinv4_displaysetting", openKylinv4displaysetting},
    {"kylinv4_powersetting", openKylinv4powersetting},
};

std::unordered_map<std::string, openSingleFunc> showFuncs = {
    {"versioninfo", showVersioninfo},
    {"cpuinfo", showCpuinfo},
    {"diskinfo", showDiskinfo},
    {"memoryinfo", showMemoryinfo},
    {"kernelinfo", showKernelinfo},
    {"ifconfiginfo", showIfconfiginfo},
    {"usernameinfo", showUsernameinfo},
    {"datetime", showDatetime},
    {"sensorsversion", showSensorversion},
    {"lsusbversion", showLsusbversion},
    {"bcversion", showBcversion},
    {"bashversion", showBashversion},
    {"lddversion", showLddversion},
    {"infocmpversion", showInfocmpversion},
    {"opensslversion", showOpensslversion},
    {"ldversion", showLdversion},
    {"findsversion", showFindversion},
    {"gzipversion", showGzipversion},
    {"tarversion", showTarversion},
    {"xzversion", showXzversion},
    {"sedversion", showSedversion},
    {"awkversion", showAwkversion},
    {"grepversion", showGrepversion},
    {"iptablesversion", showIptablesversion},
    {"systemdversion", showSystemdversion},
    {"psversion", showPsversion},
    {"ifconfigversion", showIfconfigversion},
    {"ipversion", showIpversion},
    {"tune2fsversion", showTune2fsversion},
    {"mountversion", showMountversion},
    {"dmidecodeversion", showDmidecodeversion},
    {"vimversion", showVimversion},
    {"manversion", showManversion},
    {"pingversion", showPingversion},
    {"ethtoolversion", showEthtoolversion},
    {"wgetversion", showWgetversion},
    {"curlversion", showCurlversion},
    {"gettextversion", showGettextversion},
    {"hostnamectlversion", showHostnamectlversion},
    {"uptimeversion", showUptimeversion},
    {"whoversion", showWhoversion},
    {"wversion", showWversion},
    {"topversion", showTopversion},
    {"dmesgversion", showDmesgversion},
    {"vmstatversion", showVmstatversion},
    {"freeversion", showFreeversion},
    {"lsversion", showLsversion},
    {"cpversion", showCpversion},
    {"mvversion", showMvversion},
    {"rmversion", showRmversion},
    {"chmodversion", showChmodversion},
    {"chownversion", showChownversion},
    {"lnversion", showLnversion},
    {"dfversion", showDfversion},
    {"duversion", showDuversion},
    {"statversion", showStatversion},
    {"teeversion", showTeeversion},
    {"headversion", showHeadversion},
    {"tailversion", showTailversion},
    {"sortversion", showSortversion},
    {"uniqversion", showUniqversion},
    {"cutversion", showCutversion},
    {"pasteversion", showPasteversion},
    {"splitversion", showSplitversion},
    {"wcversion", showWcversion},
    {"truncateversion", showTruncateversion},
    {"shufversion", showShufversion},
    {"yesversion", showYesversion},
    {"dateversion", showDateversion},
    {"exprversion", showExprversion},
    {"factorversion", showFactorversion},
    {"seqversion", showSeqversion},
    {"nlversion", showNlversion},
    {"basenameversion", showBasenameversion},
    {"dirnameversion", showDirnameversion},
    {"idversion", showIdversion},
    {"whoamiversion", showWhoamiversion},
    {"groupsversion", showGroupsversion},
    {"usersversion", showUsersversion},
    {"unameversion", showUnameversion},
    {"archversion", showArchversion},
    {"timeoutversion", showTimeoutversion},
    {"linkversion", showLinkversion},
    {"readlinkversion", showReadlinkversion},
    {"realpathversion", showRealpathversion},
    {"fileversion", showFileversion},
    {"foldversion", showFoldversion},
    {"prversion", showPrversion},
    {"watchversion", showWatchversion},
    {"logrotateversion", showLogrotateversion},
    {"sysctlversion", showSysctlversion},
    {"localeversion", showLocaleversion},
    {"ttyversion", showTtyversion},
    {"ssversion", showSsversion},
    {"arpversion", showArpversion},
    {"routeversion", showRouteversion},
    {"nmcliversion", showNmcliversion},
    {"ping6version", showPing6version},
    {"ip6tablesversion", showIp6tablesversion},
    {"iptables-saveversion", showIptablesSaveversion},
    {"iptables-restoreversion", showIptablesRestoreversion},
    {"mkfsversion", showMkfsversion},
    {"fsckversion", showFsckversion},
    {"blkidversion", showBlkidversion},
    {"partedversion", showPartedversion},
    {"lsblkversion", showLsblkversion},
    {"mktempversion", showMktempversion},
    {"chrootversion", showChrootversion},
    {"niceversion", showNiceversion},
    {"reniceversion", showReniceversion},
    {"pkillversion", showPkillversion},
    {"pgrepversion", showPgrepversion},
    {"xargsversion", showXargsversion},
    {"stringsversion", showStringsversion},
    {"hexdumpversion", showHexdumpversion},
    {"objdumpversion", showObjdumpversion},
    {"readelfversion", showReadelfversion},
    {"nmversion", showNmversion},
    {"ldconfigversion", showLdconfigversion},
    {"arversion", showArversion},
    {"ranlibversion", showRanlibversion},
    {"stripversion", showStripversion},
    {"sizeversion", showSizeversion},
    {"asversion", showAsversion},
    {"iconvversion", showIconvversion},
    {"msgfmtversion", showMsgfmtversion},
    {"msgmergeversion", showMsgmergeversion},
    {"msgenversion", showMsgenversion},
    {"msgcmpversion", showMsgcmpversion},
    {"msgconvversion", showMsgconvversion},
    {"msgcatversion", showMsgcatversion},
    {"xgettextversion", showXgettextversion},
    {"commversion", showCommversion},
    {"diffversion", showDiffversion},
    {"cmpversion", showCmpversion},
    {"patchversion", showPatchversion},
    {"dirversion", showDirversion},
    {"vdirversion", showVdirversion},
    {"touchversion", showTouchversion},
    {"envversion", showEnvversion},
    {"printenvversion", showPrintenvversion},
    {"sleepversion", showSleepversion},
    {"tsortversion", showTsortversion},
    {"unlinkversion", showUnlinkversion},
    {"mysqlport", showMysqlport},
    {"httpport", showHttpport},
    {"httpsport", showHttpsport},
    {"sshport", showSshport},
    {"ftpport", showFtpport},
    {"smtpport", showSmtpport},
    {"dnsport", showDnsport},
    {"dhcpport", showDhcpport},
    {"pop3port", showPop3port},
    {"imapport", showImapport},
    {"telnetport", showTelnetport},
    {"ldapport", showLdapport},
    {"smbport", showSmbport},
    {"rdpport", showRdpport},
    {"pgport", showPgport},
    {"redisport", showRedisport},
    {"mongodbport", showMongodbport},
    {"memcachedport", showMemcachedport},
    {"kafkaport", showKafkaport},
    {"elasticport", showElasticport},
    {"ntpport", showNtpport},
    {"snmpport", showSnmpport},
    {"smtpsport", showSmtpsport},
    {"imapsport", showImapsport},
    {"pop3sport", showPop3sport},
    {"ldapsport", showLdapsport},
    {"syslogport", showSyslogport},
    {"bgpport", showBgpport},
    {"ircport", showIrcport},
    {"mssqlport", showMssqlport},
    {"radiusport", showRadiusport},
    {"vncport", showVncport},
    {"zkport", showZkport},
    {"openvpnport", showOpenvpnport},
    {"proxyport", showProxyport},
    {"squidport", showSquidport},
    {"tomcatport", showTomcatport},
    {"weblogicport", showWeblogicport},
    {"rabbitmqport", showRabbitmqport},
    {"dockerregistryport", showDockerregistryport},
    {"gitport", showGitport},
    {"btport", showBtport},
    {"rsyncport", showRsyncport},
    {"bitbucketport", showBitbucketport},
    {"sonarport", showSonarport},
    {"jenkinsport", showJenkinsport},
    {"grafanaport", showGrafanaport},
    {"prometheusport", showPrometheusport},
    {"consulport", showConsulport},
    {"vaultport", showVaultport},
    {"kubeapiport", showKubeapiport},
    {"kubeletport", showKubeletport},
    {"kubeschedulerport", showKubeschedulerport},
    {"kubecontrollerport", showKubecontrollerport},
    {"etcdport", showEtcdport},
    {"nomadport", showNomadport},
    {"traefikport", showTraefikport},
    {"nginxport", showNginxport},
    {"apacheport", showApacheport},
    {"haproxyport", showHaproxyport},
    {"cephmonport", showCephmonport},
    {"cephosdport", showCephosdport},
    {"cephmdsport", showCephmdsport},
    {"cassandraport", showCassandraport},
    {"cockroachport", showCockroachport},
    {"elasticapmport", showElasticapmport},
    {"clickhouseport", showClickhouseport},
    {"natsport", showNatsport},
    {"etcdclientport", showEtcdclientport},
    {"etcdpeerport", showEtcdpeerport},
    {"keycloakport", showKeycloakport},
    {"harborport", showHarborport},
    {"mattermostport", showMattermostport},
    {"metabaseport", showMetabaseport},
    {"nexusport", showNexusport},
    {"giteaport", showGiteaport},
    {"sentryport", showSentryport},
    {"vectorport", showVectorport},
    {"lokiport", showLokiport},
    {"minioport", showMinioport},
    {"vaultagentport", showVaultagentport},
    {"opensearchport", showOpensearchport},
    {"couchdbport", showCouchdbport},
    {"hadoopnamenodeport", showHadoopnamenodeport},
    {"hadoopdatanodeport", showHadoopdatanodeport},
    {"hbmasterport", showHbmasterport},
    {"hbregionport", showHbregionport},
    {"fluentdport", showFluentdport},
    {"mqttport", showMqttport},
    {"graylogport", showGraylogport},
    {"keydbport", showKeydbport},
    {"neo4jport", showNeo4jport},
    {"arangodbport", showArangodbport},
    {"vaultapiport", showVaultapiport},
    {"thanosqueryport", showThanosqueryport},
    {"thanosstoreport", showThanosstoreport},
    {"thanossidecarport", showThanossidecarport},
    {"gitversion", showGitversion},
        {"dockerversion", showDockerversion},
        {"kubectlversion", showKubectlversion},
        {"helmversion", showHelmversion},
        {"goversion", showGoversion},
        {"pythonversion", showPythonversion},
        {"nodeversion", showNodeversion},
        {"npmversion", showNpmversion},
        {"javajdkversion", showJavajdkversion},
        {"mavenversion", showMavenversion},
        {"gradleversion", showGradleversion},
        {"phpversion", showPhpversion},
        {"rubyversion", showRubyversion},
        {"perlversion", showPerlversion},
        {"rustcversion", showRustcversion},
        {"gccversion", showGccversion},
        {"gplusplusversion", showGplusplusversion},
        {"makeversion", showMakeversion},
        {"cmakeversion", showCMakeversion},
        {"autoconfversion", showAutoconfversion},
        {"automakeversion", showAutomakeversion},
        {"libtoolversion", showLibtoolversion},
        {"pkgconfigversion", showPkgconfigversion},
        {"dnfversion", showDnfversion},
        {"yumversion", showYumversion},
        {"aptversion", showAptversion},
        {"zypperversion", showZypperversion},
        {"pacmanversion", showPacmanversion},
        {"rpmversion", showRpmversion},
        {"dpkmversion", showDpkmversion},
        {"sudoversion", showSudoversion},
        {"suversion", showSuversion},
        {"sshversion", showSshversion},
        {"scpversion", showScpversion},
        {"sftpversion", showSftpversion},
        {"rsyncversion", showRsyncversion},
        {"wcversion", showWcversion},
        {"pwdversion", showPwdversion},
        {"chmodversion", showChmodversion},
        {"chownversion", showChownversion},
        {"mkdirversion", showMkdirversion},
        {"rmdirversion", showRmdirversion},
        {"cmpversion", showCmpversion},
        {"commversion", showCommversion},
        {"diffversion", showDiffversion},
        {"patchversion", showPatchversion},
        {"cpioversion", showCpioversion},
        {"ddversion", showDdversion},
        {"odversion", showOdversion},
        {"revversion", showRevversion},
    {"cephversion", showCephversion},
        {"glusterversion", showGlusterversion},
        {"nfsversion", showNfsversion},
        {"sambaversion", showSambaversion},
        {"lustreversion", showLustreversion},
        {"hadoopversion", showHadoopversion},
        {"sparkversion", showSparkversion},
        {"hbaseversion", showHbaseversion},
        {"hiveversion", showHiveversion},
        {"flinkversion", showFlinkversion},
        {"kafkaversion", showKafkaversion},
        {"zookeepercliversion", showZookeepercliversion},
        {"etcdctlversion", showEtcdctlversion},
        {"consulclientversion", showConsulclientversion},
        {"vaultcliversion", showVaultcliversion},
        {"rabbitmqctlversion", showRabbitmqctlversion},
        {"nginxversion", showNginxversion},
        {"apacheversion", showApacheversion},
        {"lighttpdversion", showLighttpdversion},
        {"tomcatcatalinaversion", showTomcatcatalinaversion},
        {"jbosscliversion", showJbosscliversion},
        {"wildflycliversin", showWildflycliversin},
        {"squidversion", showSquidversion},
        {"haproxyversion", showHaproxyversion},
        {"keepalivedversion", showKeepalivedversion},
        {"vsftpdversion", showVsftpdversion},
        {"proftpdversion", showProftpdversion},
        {"pureftpdversion", showPureftpdversion},
        {"sshdversion", showSshdversion},
        {"nginxrtmpversion", showNginxrtmpversion},
        {"dockerregistryversion", showDockerregistryversion},
        {"prometheusclientversion", showPrometheusclientversion},
        {"grafanatoolversion", showGrafanatoolversion},
        {"alertmanagercliversion", showAlertmanagercliversion},
        {"ldapaddversion", showLdapaddversion},
        {"ldapsearchversion", showLdapsearchversion},
        {"ldapmodifyversion", showLdapmodifyversion},
        {"ldapdeleteversion", showLdapdeleteversion},
        {"mysqlclientversion", showMysqlclientversion},
        {"pgclientversion", showPgclientversion},
        {"mongoclientversion", showMongoclientversion},
        {"rediscliversion", showRediscliversion},
        {"elasticsearchversion", showElasticsearchversion},
        {"kibanacliversion", showKibanacliversion},
        {"logstashcliversion", showLogstashcliversion},
        {"rabbitmqpluginsversion", showRabbitmqpluginsversion},
        {"kafkatoolversion", showKafkaToolversion},
        {"zookeeperserverversion", showZookeeperServerversion},
        {"nginxplusversion", showNginxPlusversion},
    {"hostversion", showHostversion},
        {"nslookupversion", showNslookupversion},
        {"digversion", showDigversion},
        {"netstatversion", showNetstatversion},
        {"tcpdumpversion", showTcpdumpversion},
        {"iperf3version", showIperf3version},
        {"lsofversion", showLsofversion},
        {"fdiskversion", showFdiskversion},
        {"gpartedversion", showGpartedversion},
        {"mdadmversion", showMdadmversion},
        {"lvmversion", showLvmversion},
        {"vgdisplayversion", showVgdisplayversion},
        {"lvdisplayversion", showLvdisplayversion},
        {"pvdisplayversion", showPvdisplayversion},
        {"blkidversion", showBlkidversion},
        {"tune2fsversion", showTune2fsversion},
        {"xfsinfoversion", showXfsinfoversion},
        {"btrfsversion", showBtrfsversion},
        {"zfsversion", showZfsversion},
        {"umountversion", showUmountversion},
        {"swaponversion", showSwaponversion},
        {"swapoffversion", showSwapoffversion},
        {"mkswapversion", showMkswapversion},
        {"useraddversion", showUseraddversion},
        {"userdelversion", showUserdelversion},
        {"usermodversion", showUsermodversion},
        {"groupaddversion", showGroupaddversion},
        {"groupdelversion", showGroupdelversion},
        {"groupmodversion", showGroupmodversion},
        {"passwdversion", showPasswdversion},
        {"chageversion", showChageversion},
        {"pwckversion", showPwckversion},
        {"grpckversion", showGrpckversion},
        {"crontabversion", showCrontabversion},
        {"atversion", showAtversion},
        {"systemctlversion", showSystemctlversion},
        {"journalctlversion", showJournalctlversion},
        {"rsyslogdversion", showRsyslogdversion},
        {"logrotateversion", showLogrotateversion},
        {"aureportversion", showAureportversion},
        {"setenforceversion", showSetenforceversion},
        {"getenforceversion", showGetenforceversion},
        {"sestatusversion", showSestatusversion},
        {"firewalldversion", showFirewalldversion},
        {"ufwversion", showUfwversion},
        {"apparmorversion", showApparmorversion},
        {"vagrantversion", showVagrantversion},
        {"virtualboxversion", showVirtualboxversion},
        {"vmwareversion", showVmwareversion},
    {"qemuversion", showQemuversion},
        {"kvmversion", showKvmversion},
        {"libvirtversion", showLibvirtversion},
        {"virtinstversion", showVirtinstversion},
        {"virtmanagerversion", showVirtmanagerversion},
        {"iptablesrestoreversion", showIptablesrestoreversion},
        {"iptablessaveversion", showIptablessaveversion},
        {"ip6tablesrestoreversion", showIp6tablesrestoreversion},
        {"ip6tablessaveversion", showIp6tablessaveversion},
        {"tracerouteversion", showTracerouteversion},
        {"mtrversion", showMtrversion},
        {"ssltlsversion", showSsltlsversion},
        {"nmapversion", showNmapversion},
        {"netcatversion", showNetcatversion},
        {"socatversion", showSocatversion},
        {"openvpnversion", showOpenvpnversion},
        {"wireguardversion", showWireguardversion},
        {"gns3version", showGns3version},
        {"wiresharkversion", showWiresharkversion},
        {"tsharkversion", showTsharkversion},
        {"systemdresolveversion", showSystemdresolveversion},
        {"systemdnetworkdversion", showSystemdnetworkdversion},
        {"systemdtimesyncdversion", showSystemdtimesyncdversion},
        {"chronyversion", showChronyversion},
        {"ntpdateversion", showNtpdateversion},
        {"ntpqversion", showNtpqversion},
        {"ntpversion", showNtpversion},
        {"dockercomposeversion", showDockercomposeversion},
        {"dockerstackversion", showDockerstackversion},
        {"dockerdaemonversion", showDockerdaemonversion},
        {"kubeverseversion", showKubeverseversion},
        {"openshiftversion", showOpenshiftversion},
        {"terraformversion", showTerraformversion},
        {"ansibleversion", showAnsibleversion},
        {"puppetversion", showPuppetversion},
        {"chefversion", showChefversion},
        {"saltversion", showSaltversion},
        {"packerversion", showPackerversion},
        {"vagrantpluginsversion", showVagrantpluginsversion},
        {"cloudinitversion", showCloudinitversion},
        {"ec2cliversion", showEc2cliversion},
        {"azcliversion", showAzcliversion},
        {"gcloudversion", showGcloudversion},
        {"alishversion", showAlishversion},
        {"tencentshellversion", showTencentshellversion},
        {"huaweiocversion", showHuaweiocversion},
        {"ociversion", showOciversion},
        {"openstackclientversion", showOpenstackclientversion},
};

std::unordered_map<std::string, openSingleFunc> doFuncs = {
    {"emptytrash", doEmptytrash},
    {"checkdiskspace", doCheckDiskSpace},
      {"showcurrentworkingdirectory", doShowCurrentWorkingDirectory},
      {"listnetworkinterfaces", doListNetworkInterfaces},
      {"checkinternetconnectivity", doCheckInternetConnectivity},
      {"listsystemuptime", doListSystemUptime},
    {"gethostname", doGetHostname},
        {"getosreleasename", doGetOsReleaseName},
        {"listuserhomedirectorycontent", doListUserHomeDirectoryContent},
        {"getloginshell", doGetLoginShell},
        {"getdefaultgatewayip", doGetDefaultGatewayIp},
        {"checkdnsserverreachability", doCheckDNSServerReachability},
        {"listalllisteningports", doListAllListeningPorts},
        {"showdiskusageincurrentdir", doShowDiskUsageInCurrentDir},
        {"getcpucorecount", doGetCpuCoreCount},
        {"gettotalsystemmemory", doGetTotalSystemMemory},
        {"getfreesystemmemory", doGetFreeSystemMemory},
        {"listcurrentlymountedfilesystems", doListCurrentlyMountedFilesystems},
        {"showlastloginattempts", doShowLastLoginAttempts},
        {"showcurrentuser", doShowCurrentUser},
        {"listcurrentusersgroups", doListCurrentUsersGroups},
        {"showsystemdateandtime", doShowSystemDateAndTime},
        {"showcalendarforcurrentmonth", doShowCalendarForCurrentMonth},
        {"listrunningprocesses", doListRunningProcesses},
        {"showcpuloadaverage", doShowCpuLoadAverage},
        {"shownetworktrafficstatistics", doShowNetworkTrafficStatistics},
        {"getpublicipaddress", doGetPublicIpAddress},
        {"listenvironmentvariables", doListEnvironmentVariables},
        {"showcurrentuserhistory", doShowCurrentUserHistory},
        {"getshellname", doGetShellName},
        {"checkservicestatussshd", doCheckServiceStatusSshd},
        {"checkservicestatusnginx", doCheckServiceStatusNginx},
        {"checkservicestatusapache2", doCheckServiceStatusApache2},
        {"getdefaultbrowserinfo", doGetDefaultBrowserInfo},
        {"listallaliases", doListAllAliases},
        {"showrecentkernelmessages", doShowRecentKernelMessages},
        {"getprocesscount", doGetProcessCount},
        {"showkernelversion", doShowKernelVersion},
        {"showavailablediskspaceroot", doShowAvailableDiskSpaceRoot},
        {"listcurrentusersopenfiles", doListCurrentUsersOpenFiles},
        {"showcurrentuserdiskquota", doShowCurrentUserDiskQuota},
        {"listallpackagesinstalled", doListAllPackagesInstalled},
        {"getdefaultrouteinterface", doGetDefaultRouteInterface},
        {"getnetworksppedeth0", doGetNetworkSpeedEth0},
        {"showsystembootmessages", doShowSystemBootMessages},
        {"listusersinsudogroup", doListUsersInSudoGroup},
        {"getfilesystemtyperoot", doGetFilesystemTypeRoot},
        {"getlastboottime", doGetLastBootTime},
        {"checkclipboardcontent", doCheckClipboardContent},
        {"listusercronjobs", doListUserCronJobs},
        {"showcurrentterminaltype", doShowCurrentTerminalType},
        {"getsystemlocale", doGetSystemLocale},
        {"listuserdownloaddirectory", doListUserDownloadDirectory},
    {"counthiddenfilesinhome", doCountHiddenFilesInHome},
        {"getlongestfilenameincurrentdir", doGetLongestFileNameInCurrentDir},
        {"showdiskinodeusage", doShowDiskInodeUsage},
        {"getsystemhostid", doGetSystemHostid},
        {"getbiosversion", doGetBiosVersion},
        {"listallblockdevices", doListAllBlockDevices},
        {"showopenfilescountsystemwide", doShowOpenFilesCountSystemWide},
        {"getmaxnumnumberofprocesses", doGetMaxNumberOfProcesses},
        {"getmaxnumberofopenfiles", doGetMaxNumberOfOpenFiles},
        {"getsystembootid", doGetSystemBootId},
        {"checkswaspaceusage", doCheckSwapSpaceUsage},
        {"showlastsystemreboot", doShowLastSystemReboot},
        {"getnetworkhostname", doGetNetworkHostname},
        {"showroutingtableentries", doShowRoutingTableEntries},
        {"checknetworkinterfaceupeth0", doCheckNetworkInterfaceUpEth0},
        {"listallnetworkconnections", doListAllNetworkConnections},
        {"getbatterystatus", doGetBatteryStatus},
        {"getmonitorresolution", doGetMonitorResolution},
        {"checkkeyboardlayout", doCheckKeyboardLayout},
        {"getdesktopenvironment", doGetDesktopEnvironment},
        {"showgraphicalsessionid", doShowGraphicalSessionId},
        {"listallusersuids", doListAllUsersUIDs},
        {"getcurrentusergid", doGetCurrentUserGID},
        {"getloginattemptsincboot", doGetLoginAttemptsSinceBoot},
        {"showfailedloginattempts", doShowFailedLoginAttempts},
        {"listallsystemgroups", doListAllSystemGroups},
        {"getsystemdunitfilescount", doGetSystemdUnitFilesCount},
        {"showcputemperature", doShowCpuTemperature},
        {"showgpuinformation", doShowGpuInformation},
        {"getsoundcardinfo", doGetSoundCardInfo},
        {"listusbdevices", doListUsbDevices},
        {"listpcidevices", doListPciDevices},
        {"showcpufrequency", doShowCpuFrequency},
        {"getmemoryslotsinfo", doGetMemorySlotsInfo},
        {"showsystemvoltage", doShowSystemVoltage},
        {"getfanspeed", doGetFanSpeed},
        {"getdisktemperature", doGetDiskTemperature},
        {"shownetworkbandwidthusage", doShowNetworkBandwidthUsage},
        {"checkprinterstatus", doCheckPrinterStatus},
        {"listallinstalledfonts", doListAllInstalledFonts},
        {"checkbluetoothstatus", doCheckBluetoothStatus},
        {"checkwifistatus", doCheckWifiStatus},
        {"getkernelmodulesloaded", doGetKernelModulesLoaded},
        {"showsystemlogsize", doShowSystemLogSize},
        {"getdefaulteditor", doGetDefaultEditor},
    {"checkuserexist", doCheckUserExist},
        {"getusersdefaultshell", doGetUsersDefaultShell},
        {"listuserprocesses", doListUserProcesses},
        {"checkifuserloggedin", doCheckIfUserLoggedIn},
        {"getusershomedirectory", doGetUsersHomeDirectory},
        {"listallloginshellsavailable", doListAllLoginShellsAvailable},
        {"showkernelmoduledependencies", doShowKernelModuleDependencies},
        {"getprocessorvendorid", doGetProcessorVendorId},
        {"checkifvirtualmachine", doCheckIfVirtualMachine},
        {"showcpuflags", doShowCpuFlags},
        {"listallopentcpconnections", doListAllOpenTcpConnections},
        {"listallopenudpconnections", doListAllOpenUdpConnections},
        {"getnetworkcardmacaddress", doGetNetworkCardMacAddress},
        {"shownetworkinterfacestatisticseth0", doShowNetworkInterfaceStatisticsEth0},
        {"getdefaultinterfacemtu", doGetDefaultInterfaceMTU},
        {"listallavailablenetworkdevices", doListAllAvailableNetworkDevices},
        {"listavailablekeyboardlayouts", doListAvailableKeyboardLayouts},
        {"showxorglogerrors", doShowXorgLogErrors},
        {"getpackagemanagername", doGetPackageManagerName},
        {"showdisksectorsize", doShowDiskSectorSize},
        {"checkiffileisreadable", doCheckIfFileIsReadable},
        {"checkiffileiswritable", doCheckIfFileIsWritable},
        {"showfileownerandgroup", doShowFileOwnerAndGroup},
        {"showfilepermissions", doShowFilePermissions},
        {"showlastmodifiedtimeoffile", doShowLastModifiedTimeOfFile},
        {"showcreationtimeoffile", doShowCreationTimeOfFile},
        {"getfilesize", doGetFileSize},
        {"showfilechecksummd5", doShowFileChecksumMd5},
        {"showfilechecksumsha256", doShowFileChecksumSha256},
        {"checkifdirectoryexists", doCheckIfDirectoryExists},
        {"showdirectorycontentsrecursive", doShowDirectoryContentsRecursive},
        {"getdirectorysizerecursive", doGetDirectorySizeRecursive},
        {"showcurrentuseruid", doShowCurrentUserUid},
        {"showcurrentusergid", doShowCurrentUserGid},
        {"getuserssupplementarygroups", doGetUsersSupplementaryGroups},
        {"checkifcommandexists", doCheckIfCommandExists},
        {"showcommandfullpath", doShowCommandFullPath},
        {"getsystemarchitecture", doGetSystemArchitecture},
        {"getsystemreleaseversion", doGetSystemReleaseVersion},
        {"showallloadedmodules", doShowAllLoadedModules},
        {"getnetworkdevicedriver", doGetNetworkDeviceDriver},
        {"showdiskioostatistics", doShowDiskIoStatistics},
        {"getramdisksize", doGetRamDiskSize},
        {"showsyslogentriesfortoday", doShowSyslogEntriesForToday},
        {"getdefaulttimezoneoffset", doGetDefaultTimeZoneOffset},
    {"checkavailableupdates", doCheckAvailableUpdates},
        {"getpackagemanagercachesize", doGetPackageManagerCacheSize},
        {"listrecentlyinstalledpackages", doListRecentlyInstalledPackages},
        {"getpackagecountinstalled", doGetPackageCountInstalled},
        {"showdiskusagebyfilesystem", doShowDiskUsageByFilesystem},
        {"showmountoptionsforroot", doShowMountOptionsForRoot},
        {"checkifswappartitionexists", doCheckIfSwapPartitionExists},
        {"showavailableswapdevices", doShowAvailableSwapDevices},
        {"listallnetworkroutes", doListAllNetworkRoutes},
        {"checkspecificportstatus", doCheckSpecificPortStatus},
        {"showkernelbuilddate", doShowKernelBuildDate},
        {"getsystemarchitectureendianness", doGetSystemArchitectureEndianness},
        {"showcpuvulnerabilities", doShowCpuVulnerabilities},
        {"getcpuphysicalcores", doGetCpuPhysicalCores},
        {"listallloadedkernelmodules", doListAllLoadedKernelModules},
        {"showsystemconsolefont", doShowSystemConsoleFont},
        {"getloggedinuserscount", doGetLoggedInUsersCount},
        {"showuseridletime", doShowUserIdleTime},
        {"listusersloginsessions", doListUsersLoginSessions},
        {"getlastuserlogintime", doGetLastUserLoginTime},
        {"checkifuserhaspassword", doCheckIfUserHasPassword},
        {"listallsystemusers", doListAllSystemUsers},
        {"showlastchangedpassworddate", doShowLastChangedPasswordDate},
        {"getshellversion", doGetShellVersion},
        {"showcurrentterminalwidth", doShowCurrentTerminalWidth},
        {"showcurrentterminalheight", doShowCurrentTerminalHeight},
        {"listallrunningservices", doListAllRunningServices},
        {"showsystemdjournaldiskusage", doShowSystemdJournalDiskUsage},
        {"checkserviceenabledstatus", doCheckServiceEnabledStatus},
        {"getsystemlocalecharset", doGetSystemLocaleCharset},
        {"listavailablelocales", doListAvailableLocales},
        {"showcurrentworkingdirectorysize", doShowCurrentWorkingDirectorySize},
        {"countfilesindirectory", doCountFilesInDirectory},
        {"countdirectoriesindirectory", doCountDirectoriesInDirectory},
        {"gettotaldiskspace", doGetTotalDiskSpace},
        {"getuseddiskspace", doGetUsedDiskSpace},
        {"getfreediskspace", doGetFreeDiskSpace},
        {"showdiskusageforallmountpoints", doShowDiskUsageForAllMountPoints},
        {"showfilesystemmounttime", doShowFilesystemMountTime},
        {"getkernelcommandline", doGetKernelCommandLine},
        {"showprocesstree", doShowProcessTree},
        {"getprocesscpuusage", doGetProcessCpuUsage},
        {"showrecentshutdowns", doShowRecentShutdowns},
        {"checkrtctime", doCheckRtcTime},
        {"getsystemhardwareclocktime", doGetSystemHardwareClockTime},
        {"shownetworkdhcpleaseinfo", doShowNetworkDhcpLeaseInfo},
        {"shownetworkdnsresolver", doShowNetworkDNSResolver},
    {"checkntpsyncstatus", doCheckNtpSyncStatus},
        {"getntpserverlist", doGetNtpServerList},
        {"showsystemuptime", doShowSystemUptime},
        {"showloadaverageoneminute", doShowLoadAverageOneMinute},
        {"showloadaveragefiveminutes", doShowLoadAverageFiveMinutes},
        {"showloadaveragefifteenminutes", doShowLoadAverageFifteenMinutes},
        {"getkernelversionfull", doGetKernelVersionFull},
        {"showcpuinfosummary", doShowCpuInfoSummary},
        {"getprocessesperuser", doGetProcessesPerUser},
        {"showcpuinterruptsinfo", doShowCpuInterruptsInfo},
        {"showmemoryactiveusage", doShowMemoryActiveUsage},
        {"showmemoryinactiveusage", doShowMemoryInactiveUsage},
        {"showmemorydirtyusage", doShowMemoryDirtyUsage},
        {"showmemorywritebackusage", doShowMemoryWritebackUsage},
        {"getfilesystemmountcount", doGetFileSystemMountCount},
        {"showfilesystemtypeforpath", doShowFileSystemTypeForPath},
        {"getfreeinodescount", doGetFreeInodesCount},
        {"showdiskioqueuesize", doShowDiskIoQueueSize},
        {"checkifssdexists", doCheckIfSsdExists},
        {"getdiskreadspeed", doGetDiskReadSpeed},
        {"getdiskwritespeed", doGetDiskWriteSpeed},
        {"shownetworkpacketerrors", doShowNetworkPacketErrors},
        {"shownetworkdroppedpackets", doShowNetworkDroppedPackets},
        {"getnetworkinterfacequeuelength", doGetNetworkInterfaceQueueLength},
        {"getnetworkbroadcastaddress", doGetNetworkBroadcastAddress},
        {"shownetworkmulticastaddresses", doShowNetworkMulticastAddresses},
        {"checkdnsresolutionforhost", doCheckDnsResolutionForHost},
        {"getdefaultshellpath", doGetDefaultShellPath},
        {"showcurrentuserterminalname", doShowCurrentUserTerminalName},
        {"showloginattemptstoday", doShowLoginAttemptsToday},
        {"checkifuserhashomedirectory", doCheckIfUserHasHomeDirectory},
        {"listuserdefinedaliases", doListUserDefinedAliases},
        {"gettotalusersonsystem", doGetTotalUsersOnSystem},
        {"showsystemtimezonename", doShowSystemTimeZoneName},
        {"getsystemlocaleencoding", doGetSystemLocaleEncoding},
        {"showsystemhostnameshort", doShowSystemHostnameShort},
        {"getsystemdbusaddress", doGetSystemDbusAddress},
        {"listallcronjobfiles", doListAllCronJobFiles},
        {"showcurrentlyopenfilescount", doShowCurrentlyOpenFilesCount},
        {"getmaxfiledescriptorssystemwide", doGetMaxFileDescriptorsSystemWide},
        {"checkifpowersavingenabled", doCheckIfPowerSavingEnabled},
        {"getcpugovernor", doGetCpuGovernor},
        {"showhardwareinfosummary", doShowHardwareInfoSummary},
        {"checksystemclocksynchronization", doCheckSystemClockSynchronization},
        {"getbootuptimeinseconds", doGetBootupTimeInSeconds},
        {"showactivenetworkconnectionscount", doShowActiveNetworkConnectionsCount},
        {"listnetworkinterfacesonly", doListNetworkInterfacesOnly},
    {"showipv4addresses", doShowIpV4Addresses},
        {"showipv6addresses", doShowIpV6Addresses},
        {"showdnsserverip", doShowDnsServerIp},
        {"listallnetworkportsinuse", doListAllNetworkPortsInUse},
        {"checkifinterfaceisup", doCheckIfInterfaceIsUp},
        {"getnetworklinkspeed", doGetNetworkLinkSpeed},
        {"showwifisignalstrength", doShowWifiSignalStrength},
        {"showopensshsessions", doShowOpenSshSessions},
        {"getpackagemanagerlistavailable", doGetPackageManagerListAvailable},
        {"showpackageinstallsize", doShowPackageInstallSize},
        {"getlastbootkernelversion", doGetLastBootKernelVersion},
        {"checkkernelmodulescompatibility", doCheckKernelModulesCompatibility},
        {"getcputemperaturesensorpath", doGetCpuTemperatureSensorPath},
        {"showsystemvoltagesummary", doShowSystemVoltageSummary},
        {"getfanspeedsummary", doGetFanSpeedSummary},
        {"showdisksmartstatus", doShowDiskSmartStatus},
        {"gettotalmemoryinstalled", doGetTotalMemoryInstalled},
        {"getmemoryfreeamount", doGetMemoryFreeAmount},
        {"getmemoryusedamount", doGetMemoryUsedAmount},
        {"showswapmemoryused", doShowSwapMemoryUsed},
        {"showswapmemoryfree", doShowSwapMemoryFree},
        {"showtopfivecpuprocesses", doShowTopFiveCpuProcesses},
        {"showtopfivememoryprocesses", doShowTopFiveMemoryProcesses},
        {"getprocessparentpid", doGetProcessParentPid},
        {"showcurrentusersloginshell", doShowCurrentUsersLoginShell},
        {"listallloginrecords", doListAllLoginRecords},
        {"getlastsuccessfulloginuser", doGetLastSuccessfulLoginUser},
        {"getlastfailedloginuser", doGetLastFailedLoginUser},
        {"showusergroupmemberships", doShowUserGroupMemberships},
        {"showavailableshellsforuser", doShowAvailableShellsForUser},
        {"getsystemdefaulttimezone", doGetSystemDefaultTimezone},
        {"showallsetenvironmentvariables", doShowAllSetEnvironmentVariables},
        {"getspecificenvironmentvariable", doGetSpecificEnvironmentVariable},
        {"showcurrentusershomedirectory", doShowCurrentUsersHomeDirectory},
        {"showcurrentuserprimarygroup", doShowCurrentUserPrimaryGroup},
        {"getsystemrunlevelhistory", doGetSystemRunlevelHistory},
        {"listallsystemservices", doListAllSystemServices},
        {"checkservicerunningstatus", doCheckServiceRunningStatus},
        {"getsystemdactiveunitcount", doGetSystemdActiveUnitCount},
        {"showsystemdfailedunitcount", doShowSystemdFailedUnitCount},
        {"showdiskhealthoverview", doShowDiskHealthOverview},
        {"listallmountedfilesystems", doListAllMountedFilesystems},
        {"getfilesystemlabel", doGetFileSystemLabel},
        {"showfilesystemusagepercent", doShowFileSystemUsagePercent},
        {"checkifpathismountpoint", doCheckIfPathIsMountPoint},
        {"showsystemlogsbytype", doShowSystemLogsByType},
    {"getsystemboottimehumanreadable", doGetSystemBootTimeHumanReadable},
        {"showkernelringbuffercontent", doShowKernelRingBufferContent},
        {"showrecentdmesgerrors", doShowRecentDmesgErrors},
        {"getsystemloadaveragehistory", doGetSystemLoadAverageHistory},
        {"showcpucoreonlinestatus", doShowCpuCoreOnlineStatus},
        {"gettotalcputhreads", doGetTotalCpuThreads},
        {"showmemorycacheusage", doShowMemoryCacheUsage},
        {"showmemorybufferusage", doShowMemoryBufferUsage},
        {"gettoptenlargestfiles", doGetTopTenLargestFiles},
        {"showdirectorymodificationtime", doShowDirectoryModificationTime},
        {"getfilesystemiostatistics", doGetFilesystemIoStatistics},
        {"checkifpartitionismounted", doCheckIfPartitionIsMounted},
        {"showdiskusageforuserhome", doShowDiskUsageForUserHome},
        {"getnetworkinterfacelinkstatus", doGetNetworkInterfaceLinkStatus},
        {"checknetworkconnectivitytogateway", doCheckNetworkConnectivityToGateway},
        {"showactivelisteningports", doShowActiveListeningPorts},
        {"listnetworkinterfaceswithip", doListNetworkInterfacesWithIp},
        {"checkhostnameresolution", doCheckHostnameResolution},
        {"showcurrentusername", doShowCurrentUserName},
        {"getuseridnumber", doGetUserIdNumber},
        {"listusersinspecificgroup", doListUsersInSpecificGroup},
        {"showuserloginshells", doShowUserLoginShells},
        {"getsystemdefaultlanguage", doGetSystemDefaultLanguage},
        {"showallloadedfonts", doShowAllLoadedFonts},
        {"getgraphicaldesktopenvironment", doGetGraphicalDesktopEnvironment},
        {"checkifxserverisrunning", doCheckIfXServerIsRunning},
        {"showcurrentdisplayresolution", doShowCurrentDisplayResolution},
        {"listallinstalledpackages", doListAllInstalledPackages},
        {"getpackagedependencies", doGetPackageDependencies},
        {"showpackageversion", doShowPackageVersion},
        {"getpackagemanagerrepositorylist", doGetPackageManagerRepositoryList},
        {"showcpuutilizationpercore", doShowCpuUtilizationPerCore},
        {"gettotalrunningprocesses", doGetTotalRunningProcesses},
        {"listprocessesbyuser", doListProcessesByUser},
        {"getprocessmemoryresidentsetsize", doGetProcessMemoryResidentSetSize},
        {"showsystemdservicedependencies", doShowSystemdServiceDependencies},
        {"checksystemdserviceactivetime", doCheckSystemdServiceActiveTime},
        {"getsystemdservicepid", doGetSystemdServicePid},
        {"showdiskpartitiontabletype", doShowDiskPartitionTableType},
        {"getfilesysteminodeusage", doGetFileSystemInodeUsage},
        {"showfilesystembadblocks", doShowFileSystemBadBlocks},
        {"gettotalsystemram", doGetTotalSystemRam},
        {"getfreesystemram", doGetFreeSystemRam},
        {"getusedsystemram", doGetUsedSystemRam},
        {"shownetworkinterfacepacketcounts", doShowNetworkInterfacePacketCounts},
        {"shownetworkinterfaceerrorcounts", doShowNetworkInterfaceErrorCounts},
        {"checkifuserissudoer", doCheckIfUserIsSudoer},
    {"showuserlastlogintime", doShowUserLastLoginTime},
        {"getsystemuserlistfull", doGetSystemUserListFull},
        {"showuserdiskquotasummary", doShowUserDiskQuotaSummary},
        {"getfilesystemusedspacepercent", doGetFilesystemUsedSpacePercent},
        {"showfilesystemfreespacehumanreadable", doShowFileSystemFreeSpaceHumanReadable},
        {"checkifdirectoryisempty", doCheckIfDirectoryIsEmpty},
        {"getfilepermissionsoctal", doGetFilePermissionsOctal},
        {"showfilesizeinbytes", doShowFileSizeInBytes},
        {"getfileownerandgroup", doGetFileOwnerAndGroup},
        {"checkiffileisexecutable", doCheckIfFileIsExecutable},
        {"showcpumodelname", doShowCpuModelName},
        {"showcpuclockspeedmhz", doShowCpuClockSpeedMHz},
        {"getmemoryswapusedpercentage", doGetMemorySwapUsedPercentage},
        {"showmemoryavailableforapplications", doShowMemoryAvailableForApplications},
        {"gettotalprocessessleeping", doGetTotalProcessesSleeping},
        {"showprocessesinzombiestate", doShowProcessesInZombieState},
        {"getprocesscpuaffinity", doGetProcessCpuAffinity},
        {"showprocessmemorymaps", doShowProcessMemoryMaps},
        {"getnetworkinterfacemacaddress", doGetNetworkInterfaceMacAddress},
        {"shownetworkinterfacestatistics", doShowNetworkInterfaceStatistics},
        {"getnetworkroutetable", doGetNetworkRouteTable},
        {"checkifportisopen", doCheckIfPortIsOpen},
        {"showhostnametoipmapping", doShowHostNameToIpMapping},
        {"getlocalhostname", doGetLocalHostname},
        {"showdnscachestatistics", doShowDnsCacheStatistics},
        {"getsystempackagecount", doGetSystemPackageCount},
        {"checkifpackageisinstalled", doCheckIfPackageIsInstalled},
        {"showpackageupdatestatus", doShowPackageUpdateStatus},
        {"showsystemsecurityauditlog", doShowSystemSecurityAuditLog},
        {"checkifselinuxenforcing", doCheckIfSelinuxEnforcing},
        {"showsystemserviceunitfilestatus", doShowSystemServiceUnitFileStatus},
        {"getsystemdtargetunits", doGetSystemdTargetUnits},
        {"showsystemdserviceruntimestatus", doShowSystemdServiceRuntimeStatus},
        {"getsystemdjournalsize", doGetSystemdJournalSize},
        {"showkernelmodulelist", doShowKernelModuleList},
        {"getloadedkernelmodulescount", doGetLoadedKernelModulesCount},
        {"showkernelversionshort", doShowKernelVersionShort},
        {"getbootkernelparameters", doGetBootKernelParameters},
        {"checksystemclockhardwaretimesync", doCheckSystemClockHardwareTimeSync},
        {"showsystementropyavailable", doShowSystemEntropyAvailable},
        {"getsystemrandompoolsize", doGetSystemRandomPoolSize},
        {"showsystemtemperatureoverall", doShowSystemTemperatureOverall},
        {"getbatterychargelevel", doGetBatteryChargeLevel},
        {"showbatteryhealthstatus", doShowBatteryHealthStatus},
        {"getcpuusagepercentageoverall", doGetCpuUsagePercentageOverall},
        {"showmemoryusagepercentageoverall", doShowMemoryUsagePercentageOverall},
        {"gettotalswapspace", doGetTotalSwapSpace},
    {"showinstalledfontscount", doShowInstalledFontsCount},
        {"getsystemdefaultprinter", doGetSystemDefaultPrinter},
        {"showrunningservicescount", doShowRunningServicesCount},
        {"listallcronjobsforuser", doListAllCronJobsForUser},
        {"showuserhistorycommandcount", doShowUserHistoryCommandCount},
        {"getsystemuptimeindays", doGetSystemUptimeInDays},
        {"showlastfiveloggedusers", doShowLastFiveLoggedUsers},
        {"getsystemhostnamefullyqualified", doGetSystemHostnameFullyQualified},
        {"shownetworktrafficperinterface", doShowNetworkTrafficPerInterface},
        {"getnetworkpacketlosspercentage", doGetNetworkPacketLossPercentage},
        {"showfirewallrulescount", doShowFirewallRulesCount},
        {"getopenfilecountsystemwide", doGetOpenFileCountSystemWide},
        {"showtoptenlargestdirectories", doShowTopTenLargestDirectories},
        {"showdiskioreadwritespeed", doShowDiskIoReadWriteSpeed},
        {"gettotaldiskspacehumanreadable", doGetTotalDiskSpaceHumanReadable},
        {"showavailablediskspacehumanreadable", doShowAvailableDiskSpaceHumanReadable},
        {"checkifserviceisenabledatboot", doCheckIfServiceIsEnabledAtBoot},
        {"showsystemdservicefailurereasons", doShowSystemdServiceFailureReasons},
        {"getsystemddefaulttarget", doGetSystemdDefaultTarget},
        {"showkernelversiondetails", doShowKernelVersionDetails},
        {"getkernelbuilddate", doGetKernelBuildDate},
        {"showcpuinterruptstatistics", doShowCpuInterruptStatistics},
        {"getmemoryusedbykernel", doGetMemoryUsedByKernel},
        {"showmemoryslabusage", doShowMemorySlabUsage},
        {"gettotalprocessesrunning", doGetTotalProcessesRunning},
        {"showprocessstatusforpid", doShowProcessStatusForPid},
        {"getprocesscputimeused", doGetProcessCpuTimeUsed},
        {"showuserloggintty", doShowUserLoggedInTty},
        {"getsystemdefaultusershell", doGetSystemDefaultUserShell},
        {"showallsystemgroups", doShowAllSystemGroups},
        {"getusersprimarygroup", doGetUsersPrimaryGroup},
        {"showsystemcurrentdateandtime", doShowSystemCurrentDateAndTime},
        {"getsystemtimezoneoffset", doGetSystemTimezoneOffset},
        {"showallsystemlocales", doShowAllSystemLocales},
        {"getenvironmentvariableforprocess", doGetEnvironmentVariableForProcess},
        {"showuserloginshelllocation", doShowUserLoginShellLocation},
        {"checkifuseraccountislocked", doCheckIfUserAccountIsLocked},
        {"showrecentloginattemptsbyip", doShowRecentLoginAttemptsByIp},
        {"getpackagelatestversionavailable", doGetPackageLatestVersionAvailable},
        {"showpackagechecksum", doShowPackageChecksum},
        {"getpackagemanagerlogfilelocation", doGetPackageManagerLogFileLocation},
        {"showcpufrequencyscalinggovernor", doShowCpuFrequencyScalingGovernor},
        {"getcputemperaturethresholds", doGetCpuTemperatureThresholds},
        {"showsystempowerconsumption", doShowSystemPowerConsumption},
        {"getbatterycyclecount", doGetBatteryCycleCount},
        {"shownetworkconnectionlatency", doShowNetworkConnectionLatency},
        {"checkifsshserviceisrunning", doCheckIfSshServiceIsRunning},
        {"gettotalphysicalmemory", doGetTotalPhysicalMemory},
    {"getnetworkinterfacereceiveerrors", doGetNetworkInterfaceReceiveErrors},
        {"shownetworkinterfacetransmiterrors", doShowNetworkInterfaceTransmitErrors},
        {"getnetworkinterfacecollisions", doGetNetworkInterfaceCollisions},
        {"showkernelmoduleparameters", doShowKernelModuleParameters},
        {"getsystemopenfileslimit", doGetSystemOpenFilesLimit},
        {"showuserloginhistory", doShowUserLoginHistory},
        {"getsystemusershomedirectory", doGetSystemUsersHomeDirectory},
        {"showsystemusergroups", doShowSystemUserGroups},
        {"getfileinodenumber", doGetFileInodeNumber},
        {"showfilelastaccesstime", doShowFileLastAccessTime},
        {"getfilelastmodificationtime", doGetFileLastModificationTime},
        {"showdirectorysizehumanreadable", doShowDirectorySizeHumanReadable},
        {"getfilesystemblocksize", doGetFilesystemBlockSize},
        {"showfilesystemtype", doShowFileSystemType},
        {"getcpuidletime", doGetCpuIdleTime},
        {"showcpucontextswitches", doShowCpuContextSwitches},
        {"getmemoryusedbybuffersandcache", doGetMemoryUsedByBuffersAndCache},
        {"showmemoryactiveinactive", doShowMemoryActiveInactive},
        {"gettotalprocessthreads", doGetTotalProcessThreads},
        {"showprocesscpuusage", doShowProcessCpuUsage},
        {"getprocessmemoryusage", doGetProcessMemoryUsage},
        {"showsystemdservicemountpoints", doShowSystemdServiceMountPoints},
        {"getsystemdserviceexecstartcommand", doGetSystemdServiceExecStartCommand},
        {"showsystemdservicepidfile", doShowSystemdServicePidFile},
        {"getsystemlogfilelocation", doGetSystemLogFileLocation},
        {"showkernelringbuffersize", doShowKernelRingBufferSize},
        {"getsystembootmessagelocation", doGetSystemBootMessageLocation},
        {"shownetworkinterfaceipaddress", doShowNetworkInterfaceIpAddress},
        {"getnetworkinterfacesubnetmask", doGetNetworkInterfaceSubnetMask},
        {"shownetworkinterfacebroadcastaddress", doShowNetworkInterfaceBroadcastAddress},
        {"checkifdefaultgatewayisreachable", doCheckIfDefaultGatewayIsReachable},
        {"getdnsserveripaddresses", doGetDnsServerIpAddresses},
        {"showcurrentworkingdir", doShowCurrentWorkingDir},
        {"getusernamefromid", doGetUserNameFromId},
        {"showgroupidfromname", doShowGroupIdFromName},
        {"getsystemdefaultgateway", doGetSystemDefaultGateway},
        {"showsystemdefaultroutemetric", doShowSystemDefaultRouteMetric},
        {"getavailableshellsonsystem", doGetAvailableShellsOnSystem},
        {"checkifusercansudowithoutpassword", doCheckIfUserCanSudoWithoutPassword},
        {"showsystemhostnamealiases", doShowSystemHostnameAliases},
        {"gettotalconnectedusers", doGetTotalConnectedUsers},
        {"showuserconnectedterminals", doShowUserConnectedTerminals},
        {"getsystemdefaultlocale", doGetSystemDefaultLocale},
        {"showloadedkernelmodules", doShowLoadedKernelModules},
        {"getkernelarchitecture", doGetKernelArchitecture},
        {"showcpucorecount", doShowCpuCoreCount},
        {"getmemoryswapcached", doGetMemorySwapCached},
        {"showsystemrunlevel", doShowSystemRunlevel},
        {"getsysteminitprocesspid", doGetSystemInitProcessPid},
    {"showsystemprocesstree", doShowSystemProcessTree},
        {"getprocessnicevalue", doGetProcessNiceValue},
        {"showprocesschildrenpids", doShowProcessChildrenPids},
        {"getnetworksocketstatistics", doGetNetworkSocketStatistics},
        {"shownetworklistenports", doShowNetworkListenPorts},
        {"getsystemdhcpclientinfo", doGetSystemDhcpClientInfo},
        {"showmountedfilesystemscount", doShowMountedFileSystemsCount},
        {"getfilesystemtotalinodes", doGetFileSystemTotalInodes},
        {"showfilesystemfreeinodes", doShowFileSystemFreeInodes},
        {"getcpuvendorid", doGetCpuVendorId},
        {"showcpubugflags", doShowCpuBugFlags},
        {"getmemoryfreepercentage", doGetMemoryFreePercentage},
        {"showmemoryusedbysharedbuffers", doShowMemoryUsedBySharedBuffers},
        {"getsystemloadaverage", doGetSystemLoadAverage},
        {"showsystemboottime", doShowSystemBootTime},
        {"getsystemkernelparameters", doGetSystemKernelParameters},
        {"shownetworkinterfacequeuelength", doShowNetworkInterfaceQueueLength},
        {"getnetworkinterfacemulticastaddresses", doGetNetworkInterfaceMulticastAddresses},
        {"shownetworkinterfacestatus", doShowNetworkInterfaceStatus},
        {"getsystempacketfilterstatus", doGetSystemPacketFilterStatus},
        {"showlastreboottime", doShowLastRebootTime},
        {"getsystemtimezone", doGetSystemTimeZone},
        {"showuserloggedinsessions", doShowUserLoggedInSessions},
        {"getsystemrunningservices", doGetSystemRunningServices},
        {"showsystemavailableramslots", doShowSystemAvailableRamSlots},
        {"getcputhreadcountpercore", doGetCpuThreadCountPerCore},
        {"showdiskserialnumber", doShowDiskSerialNumber},
        {"getdisksmartstatus", doGetDiskSmartStatus},
        {"showtotalnetworkbytestransmitted", doShowTotalNetworkBytesTransmitted},
        {"gettotalnetworkbytesreceived", doGetTotalNetworkBytesReceived},
        {"showprocessopenfiledescriptors", doShowProcessOpenFileDescriptors},
        {"showprocesseffectiveuser", doShowProcessEffectiveUser},
        {"getsystemfirewallrules", doGetSystemFirewallRules},
        {"showsystemcronstatus", doShowSystemCronStatus},
        {"getsystemdunitdependencies", doGetSystemdUnitDependencies},
        {"showkernelversionbuildoptions", doShowKernelVersionBuildOptions},
        {"getkernelmaxopenfiles", doGetKernelMaxOpenFiles},
        {"showsystemdjournallogsizelimit", doShowSystemdJournalLogSizeLimit},
        {"getnetworkinterfacepacketerrors", doGetNetworkInterfacePacketErrors},
        {"shownetworkinterfacedroppedpackets", doShowNetworkInterfaceDroppedPackets},
        {"getsystemdefaultrouteinterface", doGetSystemDefaultRouteInterface},
        {"showsystemlogingracetime", doShowSystemLoginGraceTime},
        {"getcpumicrocodeversion", doGetCpuMicrocodeVersion},
        {"showmemorypagefaults", doShowMemoryPageFaults},
        {"getsystemcputopology", doGetSystemCpuTopology},
        {"showsystemblockdevicelist", doShowSystemBlockDeviceList},
        {"getnetworkinterfacespeed", doGetNetworkInterfaceSpeed},
        {"showselinuxpolicyversion", doShowSelinuxPolicyVersion},
};

std::unordered_map<std::string, openSingleFunc> emptyFuncs = {
    {"trash", emptyTrash},
    {"tempfile", emptyTempfile},
    {"dependencies",emptyDependencies}
};



int InstructionSet::openAnySkip(const std::vector<std::string>& args, int index)
{
    return 0;
}

int InstructionSet::openAny(const std::vector<std::string>& args, int index)
{
    if(args.size() < 2)
        return ERROR_PARA;
    int status = RE_SUCCESS;

    auto it = openFuncs.find(args[1]);
    if (it != openFuncs.end()) {
        // 调用找到的函数
        std::cout << index << std::endl;
        it->second(0);
    }
    else if(isUrl(args[1]))
    {
        std::cout << "open url" << std::endl;
        status = openUrl(args[1]);
    }
    else if(isMail(args[1]))
    {
        std::cout << "open mail" << std::endl;
        status = openMail(args[1]);
    }
    else
    {
        std::cout << "open application" << std::endl;

        status = openOrCloseApplication(args[1], true, true);
        if(status==0)
        {
            printIndex(index);
            if(index == -1)
            {
                std::cout << "已经打开" << appZhName << std::endl;
            }
            else
            {
                std::cout << "打开" << appZhName << "  [已完成]" << std::endl;
            }
        }
        else
        {
            std::cout << "<AI>打开失败，无法找到需要打开的目标，或许是我不太理解需要打开的目标";
        }
    }
    checkIfEnd(tasks->size(), index);
    if(status == ERROR_PARA)
    {

    }

    return status;
}

int InstructionSet::showAny(const std::vector<std::string>& args, int index)
{
    if(args.size() < 2)
        return ERROR_PARA;
    int status = RE_SUCCESS;

    auto it = showFuncs.find(args[1]);
    if (it != showFuncs.end()) {
        // 调用找到的函数
        it->second(index);
    }
    checkIfEnd(tasks->size(), index);
    if(status == ERROR_PARA)
    {

    }

    return status;
}

int InstructionSet::doAny(const std::vector<std::string>& args, int index)
{
    if(args.size() < 2)
        return ERROR_PARA;
    int status = RE_SUCCESS;

    auto it = doFuncs.find(args[1]);
    if (it != doFuncs.end()) {
        // 调用找到的函数
        it->second(index);
    }
    checkIfEnd(tasks->size(), index);
    if(status == ERROR_PARA)
    {

    }

    return status;
}
int InstructionSet::emptyAny(const std::vector<std::string>& args, int index)
{
    if(args.size() < 2)
        return ERROR_PARA;
    int status = RE_SUCCESS;

    auto it = emptyFuncs.find(args[1]);
    if (it != emptyFuncs.end()) {
        // 调用找到的函数
        it->second(index);
    }
    checkIfEnd(tasks->size(), index);
    if(status == ERROR_PARA)
    {

    }

    return status;
}


int InstructionSet::restartSkip(const std::vector<std::string>& args, int index)
{
    return 0;
}

int sessionTools(QString acttion, QString text)
{
    KMessageBox msgBox(nullptr);
    msgBox.setFixedSize(424,164);
    msgBox.setCustomIcon(QIcon::fromTheme("ukui-dialog-success"));
    msgBox.setWindowTitle("");
    msgBox.setText(text);

    KPushButton btnOK(&msgBox);
    btnOK.setBackgroundColorHighlight(true);
    btnOK.setText("Restart");
    msgBox.addButton(&btnOK, KMessageBox::YesRole);
    msgBox.setDefaultButton(&btnOK);
    KPushButton btnCancel(&msgBox);
    btnCancel.setText("Cancel");
    msgBox.addButton(&btnCancel, KMessageBox::NoRole);
    msgBox.setParent(nullptr);

    //    msgBox.move(this->geometry().center().x() - msgBox.width() / 2,
    //                this->geometry().center().y() - msgBox.height() / 2);
    if(msgBox.exec() == 0)
    {
        QAbstractButton* btn = msgBox.clickedButton();
        if(btn == &btnOK)
        {
            QString input = "ukui-session-tools --" + acttion;
            system(input.toUtf8());
        }
    }
    return 0;
}
int InstructionSet::restart(const std::vector<std::string>& args, int index)
{
    std::cout << "reboot..." << std::endl;
    KMessageBox msgBox(nullptr);
    msgBox.setFixedSize(424,164);
    msgBox.setCustomIcon(QIcon::fromTheme("ukui-dialog-success"));
    msgBox.setWindowTitle("");
    msgBox.setText("Are you sure to restart the computer?");

    KPushButton btnOK(&msgBox);
    btnOK.setBackgroundColorHighlight(true);
    btnOK.setText("Restart");
    msgBox.addButton(&btnOK, KMessageBox::YesRole);
    msgBox.setDefaultButton(&btnOK);
    KPushButton btnCancel(&msgBox);
    btnCancel.setText("Cancel");
    msgBox.addButton(&btnCancel, KMessageBox::NoRole);
    msgBox.setParent(nullptr);

    //    msgBox.move(this->geometry().center().x() - msgBox.width() / 2,
    //                this->geometry().center().y() - msgBox.height() / 2);
    if(msgBox.exec() == 0)
    {
        QAbstractButton* btn = msgBox.clickedButton();
        if(btn == &btnOK)
        {
            system("ukui-session-tools --reboot");
        }
    }
    return 0;
}

int InstructionSet::pauseSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);

    std::cout << "暂停" << "  [待执行]" << std::endl;

    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::pause(const std::vector<std::string>& args, int index)
{
    dbusClient->pauseMusic();
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已暂停" << std::endl;
    }
    else
    {
        std::cout << "暂停" << "  [已完成]" << std::endl;
    }

    return RE_SUCCESS;
}

std::unordered_map<std::string, std::string> playMap = {
    {"music", "音乐"},
    {"vedio", "视频"},
    {"previous", "上一首"},
    {"next", "下一首"}
};
int InstructionSet::playSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    if(args.size()>1)
    {
        std::string input = args[1];
        std::cout << "播放" << playMap[input] << "  [待执行]" << std::endl;

    }
    else
    {
        std::cout << "播放" << playMap["music"] << "  [待执行]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::play(const std::vector<std::string>& args, int index)
{
    if(args.size()>1)
    {
        std::string input = args[1];
        // 定义一个 unordered_map，映射字符串到 lambda 函数
        std::unordered_map<std::string, std::function<void()>> cases = {
        {"previous", []() { dbusClient->playMusicPrevious();;}},
        {"next", []() {dbusClient->playMusicNext();}},
        {"music", []() {dbusClient->playMusic();}},
                // 可以添加更多的case
    };

        // 查找输入字符串对应的函数并执行
        auto it = cases.find(input);
        if (it != cases.end()) {
            it->second();  // 执行找到的函数
        } else {
            std::cout << "没有找到匹配的case" << std::endl;
            dbusClient->playMusic();
        }
    }
    else
    {
        dbusClient->playMusic();
    }
    printIndex(index);
    if(args.size()>1)
    {
        std::string input = args[1];
        if(index == -1)
        {
            std::cout << "正在播放" << playMap[input] << std::endl;
        }
        else
        {
            std::cout << "播放" << playMap[input] << "  [已完成]" << std::endl;
        }

    }
    else
    {
        if(index == -1)
        {
            std::cout << "播放音乐" << std::endl;
        }
        else
        {
            std::cout << "播放音乐" << "  [已完成]" << std::endl;
        }
    }
    return RE_SUCCESS;
}
int InstructionSet::rag(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经将文件添加到本地知识库" << std::endl;
    }
    else
    {
        std::cout << "将文件添加到本地知识库" << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}
int InstructionSet::ragSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    std::cout << "将文件添加到本地知识库" << "  [待执行]" << std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}

int InstructionSet::raiseSkip(const std::vector<std::string>& args, int index)
{

    return RE_SUCCESS;
}
int InstructionSet::raise(const std::vector<std::string>& args, int index)
{

    return RE_SUCCESS;
}
int InstructionSet::saveFileSkip(const std::vector<std::string>& args, int index)
{
    std::cout << "exec: saveFile" << std::endl;
    return RE_SUCCESS;
}

int InstructionSet::saveFile(const std::vector<std::string>& args, int index)
{
    std::cout << "exec: saveFile" << std::endl;
    return RE_SUCCESS;
}

std::unordered_map<std::string, std::string> fixedOutMap = {
    {"setDark", "将系统设置为深色模式  [待执行]"},
    {"vedio", "视频"},
    {"previous", "上一首"},
    {"next", "下一首"}
};

void InstructionSet::fixPrint(std::string &name, int index)
{
    printIndex(index);
    std::cout << fixedOutMap[name] << std::endl;
    checkIfEnd(tasks->size(), index);
}
int InstructionSet::setDarkModeSkip(const std::string &para, int index)
{
    printIndex(index);
    std::cout << "将系统设置为深色模式" << "  [待执行]" << std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::setDarkMode(const std::string &para, int index)
{
    system("gsettings set org.ukui.style style-name ukui-dark");
    std::cout << para << std::endl;
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经将系统设置为深色模式" << std::endl;
    }
    else
    {
        std::cout << "将系统设置为深色模式" << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}

int InstructionSet::setMouseSize(const std::string &para, int index)
{
    std::string size = "";
    if(para == "small"){
        system("gsettings set org.ukui.peripherals-mouse cursor-size 24");
        size = "小";
    }else if(para == "medium"){
        system("gsettings set org.ukui.peripherals-mouse cursor-size 36");
        size = "中";
    }else{
        system("gsettings set org.ukui.peripherals-mouse cursor-size 48");
        size = "大";
    }
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经设置鼠标指针大小为" << size << std::endl;
    }
    else
    {
        std::cout << "将鼠标指针大小设置为" << size << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}

int InstructionSet::setBrightness(const std::string &para, int index)
{
    std::string level = para;
    if(level == ""){
        level = "50";
    }
    std::string directive = "gsettings set org.ukui.power-manager brightness-ac " + level;
    system(directive.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已将屏幕亮度设置为" << level << "%" << std::endl;
    }
    else
    {
        std::cout << "将屏幕亮度设置为" << level << "%" << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}

int InstructionSet::setPowerschemeonac(const std::string &para, int index)
{
    std::string scheme = para;
    std::string directive = "gsettings set org.ukui.power-manager power-policy-ac " + scheme;
    system(directive.c_str());
    printIndex(index);
    if(scheme == "0"){
        scheme = "最佳性能";
    }else if(scheme == "1"){
        scheme = "平衡";
    }else{
        scheme = "最佳能效";
    }
    if(index == -1)
    {
        std::cout << "已将使用电源时电源策略设置为" << scheme << std::endl;
    }
    else
    {
        std::cout << "将使用电源时电源策略设置为" << scheme << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}

int InstructionSet::setPowerschemeonbattery(const std::string &para, int index)
{
    std::string scheme = para;
    std::string directive = "gsettings set org.ukui.power-manager power-policy-battery " + scheme;
    system(directive.c_str());
    printIndex(index);
    if(scheme == "0"){
        scheme = "最佳性能";
    }else if(scheme == "1"){
        scheme = "平衡";
    }else{
        scheme = "最佳能效";
    }
    if(index == -1)
    {
        std::cout << "已将使用电池时电源策略设置为" << scheme << std::endl;
    }
    else
    {
        std::cout << "将使用电池时电源策略设置为" << scheme << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}

int InstructionSet::setCalendar(const std::string &para, int index)
{
    std::string type = para;
    std::string directive = "gsettings set org.ukui.control-center.panel.plugins calendar " + type;
    system(directive.c_str());
    printIndex(index);
    if(type == "lunar"){
        type = "农历";
    }else{
        type = "公历";
    }
    if(index == -1)
    {
        std::cout << "已将日历格式设置为" << type << std::endl;
    }
    else
    {
        std::cout << "将日历格式设置为" << type << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}

int InstructionSet::setFirstday(const std::string &para, int index)
{
    std::string day = para;
    std::string directive = "gsettings set org.ukui.control-center.panel.plugins firstday " + day;
    system(directive.c_str());
    printIndex(index);
    if(day == "sunday"){
        day = "星期天";
    }else{
        day = "星期一";
    }
    if(index == -1)
    {
        std::cout << "已将一周的第一天设置为" << day << std::endl;
    }
    else
    {
        std::cout << "将一周的第一天设置为" << day << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}
int InstructionSet::setDatetype(const std::string &para, int index)
{
    std::string format = para;
    std::string directive = "gsettings set org.ukui.control-center.panel.plugins date " + format;
    system(directive.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已将日期格式设置为" << format << std::endl;
    }
    else
    {
        std::cout << "将日期格式设置为" << format << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}

int InstructionSet::setTimeformat(const std::string &para, int index)
{
    std::string format = para;
    std::string directive = "gsettings set org.ukui.control-center.panel.plugins hoursystem " + format;
    system(directive.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已将时间格式设置为" << format << std::endl;
    }
    else
    {
        std::cout << "将时间格式设置为" << format << "  [已完成]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return RE_SUCCESS;
}


int InstructionSet::setLightModeSkip(const std::string &para, int index)
{
    printIndex(index);
    std::cout << "将系统设置为浅色模式" << "  [待执行]" << std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::setLightMode(const std::string &para, int index)
{
    system("gsettings set org.ukui.style style-name ukui-light");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经将系统设置为浅色模式" << std::endl;
    }
    else
    {
        std::cout << "将系统设置为浅色模式" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

std::unordered_map<std::string, std::string> languageMap = {
    {"en_US", "英语"},
    {"zh_CN", "简体中文"},
    {"mn_MN", "蒙古语"}
};
int InstructionSet::setLanguageSkip(const std::string &para, int index)
{
    printIndex(index);
    std::cout << "将系统语言设置为" << languageMap[para] << "  [待执行]" << std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::setLanguage(const std::string &para, int index)
{

    dbusClient->setLanguage(QString::fromStdString(para));
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经将系统语言设置为" << languageMap[para] << ", 需要重启后生效"<< std::endl;
    }
    else
    {
        std::cout << "将系统语言设置为" << languageMap[para] << "  [已完成，需要重启后生效]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    sessionTools("reboot", "修改系统语言需要重启后生效，是否重启？");
    return RE_SUCCESS;
}
int InstructionSet::setBackgroundSkip(const std::string &para, int index)
{
    printIndex(index);
    std::cout << "将图片设置为桌面背景" << "  [待执行]" << std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::setBackground(const std::string &para, int index)
{
    std::string input = "gsettings set org.mate.background picture-filename /home/ok/桌面/picture/p1.png";
    if(!para.empty())
    {
        input = "gsettings set org.mate.background picture-filename " + para;
    }
    system(input.c_str());
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经将图片设置为桌面背景" << std::endl;
    }
    else
    {
        std::cout << "将图片设置为桌面背景" << "  [已完成]" << std::endl;
    }

    return RE_SUCCESS;
}
int InstructionSet::setSkip(const std::vector<std::string>& args, int index)
{
    std::string key = args[1];
    std::string value;
    if(args.size() > 2)
    {
        value = args[2];
    }


    // 查找并执行对应的操作
    auto it = setSkipActions.find(key);
    if (it != setSkipActions.end()) {
        // 使用std::bind来绑定this指针
        std::function<void(const std::string&, int)> func =
                std::bind(it->second, this, std::placeholders::_1, std::placeholders::_2);
        func(value, index);


    } else {
        std::cout << "执行默认操作" << std::endl;
    }
    return RE_SUCCESS;
}

int InstructionSet::set(const std::vector<std::string>& args, int index)
{
    std::string key = args[1];
    std::string value;
    if(args.size() > 2)
    {
        value = args[2];
    }
    std::cout << value << std::endl;
    std::cout << "exec: "<< args[0] << " " << key << " "<< value << std::endl;

    // 查找并执行对应的操作
    auto it = setActions.find(key);
    if (it != setActions.end()) {
        // 使用std::bind来绑定this指针
        std::function<void(const std::string&, int)> func =
                std::bind(it->second, this, std::placeholders::_1, std::placeholders::_2);
        func(value, index);


    } else {
        std::cout << "执行默认操作" << std::endl;
    }



    return RE_SUCCESS;
}
int InstructionSet::screenshotSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    std::cout << "截屏" << "  [待执行]" << std::endl;
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::screenshot(const std::vector<std::string>& args, int index)
{
    dbusClient->mediaKeyDoAction(SCREENSHOT_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "已经截屏" << std::endl;
    }
    else
    {
        std::cout << "截屏" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int InstructionSet::shutdownSkip(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::shutdown(const std::vector<std::string>& args, int index)
{
    KMessageBox msgBox(nullptr);
    msgBox.setFixedSize(424,164);
    msgBox.setCustomIcon(QIcon::fromTheme("ukui-dialog-success"));
    msgBox.setWindowTitle("");
    msgBox.setText("Are you sure to restart the computer?");

    KPushButton btnOK(&msgBox);
    btnOK.setBackgroundColorHighlight(true);
    btnOK.setText("Restart");
    msgBox.addButton(&btnOK, KMessageBox::YesRole);
    msgBox.setDefaultButton(&btnOK);
    KPushButton btnCancel(&msgBox);
    btnCancel.setText("Cancel");
    msgBox.addButton(&btnCancel, KMessageBox::NoRole);
    msgBox.setParent(nullptr);

    //    msgBox.move(this->geometry().center().x() - msgBox.width() / 2,
    //                this->geometry().center().y() - msgBox.height() / 2);
    if(msgBox.exec() == 0)
    {
        QAbstractButton* btn = msgBox.clickedButton();
        if(btn == &btnOK)
        {
            system("ukui-session-tools --shutdown");
        }
    }
    return 0;
}

int InstructionSet::suspendSkip(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::suspend(const std::vector<std::string>& args, int index)
{
    system("ukui-session-tools --supend");
    return 0;
}


std::unordered_map<std::string, std::string> turnMap = {
    {"music", "音乐"},
    {"vedio", "视频"},
    {"previous", "上一首"},
    {"next", "下一首"}
};


int InstructionSet::turnBottomSkip(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::turnBottom(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::turnTopSkip(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::turnTop(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}

int InstructionSet::turnUpSkip(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::turnUp(const std::vector<std::string>& args, int index)
{
    return 0;
}
int InstructionSet::turnDownSkip(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::turnDown(const std::vector<std::string>& args, int index)
{
    return 0;
}
int InstructionSet::waitSkip(const std::vector<std::string>& args, int index)
{
    printIndex(index);
    if(args.size() == 2)
    {
        int time = std::stoi(args[1]);
        if(tasks->size()>1)
        {
            std::cout << "等待" << time << "秒  [待执行]" << std::endl;
        }
    }
    else
    {
        std::cout << "等待 [参数错误，跳过]" << std::endl;
    }
    checkIfEnd(tasks->size(), index);
    return 0;
}
int InstructionSet::wait(const std::vector<std::string>& args, int index)
{
    if(args.size() == 2)
    {
        int time = std::stoi(args[1]);
        if(tasks->size()>1)
        {
            printIndex(index);
            std::cout << "等待" << time << "秒  [正在执行中...]" << std::endl;
        }
        else
        {
            printIndex(-1);
            std::cout << "等待" << time << "秒，单纯的等待好像没有任何意义  [任务未执行]" << std::endl;
        }
        checkIfEnd(tasks->size(), index);
        act->performSkipTasks(tasks, index+1);
        sleep(time);
    }
    else
    {
        if(tasks->size()>1)
        {
            std::cout << index+1 << ".\t";
            std::cout << "等待 [参数错误，跳过]" << std::endl;
        }
        else
        {
            std::cout << "等待 [参数错误，任务未执行]" << std::endl;
        }
    }
    return 0;
}
int InstructionSet::writeContentSkip(const std::vector<std::string>& args, int index)
{
    return RE_SUCCESS;
}
int InstructionSet::writeContent(const std::vector<std::string>& args, int index)
{
    if(args.size() >1 )
    {
        std::ostringstream oss;

        if (!args.empty()) {
            // 将 vector 中的所有元素拼接成一个字符串，以空格为分隔符
            std::copy(args.begin(), args.end() - 1, std::ostream_iterator<std::string>(oss, " "));
            // 添加最后一个元素，避免在句子末尾添加多余的空格
            oss << args.back();
        }
        std::string str = oss.str();
        std::string insideQuotes;

        // 查找第一个引号
        size_t firstQuote = str.find('\"');
        if (firstQuote != std::string::npos) {
            // 查找第二个引号
            size_t secondQuote = str.find('\"', firstQuote + 1);
            if (secondQuote != std::string::npos) {
                // 提取两个引号之间的字符串
                insideQuotes = str.substr(firstQuote + 1, secondQuote - firstQuote - 1);
            }
        }
        std::cout << "exec: write " << insideQuotes << std::endl;
        std::ofstream outFile(curFile);

        // 检查文件是否成功打开
        if (!outFile.is_open()) {
            std::cerr << "无法创建文件" << std::endl;
            return 1;
        }

        // 向文件写入内容
        outFile << insideQuotes << std::endl;

        // 关闭文件
        outFile.close();
        std::cout << "写入文件: "<< insideQuotes << std::endl;
    }
    return RE_SUCCESS;
}

int showMemoryinfo(int index){
    QString memory = dbusClient->Memoryinfo();
    printIndex(index);
    std::cout << "系统内存信息如下：" << memory.toStdString().data();
    return RE_SUCCESS;
}

int openAutologin(int index)
{

    dbusClient->openAutologin();
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开自动登录.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开自动登录" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeAutologin(int index)
{

    dbusClient->closeAutologin();
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭自动登录.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "关闭自动登录" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openPasswordlesslogin(int index)
{

    dbusClient->openPasswordlesslogin();
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在开启免密码登录.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "开启免密码登录" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openNetworktime(int index)
{

    dbusClient->openNetworktime();
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开同步网络时间.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开同步网络时间" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeNetworktime(int index)
{

    dbusClient->closeNetworktime();
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭同步网络时间.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "正在关闭同步网络时间" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closePasswordlesslogin(int index)
{

    dbusClient->closePasswordlesslogin();
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭免密码登录.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "关闭免密码登录" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

std::string EXEC(const char* cmd) {
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


int closeVolume(int index)
{
    EXEC("amixer set Master mute");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在执行静音操作.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "执行静音操作" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeBrightness(int index)
{
    dbusClient->mediaKeyDoAction(BRIGHT_DOWN_KEY);
    dbusClient->mediaKeyDoAction(BRIGHT_DOWN_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在降低屏幕亮度.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "降低屏幕亮度" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openVolume(int index)
{
    EXEC("amixer set Master unmute");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开音量.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开音量" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openMaxVolume(int index)
{
    EXEC("amixer set Master unmute");
    EXEC("amixer set Master 100%");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在设置最高音量.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "设置最高音量" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openMinVolume(int index)
{

    EXEC("amixer set Master 0%");
    EXEC("amixer set Master mute");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在设置最低音量.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "设置最低音量" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openCalculator(int index)
{
    dbusClient->mediaKeyDoAction(CALCULATOR_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开计算器.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开计算器" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openTouchpad(int index)
{
    dbusClient->mediaKeyDoAction(TOUCHPAD_ON_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开触控板.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开触控板" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int closeTouchpad(int index)
{
    dbusClient->mediaKeyDoAction(TOUCHPAD_OFF_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在关闭触控板.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "关闭触控板" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openScreensaver(int index)
{
    dbusClient->mediaKeyDoAction(SCREENSAVER_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开锁屏.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开锁屏" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openFilemanager(int index)
{
    dbusClient->mediaKeyDoAction(FILE_MANAGER_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开文件管理器.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开文件管理器" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openTerminal(int index)
{
//    system("xdotool key ctrl+alt+t")
    dbusClient->mediaKeyDoAction(TERMINAL_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开终端.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开终端" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openSystemmonitor(int index)
{
    dbusClient->mediaKeyDoAction(SYSTEM_MONITOR_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开系统监视器.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开系统监视器" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openGlobalsearch(int index)
{
    dbusClient->mediaKeyDoAction(GLOBAL_SEARCH_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开全局搜索.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开全局搜索" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openUkuisidebar(int index)
{
    dbusClient->mediaKeyDoAction(UKUI_SIDEBAR);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开控制台.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开控制台" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openConnectioneditor(int index)
{
    dbusClient->mediaKeyDoAction(CONNECTION_EDITOR_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开网络连接设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开网络连接设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openSettings(int index)
{
    dbusClient->mediaKeyDoAction(SETTINGS_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openShutdownmanagement(int index)
{
    dbusClient->mediaKeyDoAction(SHUTDOWN_MANAGEMENT_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开关机管理设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开关机管理设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openProjection(int index)
{
    system("xdotool key super+p");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开系统投屏.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开系统投屏" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openUserinfosetting(int index)
{
    system("ukui-control-center -m userinfo &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开账户信息设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开账户信息设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openBiometrricssetting(int index)
{
    system("ukui-control-center -m biometrics &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开登陆选项设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开登陆选项设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openDisplaysetting(int index)
{
    system("ukui-control-center -m display &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开显示器设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开显示器设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openAudiosetting(int index)
{
    system("ukui-control-center -m audio &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开声音设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开声音设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openPowersetting(int index)
{
    system("ukui-control-center -m power &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开电源设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开电源设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openNoticesetting(int index)
{
    system("ukui-control-center -m notice &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开通知设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开通知设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openAboutsetting(int index)
{
    system("ukui-control-center -m about &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开关于设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开关于设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openBluetoothsetting(int index)
{
    system("ukui-control-center -m bluetooth &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开蓝牙设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开蓝牙设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}



int openPrintersetting(int index)
{
    system("ukui-control-center -m printer &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开打印机设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开打印机设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openMousesetting(int index)
{
    system("ukui-control-center -m mouse &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开鼠标设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开鼠标设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openTouchpadsetting(int index)
{
    system("ukui-control-center -m touchpad &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开触控板设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开触控板设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openKeyboardsetting(int index)
{
    system("ukui-control-center -m keyboard &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开键盘设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开键盘设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openShortcutsetting(int index)
{
    system("ukui-control-center -m shortcut &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开快捷键设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开快捷键设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openNetconnectsetting(int index)
{
    system("ukui-control-center -m netconnect &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开有线网络设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开有线网络设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openWlanconnectsetting(int index)
{
    system("ukui-control-center -m wlanconnect &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开无线网络设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开无线网络设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openProxysetting(int index)
{
    system("ukui-control-center -m proxy &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开代理设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开代理设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openVpnsetting(int index)
{
    system("ukui-control-center -m vpn &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开VPN设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开VPN设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openMobilehotspotsetting(int index)
{
    system("ukui-control-center -m mobilehotspot &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开热点设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开热点设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openWallpapersetting(int index)
{
    system("ukui-control-center -m wallpaper &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开背景设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开背景设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openThemesetting(int index)
{
    system("ukui-control-center -m theme &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开主题设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开主题设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openScreenlocksetting(int index)
{
    system("ukui-control-center -m screenlock &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开锁屏设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开锁屏设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}
int openScreensaversetting(int index)
{
    system("ukui-control-center -m screensaver &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开屏保设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开屏保设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}
int openFontssetting(int index)
{
    system("ukui-control-center -m fonts &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开字体设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开字体设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}
int openPanelsetting(int index)
{
    system("ukui-control-center -m panel &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开任务栏设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开任务栏设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}
int openDatesetting(int index)
{
    system("ukui-control-center -m date &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开时间和日期设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开时间和日期设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}
int openAreasetting(int index)
{
    system("ukui-control-center -m area &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开区域语言设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开区域语言设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openUpgradesetting(int index)
{
    system("ukui-control-center -m upgrade &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开更新设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开更新设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openBackupsetting(int index)
{
    system("ukui-control-center -m backup &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开备份还原设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开备份还原设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openDefaultappsetting(int index)
{
    system("ukui-control-center -m defaultapp &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开默认应用设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开默认应用设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openAutostartsetting(int index)
{
    system("ukui-control-center -m autostart &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开自启动设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开自启动设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openSearchsetting(int index)
{
    system("ukui-control-center -m search &");
    sleep(1);
    system("xdotool key ctrl+c");
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在打开全局搜索设置.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "打开全局搜索设置" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openBrightness(int index)
{
    dbusClient->mediaKeyDoAction(BRIGHT_UP_KEY);
    dbusClient->mediaKeyDoAction(BRIGHT_UP_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在增加屏幕亮度.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "增加屏幕亮度" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openMaxBrightness(int index)
{
    for(int i=0;i<=20;i++)
    {
        dbusClient->mediaKeyDoAction(BRIGHT_UP_KEY);
    }
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在设置最高屏幕亮度.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "设置最高屏幕亮度" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openMinBrightness(int index)
{
    for(int i=0;i<=20;i++)
    {
        dbusClient->mediaKeyDoAction(BRIGHT_DOWN_KEY);
    }
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在设置最低屏幕亮度.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "设置最低屏幕亮度" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openVolumeup(int index)
{
    dbusClient->mediaKeyDoAction(VOLUME_UP_KEY);
    dbusClient->mediaKeyDoAction(VOLUME_UP_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在增加音量.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "增加音量" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}


int openVolumedown(int index)
{
    dbusClient->mediaKeyDoAction(VOLUME_DOWN_KEY);
    dbusClient->mediaKeyDoAction(VOLUME_DOWN_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在减少音量.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "减少音量" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openWindowscreenshot(int index)
{
    dbusClient->mediaKeyDoAction(WINDOW_SCREENSHOT_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在窗口截图.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "窗口截图" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openAreascreenshot(int index)
{
    dbusClient->mediaKeyDoAction(AREA_SCREENSHOT_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在区域截图.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "区域截图" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}

int openWindowswitch(int index)
{
    dbusClient->mediaKeyDoAction(WINDOWSWITCH_KEY);
    printIndex(index);
    if(index == -1)
    {
        std::cout << "正在窗口切换.. 请稍候" << std::endl;
    }
    else
    {
        std::cout << "窗口切换" << "  [已完成]" << std::endl;
    }
    return RE_SUCCESS;
}
