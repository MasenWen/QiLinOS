#include "dbusclient.h"
#include "instructionlist.h"
#include "usd_global_define.h"
#include <QDBusReply>
#include <QJsonDocument>
#include <iostream>
#include <unistd.h>
#include <pwd.h>
DBusClient* DBusClient::sInstance = nullptr;
std::mutex DBusClient::sMutex;

DBusClient* DBusClient::getInstance() {
    std::lock_guard<std::mutex> lock(sMutex);
    if (sInstance == nullptr) {
        sInstance = new DBusClient();
    }
    return sInstance;
}
DBusClient::DBusClient()
{
    unsigned int uid = getuid();
    QString objpath = QString("/org/freedesktop/Accounts/User") + QString::number(uid);
    accountUserDbus = new QDBusInterface("org.freedesktop.Accounts",
                                          objpath,
                                          "org.freedesktop.Accounts.User",
                                          QDBusConnection::systemBus());
}

DBusClient::~DBusClient()
{

}
//QDBusMessage message = QDBusMessage::createMethodCall(DBUS_STATUSMANAGER_NAME,
//                                                      DBUS_STATUSMANAGER_PATH,
//                                                      DBUS_STATUSMANAGER_NAME,
//                                                      DBUS_STATUSMANAGER_GET_ROTATION);

//QDBusMessage response = QDBusConnection::sessionBus().call(message);
//if (response.type() == QDBusMessage::ReplyMessage) {
//    if (response.arguments().isEmpty() == false) {
//        QString value = response.arguments().takeFirst().toString();
//        printf("get mode :%s\n", value.toLatin1().data());

//    }
//}

//    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_STATUSMANAGER_NAME,
//                                                          DBUS_STATUSMANAGER_PATH,
//                                                          DBUS_STATUSMANAGER_NAME,
//                                                          DBUS_STATUSMANAGER_GET_MODE);

//    QDBusMessage response = QDBusConnection::sessionBus().call(message);
//    if (response.type() == QDBusMessage::ReplyMessage) {
//        if(response.arguments().isEmpty() == false) {
//            bool value = response.arguments().takeFirst().toBool();
//            if(value)
//            {
//                std::cout << "yes" << std::endl;
//            }
//            else
//            {
//                std::cout << "no" << std::endl;
//            }
//        }
//    }

//    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_STATUSMANAGER_NAME,
//                                                          DBUS_STATUSMANAGER_PATH,
//                                                          DBUS_STATUSMANAGER_NAME,
//                                                          DBUS_STATUSMANAGER_GET_ROTATION);

//    QDBusMessage response = QDBusConnection::sessionBus().call(message);
//    if (response.type() == QDBusMessage::ReplyMessage) {
//        if (response.arguments().isEmpty() == false) {
//            QString value = response.arguments().takeFirst().toString();
//            printf("get mode :%s\n", value.toLatin1().data());

//        }
//    }

//        QDBusMessage message = QDBusMessage::createMethodCall(DBUS_XRANDR_NAME,
//                                                              DBUS_XRANDR_PATH,
//                                                              DBUS_XRANDR_NAME,
//                                                              DBUS_XRANDR_GET_MODE);

//        QDBusMessage response = QDBusConnection::sessionBus().call(message);
//        if (response.type() == QDBusMessage::ReplyMessage) {
//            if(response.arguments().isEmpty() == false) {
//                int mode = response.arguments().takeFirst().toInt();
//                std::cout << "mode: " << mode << std::endl;
//            }
//        }


//        QDBusMessage message = QDBusMessage::createMethodCall(DBUS_XRANDR_NAME,
//                                                              DBUS_XRANDR_PATH,
//                                                              DBUS_XRANDR_NAME,
//                                                              DBUS_XRANDR_GET_SCREEN_PARAM);

//        QDBusMessage response = QDBusConnection::sessionBus().call(message);
//        if (response.type() == QDBusMessage::ReplyMessage) {
//            if(response.arguments().isEmpty() == false) {

//                QStringList screenList;
//                QJsonDocument parser;
//                QVariantList screens = parser.fromJson(response.arguments().takeFirst().toByteArray()).toVariant().toList();;
//                for (const auto& screenInfo : screens) {
//                    const QString& outputName = ((screenInfo.toMap())[("metadata")].toMap())["name"].toString();
//                    screenList << outputName;
//                }
//                // 使用基于范围的for循环遍历QStringList
//                    for (const QString &str : screenList) {
//                        std::cout << str.toStdString() << std::endl;
//                    }
//            }
//        }


