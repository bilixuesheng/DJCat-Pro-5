cmake_minimum_required(VERSION 3.20)
project(djcat-updater C)

add_executable(updater updater.c)
target_link_libraries(updater PRIVATE shell32 advapi32 user32)

if(MSVC)
    target_compile_options(updater PRIVATE /W4 /utf-8)
    # Every _vsnwprintf/wcsncat call is length-bounded explicitly; the _s
    # variants would only bury real warnings under C4996.
    target_compile_definitions(updater PRIVATE _CRT_SECURE_NO_WARNINGS)
    set_target_properties(updater PROPERTIES LINK_FLAGS "/MANIFESTUAC:\"level='asInvoker' uiAccess='false'\"")
else()
    target_compile_options(updater PRIVATE -Wall -Wextra)
endif()
