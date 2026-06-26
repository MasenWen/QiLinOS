

#include "linkdialog.h"
#include <QVBoxLayout>
#include <QListWidgetItem>
#include <QDesktopServices>
#include <QUrl>
#include <iostream>
#include "pubdef.h"
LinkDialog* LinkDialog::m_instance = nullptr;

LinkDialog::LinkDialog(QWidget *parent) : QWidget(parent)
{
    gWaitUser = true;
//    setAttribute(Qt::WA_DeleteOnClose, false); // 关闭时不要删除窗口
    setWindowFlags(windowFlags() | Qt::WindowStaysOnTopHint); // 设置窗口置顶
    setWindowTitle("文件查找结果");
    setFixedSize(560,640);
    listWidget = new QListWidget(this);

    QVBoxLayout *layout = new QVBoxLayout(this);
    layout->addWidget(listWidget);

    connect(listWidget, &QListWidget::itemClicked, this, &LinkDialog::openLink);

}

LinkDialog* LinkDialog::getInstance(QWidget *parent)
{
    if (!m_instance) {
        m_instance = new LinkDialog(parent);
    }
    return m_instance;
}


void LinkDialog::addLink(const QString link)
{
    listWidget->addItem(link); // 向列表中添加新链接
}

LinkDialog::~LinkDialog()
{
    m_instance = nullptr;
}

void LinkDialog::openLink(QListWidgetItem *item)
{
//    std::string cmd = "/usr/bin/poeny " + item->text().toStdString();
//    system(cmd.c_str());
    QString text = "file://" + item->text();
    QUrl url(text);
    if (QDesktopServices::openUrl(url)) {
        std::cout << "链接已打开：" << item->text().toStdString();
    } else {
        std::cout << "无法打开链接：" << item->text().toStdString();
    }
}
