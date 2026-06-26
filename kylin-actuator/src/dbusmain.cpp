//#include <QCoreApplication>
//#include <QDBusConnection>
//#include <QDBusError>
//#include <QDebug>

//#include "actuator.h"

//int main(int argc, char *argv[])
//{
//    QCoreApplication app(argc, argv);
//    app.setOrganizationName("kylin Actuator");
//    app.setApplicationName("kylin Actuator");

//    QDBusConnection systemBus = QDBusConnection::systemBus();
//    if (!systemBus.isConnected()) {
//        outLog("d-bus connection fail !");
//        printf("d-bus connection fail !");
//        return -1;
//    }

//    if (!systemBus.registerService("com.kylin.actuator")) {
//        outLog(QString("d-bus register service fail ! d-bus error : ") +
//               QDBusError::errorString(systemBus.lastError().type()));
//        printf("d-bus register service fail ! d-bus error!");
//        return -1;
//    }

//    if (!systemBus.registerObject("/", new Actuator,
//                                  QDBusConnection::ExportAllSlots | QDBusConnection::ExportAllSignals)) {
//        outLog(QString("d-bus register object fail ! d-bus error : ") +
//               QDBusError::errorString(systemBus.lastError().type()));
//        printf("d-bus register object fail ! d-bus error !");
//        return -1;
//    }

//    return app.exec();
//}