//#define DBUS_GM_NAME                    "org.ukui.SettingsDaemon"
//#define DBUS_GM_PATH                    "/org/ukui/SettingsDaemon/GammaManager"
//#define DBUS_GM_INTERFACE               "org.ukui.SettingsDaemon.GammaManager"
//#define DBUS_GM_SCREENCHANGED           "screenBrightnessChanged"

//    mXrandrInterface = new QDBusInterface(DBUS_XRANDR_NAME,DBUS_XRANDR_PATH,DBUS_XRANDR_INTERFACE,QDBusConnection::sessionBus(),this);
//    QDBusReply<QString> reply1 = mXrandrInterface->call(DBUS_XRANDR_GET_MODE, "acutator");
//    int mode = reply1.value().toInt();
//    std::cout << mode << std::endl;

//    QDBusReply<QString> reply2 = mXrandrInterface->call(DBUS_XRANDR_GET_SCREEN_PARAM, "acutator");
//    if (reply2.isValid()) {
//        QStringList screenList;
//        QJsonDocument parser;
//        QVariantList screens = parser.fromJson(reply2.value().toUtf8().data()).toVariant().toList();
//        for (const auto& screenInfo : screens) {
//            const QString& outputName = ((screenInfo.toMap())[("metadata")].toMap())["name"].toString();
//            screenList << outputName;
//        }
//        // 使用基于范围的for循环遍历QStringList
//            for (const QString &str : screenList) {
//                std::cout << str.toStdString() << std::endl;
//            }
//    }


//    mScreenInterface = new QDBusInterface(DBUS_GM_NAME, DBUS_GM_PATH, DBUS_GM_INTERFACE, QDBusConnection::sessionBus(),this);
//    if (!mScreenInterface->isValid()) {
//        mScreenInterface = nullptr;
//        return;
//    }

//    QDBusReply<QString> reply3 = mScreenInterface->call("getPrimaryBrightness");
//    int brightness = reply3.value().toInt();
//    std::cout << brightness << std::endl;

//    QVariantList args;
//    args << "eDP-1" << 10; // 添加任意类型的参数
//    QDBusReply<QString> reply4 = mScreenInterface->call("setScreenBrightness", args);
//    int brightness2 = reply3.value().toInt();
//    std::cout << brightness << std::endl;

//    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_GM_NAME,
//                                                          DBUS_GM_PATH,
//                                                          DBUS_GM_NAME,
//                                                          "getPrimaryBrightness");
//    message << "eDP-1";
//    QDBusMessage response = QDBusConnection::sessionBus().call(message);
//    if (response.type() == QDBusMessage::ReplyMessage) {
//        if (response.arguments().isEmpty() == false) {
//            int mode = response.arguments().takeFirst().toInt();
//            std::cout << "brightness: " << mode << std::endl;
//        }
//    }



//    QDBusReply<QString> reply3 = mScreenInterface->call("getPrimaryBrightness", "acutator");
//    int brightness = reply3.value().toInt();
//    std::cout << brightness << std::endl;
//    DBUS_GM_INTERFACE
//    int GmDbus::setScreenBrightness(QString appName, QString screenName, uint screenBrightness)


//    QDBusMessage notifySignal =
//            QDBusMessage::createSignal(DBUS_GC_BRIGHTNESS_PATH, DBUS_GC_BRIGHTNESS_INTERFACE, DBUS_GC_BRIGHTNESS_SIGNAL_PRIMARYCHANGED_END);
//    notifySignal.setArguments({QVariant::fromValue((uint)100)});
//    QDBusConnection::sessionBus().send(notifySignal);

#define DBUS_MEDIA_KEY_NAME "org.ukui.SettingsDaemon"
#define DBUS_MEDIA_KEY_PATH "/org/ukui/SettingsDaemon/MediaKeys"
#define DBUS_MEDIA_KEY_INTERFACE "org.ukui.SettingsDaemon.MediaKeys"


