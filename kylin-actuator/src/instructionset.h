#ifndef INSTRUCTION_SET_H
#define INSTRUCTION_SET_H

#include <string>
#include <unordered_map>
#include <functional>
#include <vector>
#include <mutex>

#include "actuator.h"

// 定义指令执行函数类型，接受std::vector<std::string>参数
//using InstructionFunction = std::function<int(Actuator*, const std::vector<std::string>&, const std::vector<std::string>&,  int, bool)>;
using openSingleFunc = std::function<int(int)>;
// InstructionSet类，实现单例模式
class InstructionSet {
private:
    Actuator *act;
    std::vector<std::string> *tasks;
    std::string pwdPath;
    std::string curFile;
    //    std::unordered_map<std::string, InstructionFunction> mInstructions;
    std::unordered_map<std::string, int (InstructionSet::*)(const std::vector<std::string>&, int)> doActions;
    std::unordered_map<std::string, int (InstructionSet::*)(const std::vector<std::string>&, int)> skipActions;
    std::unordered_map<std::string, int (InstructionSet::*)(const std::string&, int)> setActions;
    std::unordered_map<std::string, int (InstructionSet::*)(const std::string&, int)> setSkipActions;
    static InstructionSet* sInstance; // 单例实例指针
    static std::mutex sMutex;

    void initializeActions();
    InstructionSet(); // 私有构造函数，防止外部创建实例
    InstructionSet(const InstructionSet&) = delete;
    InstructionSet& operator=(const InstructionSet&) = delete;


    void fixPrint(std::string &name, int index);

    int defaultExec(const std::vector<std::string>& args, int index);
    int bye(const std::vector<std::string>& args, int index);
    int cd(const std::vector<std::string>& args, int index);
    int closeAny(const std::vector<std::string>& args, int index);
    int create(const std::vector<std::string>& args, int index);
    int disc(const std::vector<std::string>& args, int index);
    int find(const std::vector<std::string>& args, int index);
    int hibernate(const std::vector<std::string>& args, int index);
    int mailto(const std::vector<std::string>& args, int index);
    int makepic(const std::vector<std::string>& args, int index);
    int mute(const std::vector<std::string>& args, int index);
    int none(const std::vector<std::string>& args, int index);
    int openAny(const std::vector<std::string>& args, int index);
    int showAny(const std::vector<std::string>& args, int index);
    int emptyAny(const std::vector<std::string>& args, int index);
    int doAny(const std::vector<std::string>& args, int index);
    int search(const std::vector<std::string>& args,int index);
    int restart(const std::vector<std::string>& args, int index);
    int pause(const std::vector<std::string>& args, int index);
    int play(const std::vector<std::string>& args, int index);
    int rag(const std::vector<std::string>& args, int index);
    int raise(const std::vector<std::string>& args, int index);
    int saveFile(const std::vector<std::string>& args, int index);
    int setDarkMode(const std::string &para, int index);
    int setMouseSize(const std::string &para, int index);
    int setBrightness(const std::string &para, int index);
    int setPowerschemeonac(const std::string &para, int index);
    int setPowerschemeonbattery(const std::string &para, int index);
    int setCalendar(const std::string &para, int index);
    int setFirstday(const std::string &para, int index);
    int setDatetype(const std::string &para, int index);
    int setTimeformat(const std::string &para, int index);
    int setLightMode(const std::string &para, int index);
    int setLanguage(const std::string &para, int index);
    int setBackground(const std::string &para, int index);
    int set(const std::vector<std::string>& args, int index);
    int screenshot(const std::vector<std::string>& args, int index);
    int shutdown(const std::vector<std::string>& args, int index);
    int suspend(const std::vector<std::string>& args, int index);
    int turnBottom(const std::vector<std::string>& args, int index);
    int turnTop(const std::vector<std::string>& args, int index);
    int turnUp(const std::vector<std::string>& args, int index);
    int turnDown(const std::vector<std::string>& args, int index);
    int wait(const std::vector<std::string>& args, int index);
    int writeContent(const std::vector<std::string>& args, int index);


    int defaultExecSkip(const std::vector<std::string>& args, int index);
    int cdSkip(const std::vector<std::string>& args, int index);
    int closeAnySkip(const std::vector<std::string>& args, int index);
    int createSkip(const std::vector<std::string>& args, int index);
    int discSkip(const std::vector<std::string>& args, int index);
    int findSkip(const std::vector<std::string>& args, int index);
    int hibernateSkip(const std::vector<std::string>& args, int index);
    int mailtoSkip(const std::vector<std::string>& args, int index);
    int makepicSkip(const std::vector<std::string>& args, int index);
    int muteSkip(const std::vector<std::string>& args, int index);
    int openAnySkip(const std::vector<std::string>& args, int index);
    int restartSkip(const std::vector<std::string>& args, int index);
    int pauseSkip(const std::vector<std::string>& args, int index);
    int playSkip(const std::vector<std::string>& args, int index);
    int ragSkip(const std::vector<std::string>& args, int index);
    int raiseSkip(const std::vector<std::string>& args, int index);
    int saveFileSkip(const std::vector<std::string>& args, int index);
    int setDarkModeSkip(const std::string &para, int index);
    int setLightModeSkip(const std::string &para, int index);
    int setLanguageSkip(const std::string &para, int index);
    int setBackgroundSkip(const std::string &para, int index);
    int setSkip(const std::vector<std::string>& args, int index);
    int screenshotSkip(const std::vector<std::string>& args, int index);
    int shutdownSkip(const std::vector<std::string>& args, int index);
    int suspendSkip(const std::vector<std::string>& args, int index);
    int turnBottomSkip(const std::vector<std::string>& args, int index);
    int turnTopSkip(const std::vector<std::string>& args, int index);
    int turnUpSkip(const std::vector<std::string>& args, int index);
    int turnDownSkip(const std::vector<std::string>& args, int index);
    int waitSkip(const std::vector<std::string>& args, int index);
    int writeContentSkip(const std::vector<std::string>& args, int index);

public:
    static InstructionSet* getInstance(); // 获取单例实例

    //    void addInstruction(const std::string& name, const InstructionFunction& function); // 添加指令
    //    bool hasInstruction(const std::string& name) const; // 检查指令是否存在
    //    int executeInstruction(const std::string& name, const std::vector<std::string>& args = {}); // 执行指令
    void initTaskEnv(Actuator *tAct, std::vector<std::string> *tTasks);
    int executeInstruction(int index, const std::string& name, const std::vector<std::string>& args = {});
    int executeSkipInstruction(int index, const std::string& name, const std::vector<std::string>& args = {});
    static void deleteInstance(); // 删除实例
};

#endif // INSTRUCTION_SET_H
