cmake_minimum_required(VERSION 3.16)

project(kylin-actuator LANGUAGES CXX)

set(TOP_DIR ${CMAKE_CURRENT_LIST_DIR})
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(SRCS
    ${TOP_DIR}/src/pubdef.h
    ${TOP_DIR}/src/pubdef.cpp
    ${TOP_DIR}/src/actuator.cpp
    ${TOP_DIR}/src/actuator.h
    ${TOP_DIR}/src/actuatormain.cpp
    ${TOP_DIR}/src/dbusmain.cpp
    ${TOP_DIR}/src/instructionset.cpp
    ${TOP_DIR}/src/instructionset.h
    ${TOP_DIR}/src/instructionlist.cpp
    ${TOP_DIR}/src/instructionlist.h
    ${TOP_DIR}/src/dbusclient.cpp
    ${TOP_DIR}/src/dbusclient.h
    ${TOP_DIR}/src/linkdialog.cpp
    ${TOP_DIR}/src/linkdialog.h
    ${TOP_DIR}/src/usd_global_define.h
    )

add_executable(${PROJECT_NAME} ${SRCS})

target_include_directories(${PROJECT_NAME} PRIVATE
    /usr/include/kabase/
    /usr/include/kysdk/applications/kabase/kylin_system/
    /usr/include/kabase/kylin_system/
    /usr/include/kysdk/applications/kabase/
    /usr/include/kysdk/applications/
    /usr/include/x86_64-linux-gnu/qt5
    )

target_compile_options(${PROJECT_NAME} PRIVATE -Wall -g)
target_compile_features(${PROJECT_NAME} PRIVATE cxx_std_11)

#find_package(Qt5 REQUIRED COMPONENTS Core)


#find_package(Qt5 REQUIRED COMPONENTS DBus)


find_package(Qt5 COMPONENTS Core Widgets DBus REQUIRED)
target_link_libraries(${PROJECT_NAME} PRIVATE Qt5::Widgets Qt5::Core Qt5::DBus)


find_package(PkgConfig REQUIRED)

pkg_check_modules(KYSDKQTWIDGETS_PKG kysdk-qtwidgets)

target_include_directories(${PROJECT_NAME} PRIVATE ${KYSDKQTWIDGETS_PKG_INCLUDE_DIRS})
target_link_directories(${PROJECT_NAME} PRIVATE ${KYSDKQTWIDGETS_PKG_LIBRARY_DIRS})

target_link_libraries(${PROJECT_NAME} PRIVATE ${KYSDKQTWIDGETS_PKG_LIBRARIES} kysdk-kabase)



install(TARGETS ${PROJECT_NAME} DESTINATION /usr/bin/)
#install(FILES ${TOP_DIR}/com.kylin.actuator.conf DESTINATION /etc/dbus-1/system.d/)
#install(FILES ${TOP_DIR}/com.kylin.actuator.service DESTINATION /usr/share/dbus-1/system-services/)
#install(FILES ${TOP_DIR}/com.kylin.actuator.limit DESTINATION /etc/dbus-1/conf/)
#install(FILES ${TOP_DIR}/com.kylin.actuator.limit DESTINATION /usr/share/dbus-1/conf/)
#install(FILES ${TOP_DIR}/com.kylin.actuator.limit.verify DESTINATION /etc/dbus-1/conf/)


#
