#ifndef LINKDIALOG_H
#define LINKDIALOG_H

#include <QWidget>
#include <QListWidget>


class LinkDialog : public QWidget
{
    Q_OBJECT

public:
    static LinkDialog* getInstance(QWidget *parent = nullptr);
    void addLink(const QString link);
    ~LinkDialog();

private:
    explicit LinkDialog(QWidget *parent = nullptr);
    static LinkDialog* m_instance;

private slots:
    void openLink(QListWidgetItem *item);

private:
    QListWidget *listWidget;
};

#endif // LINKDIALOG_H
