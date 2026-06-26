 #include <QApplication>
#include <unistd.h>
#include <cstdio>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <set>
#include <filesystem>

#include <qdir.h>
#include <kpushbutton.h>
#include <kaboutdialog.h>
#include <qapplication.h>
#include <kmessagebox.h>

//#include "instructionset.h"
//#include "dbusclient.h"

//#include "usd_global_define.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <QTextStream>
#include "actuator.h"
#include <filesystem>

namespace fs = std::filesystem;
#include "pubdef.h"
//using namespace kdk;
//namespace fs = std::filesystem;

//InstructionSet* instructionSet = InstructionSet::getInstance();




//int executeCommand(std::string cmd)
//{
//    std::string input = cmd; // 要解析的指令
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



//    // 获取第一个token作为指令名
//    std::string name = tokens[0];

//    // 准备第二个参数，如果tokens只有一个元素，则传递空数组
//    std::vector<std::string> args;
//    if (tokens.size() > 1) {
//        args = std::vector<std::string>(tokens.begin() + 1, tokens.end());
//    }

//    // 执行指令
//    return instructionSet->executeInstruction(name, args);

//}

int main(int argc, char *argv[])
{

    setbuf(stdout, NULL);
#if (QT_VERSION >= QT_VERSION_CHECK(5, 6, 0))
    QApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
    QApplication::setAttribute(Qt::AA_UseHighDpiPixmaps);
#endif

#if (QT_VERSION >= QT_VERSION_CHECK(5, 14, 0))
    QApplication::setHighDpiScaleFactorRoundingPolicy(Qt::HighDpiScaleFactorRoundingPolicy::PassThrough);
#endif

    QApplication app(argc, argv);
    app.setApplicationName(QApplication::tr("Actuator"));
    app.setApplicationVersion("1.0.0-ok1");

    std::string content;
    if (argc > 1) { // 检查是否有足够的参数
        std::string filePath = argv[1]; // 获取第一个参数作为文件路径
        if (fs::exists(filePath) && fs::is_regular_file(filePath)) { // 检查文件是否存在并且是一个常规文件
            std::ifstream file(filePath);
            if (file.is_open()) {
                content = std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
                file.close();
            }
            else
            {
                std::cerr << "Failed to open file: " << filePath << std::endl;
                return 1;
            }
        }
        else
        {
            content = argv[1];
            std::cerr << "read content directly" << filePath << std::endl;
        }
    }
    else
    {


        //    executeCommand("{open 浏览器}{restart}");
        // 检查是否有足够的命令行参数


        QString path = QDir::homePath() + "/.kylin-actuator/input";
        std::string stdPath = path.toStdString();
        // 读取文件内容到QString
        std::ifstream inputFile(stdPath);
        if (!inputFile.is_open()) {
            std::cerr << "Unable to open file for reading." << std::endl;
            return 1;
        }

        content = std::string((std::istreambuf_iterator<char>(inputFile)),
                               std::istreambuf_iterator<char>());

        inputFile.close();
    }
    //     清空文件内容
    //    std::ofstream outputFile(stdPath, std::ofstream::out | std::ofstream::trunc);
    //    if (!outputFile.is_open()) {
    //        std::cerr << "Unable to open file for writing." << std::endl;
    //        return 1;
    //    }
    //    outputFile.close();
    Actuator act;
    //    int status = act.performTasks("{set dark}{screenshot}{set language mn}{set background /home/ok/图片/196736458_0_final.png}{open music}{play}{wait 30}{pause}");
    int status = act.performTasks(content);

    if(gWaitUser)
    {
        return app.exec();
    }
    else
    {
        return status;
    }
}



