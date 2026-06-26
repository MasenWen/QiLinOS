
#include <QString>
#include <QUrl>
#include <QDebug>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <QFile>
#include <QThread>
#include <QDir>
#include <QCoreApplication>
#include <sys/syslog.h>

#include <iostream>
#include <regex>
#include <string>
#include "actuator.h"
#include "instructionset.h"


void outLog(QString str)
{
    str.prepend(QString("Actuator: "));
    syslog(LOG_INFO, "%s\n", str.toStdString().c_str());
}

Actuator::Actuator()
{
    instructionSet = InstructionSet::getInstance();
}

Actuator::~Actuator()
{

}
int Actuator::executeSkipCommand(std::vector<std::string> *tasks, int index)
{
    int actIndex = 0;
    if(index>0)
    {
        actIndex = index;
    }
    std::string input = tasks->at(actIndex);
    //    std::vector<std::string> tokens; // 存储解析后的指令和参数

    //    // 使用空格分隔指令和参数
    //    size_t pos = 0;
    //    std::string delimiter = " ";
    //    while ((pos = input.find(delimiter)) != std::string::npos) {
    //        std::string token = input.substr(0, pos);
    //        tokens.push_back(token);
    //        input.erase(0, pos + delimiter.length());
    //    }
    //    tokens.push_back(input); // 将剩下的部分作为最后一个参数
    std::vector<std::string> tokens;
    std::string temp;
    bool insideQuotes = false;

    for (char c : input) {
        if (c == '"') {
            insideQuotes = !insideQuotes;
        } else if (c == ' ' && !insideQuotes) {
            if (!temp.empty()) {
                //                if(c == '"')
                //                {
                //                    tokens.push_back("\""+temp+"\"");
                //                }
                //                else
                //                {
                tokens.push_back(temp);
                //                }
                temp.clear();
            }
        } else {
            temp += c;
        }
    }

    // 处理最后一个单词
    if (!temp.empty()) {
        tokens.push_back(temp);
    }

    // 获取第一个token作为指令名
    std::string name = tokens[0];

    // 准备第二个参数，如果tokens只有一个元素，则传递空数组
    std::vector<std::string> args;

    args = std::vector<std::string>(tokens.begin(), tokens.end());


    // 执行指令const std::string& name, bool &skip, const std::vector<std::string>& args, const std::vector<std::string>& tasks, int index
    return instructionSet->executeSkipInstruction(index, name, args);

}
int Actuator::executeCommand(std::vector<std::string> *tasks, int index)
{
    int actIndex = 0;
    if(index>0)
    {
        actIndex = index;
    }
    std::string input = tasks->at(actIndex);
    //    std::vector<std::string> tokens; // 存储解析后的指令和参数

    //    // 使用空格分隔指令和参数
    //    size_t pos = 0;
    //    std::string delimiter = " ";
    //    while ((pos = input.find(delimiter)) != std::string::npos) {
    //        std::string token = input.substr(0, pos);
    //        tokens.push_back(token);
    //        input.erase(0, pos + delimiter.length());
    //    }
    //    tokens.push_back(input); // 将剩下的部分作为最后一个参数

    std::vector<std::string> tokens;
    std::string temp;
    bool insideQuotes = false;

    for (char c : input) {
        if (c == '"') {
            insideQuotes = !insideQuotes;
        } else if (c == ' ' && !insideQuotes) {
            if (!temp.empty()) {
//                if(c == '"')
//                {
//                    tokens.push_back("\""+temp+"\"");
//                }
//                else
//                {
                tokens.push_back(temp);
//                }
                temp.clear();
            }
        } else {
            temp += c;
        }
    }

    // 处理最后一个单词
    if (!temp.empty()) {
        tokens.push_back(temp);
    }

    // 获取第一个token作为指令名
    std::string name = tokens[0];

    // 准备第二个参数，如果tokens只有一个元素，则传递空数组
    std::vector<std::string> args;

    args = std::vector<std::string>(tokens.begin(), tokens.end());


    // 执行指令const std::string& name, bool &skip, const std::vector<std::string>& args, const std::vector<std::string>& tasks, int index
    return instructionSet->executeInstruction(index, name, args);

}
int Actuator::performSkipTasks(std::vector<std::string> *tasks, int index)
{
    int status = 0;
    if(tasks->size() == 1)
    {
        status = executeSkipCommand(tasks, -1);
    }
    else
    {
        for (size_t i = index; i < tasks->size(); ++i) {

            int rCode = executeSkipCommand(tasks, i);
            if(rCode != 0)
            {
                status = rCode;
            }
        }
    }
    return status;
}
int Actuator::performTasks(std::string tasks)
{
    std::regex pattern(R"(\{([^}]+)\})");


    std::vector<std::string> matchedStrings;
    std::sregex_iterator it(tasks.begin(), tasks.end(), pattern);
    std::sregex_iterator end;
    int status = 0;
    while (it != end) {
        //        std::cout << "匹配到的字符串: " << it->str(1) << std::endl;
        matchedStrings.push_back(it->str(1));

        ++it;
    }

    instructionSet->initTaskEnv(this, &matchedStrings);
    if(matchedStrings.size()>1)
    {
//        std::cout << "<AI>好的，" << std::endl;
    }
    if(matchedStrings.size() == 1)
    {
        status = executeCommand(&matchedStrings, -1);
    }
    else
    {
        for (size_t i = 0; i < matchedStrings.size(); ++i) {

            int rCode = executeCommand(&matchedStrings, i);
            if(rCode != 0)
            {
                status = rCode;
            }
        }
    }
    return status;
}

int Actuator::perform_tasks(QString input)
{
    std::string tasks = input.toStdString(); // 将QString转换为std::string
    return performTasks(tasks);
}
QString Actuator::test(QString input)
{
    return "hello, this is a reply2";
}