//dbus name: org.freedesktop.Accounts
//dbus path: /org/freedesktop/Accounts/Userid
//dbus interface: org.freedesktop.Accounts.User
//dbus method: SetLanguage(String Language)

  void DBusClient::setLanguage(const QString &lang)
  {
      QDBusMessage response = accountUserDbus->call("SetLanguage", lang);
      if (response.type() == QDBusMessage::ReplyMessage) {
          std::cout << "nice" << std::endl;
          return ;
      }
//      QDBusMessage message = QDBusMessage::createMethodCall("org.freedesktop.Accounts",
//                                                            "/org/freedesktop/Accounts/Userid",
//                                                            "org.freedesktop.Accounts.User",
//                                                            "SetLanguage");


//      message << QString::fromStdString(lang);
//      QDBusMessage response = QDBusConnection::sessionBus().call(message);
//      if (response.type() == QDBusMessage::ReplyMessage) {
//          std::cout << "nice" << std::endl;
//          return ;
//      }
  }

void DBusClient::mediaKeyDoAction(ActionType ation)
{
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_MEDIA_KEY_NAME,
                                                          DBUS_MEDIA_KEY_PATH,
                                                          DBUS_MEDIA_KEY_INTERFACE,
                                                          "externalDoAction");
    message << ation << "acutator";
    QDBusMessage response = QDBusConnection::sessionBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "nice" << std::endl;
        return ;
    }
}


#define DBUS_MUSIC_NAME "org.ukui.kylin_music"
#define DBUS_MUSIC_PATH "/org/ukui/kylin_music"
#define DBUS_MUSIC_INTERFACE "org.ukui.kylin_music.play"
//#define DBUS_MUSIC_NAME "org.mpris.MediaPlayer2.KylinMusic"
//#define DBUS_MUSIC_PATH "/org/mpris/MediaPlayer2"
//#define DBUS_MUSIC_INTERFACE "org.mpris.MediaPlayer2.KylinMusic"

void DBusClient::playMusic()
{
    openOrCloseApplication("music", true, true);
    system("xdotool key space");
//    sleep(1);
    pauseMusic();
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_MUSIC_NAME,
                                                          DBUS_MUSIC_PATH,
                                                          DBUS_MUSIC_INTERFACE,
                                                          "Play");
//    message << ation << "acutator";
    QDBusMessage response = QDBusConnection::sessionBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "play music" << std::endl;
    }
}
void DBusClient::pauseMusic()
{

    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_MUSIC_NAME,
                                                          DBUS_MUSIC_PATH,
                                                          DBUS_MUSIC_INTERFACE,
                                                          "Pause");
//    message << ation << "acutator";
    QDBusMessage response = QDBusConnection::sessionBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "pause music" << std::endl;

    }
}
void DBusClient::playMusicPrevious()
{

    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_MUSIC_NAME,
                                                          DBUS_MUSIC_PATH,
                                                          DBUS_MUSIC_INTERFACE,
                                                          "Previous");
//    message << ation << "acutator";
    QDBusMessage response = QDBusConnection::sessionBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "play previous" << std::endl;

    }
}
void DBusClient::playMusicNext()
{

    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_MUSIC_NAME,
                                                          DBUS_MUSIC_PATH,
                                                          DBUS_MUSIC_INTERFACE,
                                                          "Next");
//    message << ation << "acutator";
    QDBusMessage response = QDBusConnection::sessionBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "play next" << std::endl;

    }
}

void DBusClient::closeMusic()
{

    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_MUSIC_NAME,
                                                          DBUS_MUSIC_PATH,
                                                          DBUS_MUSIC_INTERFACE,
                                                          "slotClose");
//    message << ation << "acutator";
    QDBusMessage response = QDBusConnection::sessionBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "close music" << std::endl;
        return ;
    }
}
#define DBUS_BLUETOOTH_NAME "org.ukui.bluetooth"
#define DBUS_BLUETOOTH_PATH "/org/ukui/bluetooth/"
#define DBUS_BLUETOOTH_INTERFACE "org.ukui.bluetooth"

void DBusClient::openBluetooth()
{

//    dbus method: setDefaultAdapterAttr(Dict of {String, Variant} arg_1)


    sleep(1);
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_BLUETOOTH_NAME,
                                                          DBUS_BLUETOOTH_PATH,
                                                          DBUS_BLUETOOTH_INTERFACE,
                                                          "setDefaultAdapterAttr");
//    message << ation << "acutator";
    QDBusMessage response = QDBusConnection::sessionBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "play music" << std::endl;

    }
}

