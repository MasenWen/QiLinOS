#ifndef SYSTEM_SET_H
#define SYSTEM_SET_H


#include <string>
#include <mutex>

#include <QObject>
#include <QDBusInterface>
#include <QGSettings/qgsettings.h>

typedef enum {
    TOUCHPAD_KEY,
    MUTE_KEY,
    VOLUME_DOWN_KEY,
    VOLUME_UP_KEY,
    MIC_MUTE_KEY,
    BRIGHT_UP_KEY,
    BRIGHT_DOWN_KEY,
    POWER_DOWN_KEY,
    POWER_OFF_KEY,
    EJECT_KEY,
    HOME_KEY,
    MEDIA_KEY,
    CALCULATOR_KEY,
    EMAIL_KEY,
    SCREENSAVER_KEY,
    HELP_KEY,
    WWW_KEY,
    PLAY_KEY,
    PAUSE_KEY,
    STOP_KEY,
    PREVIOUS_KEY,
    NEXT_KEY,
    REWIND_KEY,
    FORWARD_KEY,
    REPEAT_KEY,
    CURSOR_PROMPT_KEY,
    RANDOM_KEY,
    SETTINGS_KEY,
    FILE_MANAGER_KEY,
    SHUTDOWN_MANAGEMENT_KEY,
    TERMINAL_KEY,
    SCREENSHOT_KEY,
    WINDOW_SCREENSHOT_KEY,
    AREA_SCREENSHOT_KEY,
    WINDOWSWITCH_KEY,
    SYSTEM_MONITOR_KEY,
    CONNECTION_EDITOR_KEY,
    GLOBAL_SEARCH_KEY,
    KDS_KEY,
    WLAN_KEY,
    WEBCAM_KEY,
    HANDLED_KEYS,
    UKUI_SIDEBAR,
    UKUI_EYECARE_CENTER,
    TOUCHPAD_ON_KEY,
    TOUCHPAD_OFF_KEY,
    RFKILL_KEY,
    BLUETOOTH_KEY,
    ASRASSISTANT,
    PERFORMANCE_KEY,
} ActionType;

class DBusClient : public QObject {
private:
    static DBusClient* sInstance;
    static std::mutex sMutex;
    QDBusInterface *accountUserDbus = nullptr;
    //    QGSettings *mXsettings;
    //    QDBusInterface *mDbusInterface = nullptr;
    //    QDBusInterface *mDbusInterfaceSessionManager = nullptr;
    //    QDBusInterface *mXrandrInterface = nullptr;
    //    QDBusInterface *mScreenInterface = nullptr;
    //    QDBusInterface *mMediaKeyInterface = nullptr;


    DBusClient();
    ~DBusClient();
    DBusClient(const DBusClient&) = delete;
    DBusClient& operator=(const DBusClient&) = delete;

public:
    void setLanguage(const QString &lang);
    void openNetwork();
    void mediaKeyDoAction(ActionType ation);
    void playMusic();
    void pauseMusic();
    void openBluetooth();
    void playMusicPrevious();
    void playMusicNext();
    void closeMusic();
    QString Memoryinfo();
    void openAutologin();
    void closeAutologin();
    void openPasswordlesslogin();
    void closePasswordlesslogin();
    void openNetworktime();
    void closeNetworktime();
    static DBusClient* getInstance();

};

#endif // SYSTEM_SET_H
