cmake_minimum_required(VERSION 3.20)
project(djcat-updater C)

add_executable(updater updater.c)
target_link_libraries(updater PRIVATE shell32)

if(MSVC)
    target_compile_options(updater PRIVATE /W4 /utf-8)
    set_target_properties(updater PROPERTIES LINK_FLAGS "/MANIFESTUAC:\"level='asInvoker' uiAccess='false'\"")
else()
    target_compile_options(updater PRIVATE -Wall -Wextra)
endif()