#define DBUS_AUTOLOGIN_NAME "org.freedesktop.Accounts"
#define DBUS_AUTOLOGIN_PATH "/org/freedesktop/Accounts/User"
#define DBUS_AUTOLOGIN_INTERFACE "org.freedesktop.Accounts.User"
void DBusClient::openAutologin(){
    unsigned int uid = getuid();
    QString objpath = QString(DBUS_AUTOLOGIN_PATH) + QString::number(uid);
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_AUTOLOGIN_NAME,
                                                        objpath,
                                                        DBUS_AUTOLOGIN_INTERFACE,
                                                        "SetAutomaticLogin");
    message << true;
    QDBusMessage response = QDBusConnection::systemBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "open autologin" << std::endl;
    }
}

void DBusClient::closeAutologin(){
    unsigned int uid = getuid();
    QString objpath = QString(DBUS_AUTOLOGIN_PATH) + QString::number(uid);
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_AUTOLOGIN_NAME,
                                                        objpath,
                                                        DBUS_AUTOLOGIN_INTERFACE,
                                                        "SetAutomaticLogin");
    message << false;
    QDBusMessage response = QDBusConnection::systemBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "close autologin" << std::endl;
    }
}


#define DBUS_PASSWORDLESSLOGIN_NAME "org.ukui.groupmanager"
#define DBUS_PASSWORDLESSLOGIN_PATH "/org/ukui/groupmanager"
#define DBUS_PASSWORDLESSLOGIN_INTERFACE "org.ukui.groupmanager.interface"
void DBusClient::openPasswordlesslogin(){
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_PASSWORDLESSLOGIN_NAME,
                                                        DBUS_PASSWORDLESSLOGIN_PATH,
                                                        DBUS_PASSWORDLESSLOGIN_INTERFACE,
                                                        "setNoPwdLoginStatus");
    struct passwd* pwd;
    pwd = getpwuid( getuid());
    message << true << pwd->pw_name;
    QDBusMessage response = QDBusConnection::systemBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "open passwordlesslogin" << std::endl;
    }
}


void DBusClient::closePasswordlesslogin(){
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_PASSWORDLESSLOGIN_NAME,
                                                        DBUS_PASSWORDLESSLOGIN_PATH,
                                                        DBUS_PASSWORDLESSLOGIN_INTERFACE,
                                                        "setNoPwdLoginStatus");
    struct passwd* pwd;
    pwd = getpwuid(getuid());
    message << false << pwd->pw_name;
    QDBusMessage response = QDBusConnection::systemBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "close passwordlesslogin" << std::endl;
    }
}

#define DBUS_NETWORKTIME_NAME "org.freedesktop.timedate1"
#define DBUS_NETWORKTIME_PATH "/org/freedesktop/timedate1"
#define DBUS_NETWORKTIME_INTERFACE "org.freedesktop.timedate1"
void DBusClient::openNetworktime(){
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_NETWORKTIME_NAME,
                                                        DBUS_NETWORKTIME_PATH,
                                                        DBUS_NETWORKTIME_INTERFACE,
                                                        "SetNtp");
    message << true << true;
    QDBusMessage response = QDBusConnection::systemBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "open networktime" << std::endl;
    }
}

void DBusClient::closeNetworktime(){
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_NETWORKTIME_NAME,
                                                        DBUS_NETWORKTIME_PATH,
                                                        DBUS_NETWORKTIME_INTERFACE,
                                                        "SetNtp");
    message << false << true;
    QDBusMessage response = QDBusConnection::systemBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        std::cout << "open networktime" << std::endl;
    }
}


#define DBUS_MEMORYINFO_NAME "com.control.center.qt.systemdbus"
#define DBUS_MEMORYINFO_PATH "/"
#define DBUS_MEMORYINFO_INTERFACE "com.control.center.interface"
QString DBusClient::Memoryinfo()
{
    sleep(1);
    QDBusMessage message = QDBusMessage::createMethodCall(DBUS_MEMORYINFO_NAME,
                                                          DBUS_MEMORYINFO_PATH,
                                                          DBUS_MEMORYINFO_INTERFACE,
                                                          "getMemory");
    QDBusMessage response = QDBusConnection::systemBus().call(message);
    if (response.type() == QDBusMessage::ReplyMessage) {
        const auto &args = response.arguments();
        if (!args.isEmpty()) {
            QString memory = args.at(0).toString();
            return memory;
        } else {
            return "系统内存信息不存在";
        }
    } else {
        return "获取系统内存信息失败";
    }

}
