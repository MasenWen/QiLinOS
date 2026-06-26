#ifndef Actuator_H
#define Actuator_H

#include <QObject>
#include <QProcess>

void outLog(QString str);
class InstructionSet;
class Actuator : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "com.kylin.actuator")
private:
   InstructionSet* instructionSet;

public:
    Actuator();
    ~Actuator();
    int executeSkipCommand(std::vector<std::string> *tasks, int index);
    int executeCommand(std::vector<std::string> *tasks, int index);
    int performSkipTasks(std::vector<std::string> *tasks, int index);
    int performTasks(std::string tasks);
Q_SIGNALS:

    void sigProgressValue(int);



public Q_SLOTS:
    int perform_tasks(QString input);
    QString test(QString input);

};

#endif  // !Actuator_H
