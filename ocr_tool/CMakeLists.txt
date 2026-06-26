cmake_minimum_required(VERSION 3.10)
project(ocr_tool)

find_package(PkgConfig REQUIRED)

# 查找麒麟AI视觉SDK
pkg_check_modules(KYSDK_AI_VISION kysdk-coreai-vision)

# 查找GLib/GIO库
pkg_check_modules(GIO REQUIRED gio-2.0)
pkg_check_modules(GLIB REQUIRED glib-2.0)

# 包含头文件目录
include_directories(
    ${KYSDK_AI_VISION_INCLUDE_DIRS}
    ${GLIB_INCLUDE_DIRS}
    ${GIO_INCLUDE_DIRS}
)

# 设置C++标准
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 创建可执行文件
add_executable(${PROJECT_NAME} main.cpp)

# 链接库
target_link_libraries(
    ${PROJECT_NAME}
    ${KYSDK_AI_VISION_LIBRARIES}
    ${GLIB_LIBRARIES}
    ${GIO_LIBRARIES}
)

install(TARGETS ${PROJECT_NAME} DESTINATION /usr/bin/)
#libkysdk-coreai-vision-dev libglib2.0-dev
